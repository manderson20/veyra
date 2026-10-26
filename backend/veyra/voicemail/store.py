# SPDX-License-Identifier: AGPL-3.0-or-later
"""The voicemail store helper (docs/USER_PORTAL.md §2.2).

Asterisk keeps messages and greetings under its spool,
``/var/spool/asterisk/voicemail/<context>/<mailbox>/``, owned by the
asterisk user and not reachable by the service account. This module is
served by ``veyra vmstore serve`` **as the asterisk user** (unit
``veyra-vmstore.service``) over a Unix socket the API connects to
(:mod:`veyra.voicemail.client`). It does a fixed set of things to a fixed
set of paths:

* ``list``: the messages of a folder, parsed from ``msgNNNN.txt``;
* ``read``: one message's audio (base64);
* ``move``, ``delete``, ``copy``: between the six folders, renumbering the
  folder afterwards so the sequence stays contiguous (Asterisk expects it)
  and holding Asterisk's own ``.lock`` while doing so;
* ``delete_id``: one message found by its ``msg_id`` in the given folders
  (the mail worker removes a message once its email was accepted);
* ``prune``: the messages older than a date in every folder (a box's
  ``keep_days``);
* ``greeting_get``, ``greeting_put``, ``greeting_delete``: the greetings
  (``unavail``, ``busy``, ``greet``, ``temp``, and Veyra's ``absence``).

Every argument is checked against a fixed pattern and every path must
resolve under the spool root without following symbolic links. The
protocol is one JSON request per connection and one JSON answer, like the
HA agent's.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import re
import socketserver
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("veyra.voicemail.store")

DEFAULT_SPOOL = Path("/var/spool/asterisk/voicemail")
SOCKET_PATH = Path("/run/veyra/vmstore.sock")
MAX_LINE = 16 * 1024 * 1024  # one request or answer (a base64 message fits)

FOLDERS = ("INBOX", "Old", "Work", "Family", "Friends", "Urgent")
# "absence" (issue #169) is Veyra's own: copied over "temp" while an
# extended absence is on; Asterisk never reads it.
GREETINGS = ("unavail", "busy", "greet", "temp", "absence")
AUDIO_FORMATS = ("wav", "WAV", "gsm")  # preference when reading
MAX_MESSAGES = 9999
MAX_AUDIO = 64 * 1024 * 1024

_CONTEXT_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")
_MAILBOX_RE = re.compile(r"^[0-9]{1,16}$")
_MSG_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_MSG_RE = re.compile(r"^msg(\d{4})\.(txt|wav|WAV|gsm)$")
_TXT_KEYS = (
    "origmailbox",
    "context",
    "exten",
    "rdnis",
    "callerid",
    "callerchan",
    "origdate",
    "origtime",
    "category",
    "msg_id",
    "flag",
    "duration",
)


class StoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _check(value: Any, pattern: re.Pattern[str], what: str) -> str:
    s = str(value or "")
    if not pattern.match(s):
        raise StoreError("bad_argument", f"{what} {s!r} is not valid")
    return s


def _check_folder(value: Any) -> str:
    s = str(value or "")
    if s not in FOLDERS:
        raise StoreError("bad_argument", f"folder {s!r} is not valid")
    return s


def _check_greeting(value: Any) -> str:
    s = str(value or "")
    if s not in GREETINGS:
        raise StoreError("bad_argument", f"greeting {s!r} is not valid")
    return s


def _check_number(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as e:
        raise StoreError("bad_argument", f"message number {value!r} is not valid") from e
    if not 0 <= n <= MAX_MESSAGES:
        raise StoreError("bad_argument", f"message number {n} is out of range")
    return n


def parse_message_txt(text: str) -> dict[str, Any]:
    """The ``[message]`` section Asterisk writes beside each recording."""
    out: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("[", ";", "#")):
            continue
        key, sep, value = line.partition("=")
        key = key.strip().lower()
        if sep and key in _TXT_KEYS:
            out[key] = value.strip()
    return out


class _FolderLock:
    """Asterisk's folder lock (``ast_lock_path``): a ``.lock`` file created
    with O_EXCL, retried for a few seconds. Held while renaming files."""

    def __init__(self, folder: Path, timeout: float = 5.0) -> None:
        self.path = folder / ".lock"
        self.timeout = timeout

    def __enter__(self) -> _FolderLock:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    continue
                if age > 60:  # a stale lock left by a crash
                    with contextlib.suppress(OSError):
                        self.path.unlink()
                    continue
                if time.monotonic() > deadline:
                    raise StoreError("busy", "the mailbox is in use; try again") from None
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()


class VoicemailStore:
    """File operations on one spool root; each public method is a verb."""

    def __init__(self, spool: Path = DEFAULT_SPOOL) -> None:
        self.spool = spool.resolve()

    # ------------------------------------------------------------ paths

    def _box_dir(self, context: Any, mailbox: Any) -> Path:
        ctx = _check(context, _CONTEXT_RE, "context")
        box = _check(mailbox, _MAILBOX_RE, "mailbox")
        path = self.spool / ctx / box
        self._inside(path)
        return path

    def _folder_dir(self, context: Any, mailbox: Any, folder: Any, *, create: bool = False) -> Path:
        path = self._box_dir(context, mailbox) / _check_folder(folder)
        if create and not path.exists():
            if not path.parent.exists():
                raise StoreError("not_found", "the mailbox has no messages yet")
            path.mkdir(mode=0o755)
        return path

    def _inside(self, path: Path) -> None:
        # The components are validated, so ".." cannot appear; links could.
        try:
            real = path.resolve(strict=False)
        except OSError as e:
            raise StoreError("not_found", str(e)) from e
        if real != path or not str(real).startswith(str(self.spool) + os.sep):
            raise StoreError("bad_argument", "the path leaves the spool")

    @staticmethod
    def _regular(path: Path) -> None:
        try:
            st = os.lstat(path)
        except FileNotFoundError as e:
            raise StoreError("not_found", f"{path.name} is missing") from e
        if not stat.S_ISREG(st.st_mode):
            raise StoreError("bad_argument", f"{path.name} is not a regular file")

    # ------------------------------------------------------------ messages

    def _messages(self, folder: Path) -> list[int]:
        if not folder.is_dir():
            return []
        numbers = set()
        for name in os.listdir(folder):
            m = _MSG_RE.match(name)
            if m and m.group(2) == "txt":
                numbers.add(int(m.group(1)))
        return sorted(numbers)

    def _audio_file(self, folder: Path, n: int) -> Path | None:
        for ext in AUDIO_FORMATS:
            p = folder / f"msg{n:04d}.{ext}"
            if p.is_file() and not p.is_symlink():
                return p
        return None

    def _entry(self, folder: Path, folder_name: str, n: int) -> dict[str, Any]:
        txt = folder / f"msg{n:04d}.txt"
        self._regular(txt)
        meta = parse_message_txt(txt.read_text(errors="replace"))
        audio = self._audio_file(folder, n)
        try:
            duration = int(meta.get("duration") or 0)
        except ValueError:
            duration = 0
        try:
            origtime = int(meta.get("origtime") or 0)
        except ValueError:
            origtime = 0
        return {
            "number": n,
            "folder": folder_name,
            "msg_id": meta.get("msg_id") or f"{origtime}-{n}",
            "callerid": meta.get("callerid") or "",
            "origtime": origtime,
            "origdate": meta.get("origdate") or "",
            "duration": duration,
            "urgent": (meta.get("flag") or "").lower() == "urgent",
            "format": audio.suffix.lstrip(".") if audio else None,
            "size": audio.stat().st_size if audio else 0,
        }

    def list_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        folder_name = _check_folder(args.get("folder", "INBOX"))
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        folder = box / folder_name
        entries = [self._entry(folder, folder_name, n) for n in self._messages(folder)]
        counts = {f: len(self._messages(box / f)) for f in FOLDERS}
        return {"messages": entries, "counts": counts}

    def read(self, args: dict[str, Any]) -> dict[str, Any]:
        folder_name = _check_folder(args.get("folder", "INBOX"))
        n = _check_number(args.get("number"))
        folder = self._folder_dir(args.get("context"), args.get("mailbox"), folder_name)
        audio = self._audio_file(folder, n)
        if audio is None:
            raise StoreError("not_found", "the message has no audio file")
        if audio.stat().st_size > MAX_AUDIO:
            raise StoreError("too_large", "the message is too large to send")
        entry = self._entry(folder, folder_name, n)
        return {
            "message": entry,
            "format": audio.suffix.lstrip("."),
            "data": base64.b64encode(audio.read_bytes()).decode("ascii"),
        }

    def _files_of(self, folder: Path, n: int) -> list[Path]:
        return [folder / f"msg{n:04d}.{ext}" for ext in ("txt", *AUDIO_FORMATS)]

    def _renumber(self, folder: Path) -> None:
        """Close the gaps so messages are msg0000..msgNNNN again."""
        for target, n in enumerate(self._messages(folder)):
            if n == target:
                continue
            for src in self._files_of(folder, n):
                if src.exists():
                    os.replace(src, folder / f"msg{target:04d}{src.suffix}")

    def _check_msg_id(self, folder: Path, folder_name: str, n: int, expected: Any) -> None:
        if expected:
            entry = self._entry(folder, folder_name, n)
            if entry["msg_id"] != str(expected):
                raise StoreError("message_moved", "the message list changed; reload it")

    def move(self, args: dict[str, Any]) -> dict[str, Any]:
        src_name = _check_folder(args.get("folder", "INBOX"))
        dst_name = _check_folder(args.get("to"))
        n = _check_number(args.get("number"))
        src = self._folder_dir(args.get("context"), args.get("mailbox"), src_name)
        dst = self._folder_dir(args.get("context"), args.get("mailbox"), dst_name, create=True)
        if src_name == dst_name:
            return {"moved": False}
        with _FolderLock(src), _FolderLock(dst):
            self._check_msg_id(src, src_name, n, args.get("msg_id"))
            if not (src / f"msg{n:04d}.txt").exists():
                raise StoreError("not_found", "no such message")
            target = len(self._messages(dst))
            if target > MAX_MESSAGES:
                raise StoreError("full", "the folder is full")
            for f in self._files_of(src, n):
                if f.exists():
                    os.replace(f, dst / f"msg{target:04d}{f.suffix}")
            self._renumber(src)
        return {"moved": True, "number": target}

    def delete(self, args: dict[str, Any]) -> dict[str, Any]:
        folder_name = _check_folder(args.get("folder", "INBOX"))
        n = _check_number(args.get("number"))
        folder = self._folder_dir(args.get("context"), args.get("mailbox"), folder_name)
        with _FolderLock(folder):
            self._check_msg_id(folder, folder_name, n, args.get("msg_id"))
            if not (folder / f"msg{n:04d}.txt").exists():
                raise StoreError("not_found", "no such message")
            for f in self._files_of(folder, n):
                with contextlib.suppress(FileNotFoundError):
                    f.unlink()
            self._renumber(folder)
        return {"deleted": True}

    def delete_id(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete the message whose ``msg_id`` matches, wherever it is among
        ``folders`` (default the inbox, Old and Urgent): its number may have
        changed since the id was taken. Nothing matching: ``deleted`` false."""
        msg_id = _check(args.get("msg_id"), _MSG_ID_RE, "message id")
        names = args.get("folders") or ["INBOX", "Old", "Urgent"]
        if not isinstance(names, list):
            raise StoreError("bad_argument", "folders must be a list")
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        for folder_name in [_check_folder(f) for f in names]:
            folder = box / folder_name
            if not folder.is_dir():
                continue
            with _FolderLock(folder):
                for n in self._messages(folder):
                    if self._entry(folder, folder_name, n)["msg_id"] != msg_id:
                        continue
                    for f in self._files_of(folder, n):
                        with contextlib.suppress(FileNotFoundError):
                            f.unlink()
                    self._renumber(folder)
                    return {"deleted": True, "folder": folder_name}
        return {"deleted": False}

    def prune(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete the messages received before ``before`` (epoch seconds) in
        every folder (voicemail pruning, issue #142); returns how many."""
        try:
            before = int(args.get("before"))  # type: ignore[arg-type]
        except (TypeError, ValueError) as e:
            raise StoreError("bad_argument", "before must be epoch seconds") from e
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        removed = 0
        for folder_name in FOLDERS:
            folder = box / folder_name
            if not folder.is_dir():
                continue
            with _FolderLock(folder):
                old = [
                    n
                    for n in self._messages(folder)
                    if 0 < int(self._entry(folder, folder_name, n)["origtime"] or 0) < before
                ]
                for n in old:
                    for f in self._files_of(folder, n):
                        with contextlib.suppress(FileNotFoundError):
                            f.unlink()
                if old:
                    self._renumber(folder)
                removed += len(old)
        return {"removed": removed}

    def copy(self, args: dict[str, Any]) -> dict[str, Any]:
        """Forward: copy a message into another mailbox's INBOX (same context
        or another), with a note of who forwarded it in the ``.txt``."""
        folder_name = _check_folder(args.get("folder", "INBOX"))
        n = _check_number(args.get("number"))
        src = self._folder_dir(args.get("context"), args.get("mailbox"), folder_name)
        dst_box = self._box_dir(args.get("to_context"), args.get("to_mailbox"))
        if not dst_box.exists():
            dst_box.mkdir(mode=0o755, parents=True)
        dst = dst_box / "INBOX"
        if not dst.exists():
            dst.mkdir(mode=0o755)
        txt = src / f"msg{n:04d}.txt"
        self._regular(txt)
        audio = self._audio_file(src, n)
        if audio is None:
            raise StoreError("not_found", "the message has no audio file")
        with _FolderLock(dst):
            target = len(self._messages(dst))
            if target > MAX_MESSAGES:
                raise StoreError("full", "the folder is full")
            text = txt.read_text(errors="replace")
            note = str(args.get("note") or "").replace("\n", " ")[:200]
            if note:
                text = text.rstrip("\n") + f"\nforwarded_by={note}\n"
            # Audio first, the index file last: a reader never sees a .txt
            # without its recording.
            (dst / f"msg{target:04d}{audio.suffix}").write_bytes(audio.read_bytes())
            (dst / f"msg{target:04d}.txt").write_text(text)
        return {"copied": True, "number": target}

    # ------------------------------------------------------------ greetings

    def greeting_get(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _check_greeting(args.get("kind"))
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        for ext in AUDIO_FORMATS:
            p = box / f"{kind}.{ext}"
            if p.is_file() and not p.is_symlink():
                if p.stat().st_size > MAX_AUDIO:
                    raise StoreError("too_large", "the greeting is too large to send")
                return {
                    "kind": kind,
                    "format": ext,
                    "data": base64.b64encode(p.read_bytes()).decode("ascii"),
                }
        raise StoreError("not_found", "no such greeting")

    def greetings(self, args: dict[str, Any]) -> dict[str, Any]:
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        out: dict[str, Any] = {}
        for kind in GREETINGS:
            found = None
            for ext in AUDIO_FORMATS:
                p = box / f"{kind}.{ext}"
                if p.is_file() and not p.is_symlink():
                    found = {"format": ext, "size": p.stat().st_size}
                    break
            out[kind] = found
        return {"greetings": out}

    def greeting_put(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _check_greeting(args.get("kind"))
        fmt = str(args.get("format") or "wav")
        if fmt not in AUDIO_FORMATS:
            raise StoreError("bad_argument", f"format {fmt!r} is not valid")
        try:
            data = base64.b64decode(str(args.get("data") or ""), validate=True)
        except ValueError as e:
            raise StoreError("bad_argument", "the audio is not valid base64") from e
        if not data or len(data) > MAX_AUDIO:
            raise StoreError("bad_argument", "the audio is empty or too large")
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        if not box.exists():
            box.mkdir(mode=0o755, parents=True)
        tmp = box / f".{kind}.{fmt}.tmp"
        tmp.write_bytes(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, box / f"{kind}.{fmt}")
        for ext in AUDIO_FORMATS:  # one format only: the new one plays
            if ext != fmt:
                with contextlib.suppress(FileNotFoundError):
                    (box / f"{kind}.{ext}").unlink()
        return {"saved": True, "format": fmt}

    def greeting_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _check_greeting(args.get("kind"))
        box = self._box_dir(args.get("context"), args.get("mailbox"))
        removed = 0
        for ext in AUDIO_FORMATS:
            p = box / f"{kind}.{ext}"
            if p.is_file() and not p.is_symlink():
                p.unlink()
                removed += 1
        return {"deleted": removed > 0}

    def ping(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"spool": str(self.spool), "readable": os.access(self.spool, os.R_OK | os.X_OK)}

    # ------------------------------------------------------------ protocol

    VERBS: dict[str, str] = {
        "ping": "ping",
        "list": "list_messages",
        "read": "read",
        "move": "move",
        "delete": "delete",
        "delete_id": "delete_id",
        "prune": "prune",
        "copy": "copy",
        "greetings": "greetings",
        "greeting_get": "greeting_get",
        "greeting_put": "greeting_put",
        "greeting_delete": "greeting_delete",
    }

    def handle(self, line: bytes) -> bytes:
        try:
            if len(line) > MAX_LINE:
                raise StoreError("too_large", "the request is too large")
            req = json.loads(line or b"{}")
            verb = str(req.get("verb") or "")
            args = req.get("args") if isinstance(req.get("args"), dict) else {}
            name = self.VERBS.get(verb)
            if name is None:
                raise StoreError("unknown_verb", f"Unknown verb {verb!r}.")
            fn: Callable[[dict[str, Any]], dict[str, Any]] = getattr(self, name)
            out: dict[str, Any] = {"ok": True, "result": fn(args)}
        except StoreError as e:
            out = {"ok": False, "code": e.code, "error": e.message}
        except (OSError, ValueError) as e:
            log.warning("verb failed: %s", e)
            out = {"ok": False, "code": "store_error", "error": f"{type(e).__name__}: {e}"}
        except Exception as e:  # pragma: no cover - defensive
            log.exception("verb failed")
            out = {"ok": False, "code": "store_error", "error": f"{type(e).__name__}: {e}"}
        return json.dumps(out, separators=(",", ":")).encode() + b"\n"

    def serve(self, path: Path = SOCKET_PATH, *, group: str = "veyra", once: bool = False) -> None:
        store = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                data = self.rfile.read(MAX_LINE + 1)
                self.wfile.write(store.handle(data))

        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        server.daemon_threads = True
        os.chmod(path, 0o660)
        with contextlib.suppress(KeyError, PermissionError, OSError):
            import grp

            os.chown(path, -1, grp.getgrnam(group).gr_gid)
        log.info("voicemail store listening on %s (spool %s)", path, self.spool)
        if once:
            server.handle_request()
            server.server_close()
            return
        t = threading.Thread(target=server.serve_forever, name="vmstore", daemon=True)
        t.start()
        try:
            while t.is_alive():
                t.join(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
