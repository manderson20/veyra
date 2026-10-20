# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client of the voicemail store helper's socket (docs/USER_PORTAL.md §2.2):
one JSON request per connection, one JSON answer. The helper is
:mod:`veyra.voicemail.store`."""

from __future__ import annotations

import base64
import json
import socket
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from veyra.voicemail.store import MAX_LINE, SOCKET_PATH


class StoreClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class StoreUnavailable(StoreClientError):
    def __init__(self, message: str = "The voicemail store helper is not running.") -> None:
        super().__init__("vmstore_unavailable", message)


class StoreClient:
    def __init__(self, path: Path = SOCKET_PATH, timeout: float = 20.0) -> None:
        self.path, self.timeout = path, timeout

    def call(self, verb: str, **args: Any) -> Any:
        payload = json.dumps({"verb": verb, "args": args}, separators=(",", ":")).encode()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(str(self.path))
                s.sendall(payload + b"\n")
                s.shutdown(socket.SHUT_WR)
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = s.recv(1 << 16)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_LINE:
                        raise StoreClientError("bad_answer", "The helper's answer is too large.")
                    chunks.append(chunk)
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as e:
            raise StoreUnavailable() from e
        except (TimeoutError, OSError) as e:
            raise StoreClientError(
                "vmstore_error", f"The voicemail store did not answer: {e}"
            ) from e
        try:
            data = json.loads(b"".join(chunks))
        except ValueError as e:
            raise StoreClientError("bad_answer", "The helper's answer is not JSON.") from e
        if not isinstance(data, dict):
            raise StoreClientError("bad_answer", "The helper's answer is not an object.")
        if not data.get("ok"):
            raise StoreClientError(
                str(data.get("code") or "vmstore_error"), str(data.get("error") or "failed")
            )
        return data.get("result")

    # Typed conveniences --------------------------------------------------

    def ping(self) -> dict[str, Any]:
        return dict(self.call("ping"))

    def list(self, context: str, mailbox: str, folder: str = "INBOX") -> dict[str, Any]:
        return dict(self.call("list", context=context, mailbox=mailbox, folder=folder))

    def read(self, context: str, mailbox: str, folder: str, number: int) -> tuple[str, bytes]:
        r = self.call("read", context=context, mailbox=mailbox, folder=folder, number=number)
        return str(r["format"]), base64.b64decode(r["data"])

    def move(
        self,
        context: str,
        mailbox: str,
        folder: str,
        number: int,
        to: str,
        msg_id: str | None = None,
    ) -> dict[str, Any]:
        return dict(
            self.call(
                "move",
                context=context,
                mailbox=mailbox,
                folder=folder,
                number=number,
                to=to,
                msg_id=msg_id,
            )
        )

    def delete(
        self, context: str, mailbox: str, folder: str, number: int, msg_id: str | None = None
    ) -> dict[str, Any]:
        return dict(
            self.call(
                "delete",
                context=context,
                mailbox=mailbox,
                folder=folder,
                number=number,
                msg_id=msg_id,
            )
        )

    def delete_id(
        self, context: str, mailbox: str, msg_id: str, folders: Sequence[str] | None = None
    ) -> bool:
        r = self.call(
            "delete_id",
            context=context,
            mailbox=mailbox,
            msg_id=msg_id,
            folders=list(folders) if folders else None,
        )
        return bool(r["deleted"])

    def copy(
        self,
        context: str,
        mailbox: str,
        folder: str,
        number: int,
        to_context: str,
        to_mailbox: str,
        note: str = "",
    ) -> dict[str, Any]:
        return dict(
            self.call(
                "copy",
                context=context,
                mailbox=mailbox,
                folder=folder,
                number=number,
                to_context=to_context,
                to_mailbox=to_mailbox,
                note=note,
            )
        )

    def greetings(self, context: str, mailbox: str) -> dict[str, Any]:
        return dict(self.call("greetings", context=context, mailbox=mailbox)["greetings"])

    def greeting_get(self, context: str, mailbox: str, kind: str) -> tuple[str, bytes]:
        r = self.call("greeting_get", context=context, mailbox=mailbox, kind=kind)
        return str(r["format"]), base64.b64decode(r["data"])

    def greeting_put(
        self, context: str, mailbox: str, kind: str, data: bytes, fmt: str = "wav"
    ) -> None:
        self.call(
            "greeting_put",
            context=context,
            mailbox=mailbox,
            kind=kind,
            format=fmt,
            data=base64.b64encode(data).decode("ascii"),
        )

    def greeting_delete(self, context: str, mailbox: str, kind: str) -> bool:
        return bool(
            self.call("greeting_delete", context=context, mailbox=mailbox, kind=kind)["deleted"]
        )
