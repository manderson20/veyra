# SPDX-License-Identifier: AGPL-3.0-or-later
"""The root capture runner (docs/CALL_FEATURES.md §2.2): one fixed tcpdump
command for one recorded capture, the duration and size limit enforced
here, the file handed to the service account, the outcome recorded through
``veyra capture record``. Runs from ``veyra-capture@<id>.service``.

Root has no database role: the capture's definition is read through the
service account (``veyra capture show``), and its filter expression is
rebuilt from the validated fields, never taken from the row as text.
"""

from __future__ import annotations

import grp
import json
import logging
import os
import pwd
import re
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from veyra.diagnostics import filters

log = logging.getLogger("veyra.capture")

VEYRA_CLI = "/usr/local/bin/veyra"
TCPDUMP = "/usr/bin/tcpdump"
DEFAULT_DIRECTORY = Path(os.environ.get("VEYRA_DATA_DIR") or "/var/lib/veyra") / "captures"
SERVICE_USER = "veyra"
_CAPTURED_RE = re.compile(r"(\d+) packets? captured")


class CaptureRunError(RuntimeError):
    pass


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], Result]


def subprocess_runner(timeout: float = 60) -> Runner:
    def run(argv: Sequence[str]) -> Result:
        try:
            p = subprocess.run(  # noqa: S603 - fixed argv built here
                list(argv), capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return Result(127, "", str(e))
        return Result(p.returncode, p.stdout, p.stderr)

    return run


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def tcpdump_argv(path: Path, expression: str, binary: str = TCPDUMP) -> list[str]:
    """The one command the unit runs: every interface, no name resolution,
    whole packets, stay root (the file lands in the service account's
    directory), packet-buffered writes so a stop loses nothing."""
    return [binary, "-i", "any", "-nn", "-s", "0", "-Z", "root", "-U", "-w", str(path), expression]


def load(run: Runner, capture_id: str) -> dict[str, Any]:
    r = run(
        ["runuser", "-u", SERVICE_USER, "--", VEYRA_CLI, "capture", "show", capture_id, "--json"]
    )
    if not r.ok:
        raise CaptureRunError(f"reading the capture: {(r.stderr or r.stdout).strip()[:300]}")
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise CaptureRunError("the capture record is not JSON") from e
    if not isinstance(data, dict) or str(data.get("id")) != capture_id:
        raise CaptureRunError("the capture record does not match")
    return data


def record(run: Runner, payload: dict[str, Any]) -> Result:
    return run(
        [
            "runuser",
            "-u",
            SERVICE_USER,
            "--",
            VEYRA_CLI,
            "capture",
            "record",
            "--json",
            json.dumps(payload, default=str),
        ]
    )


def hand_over(path: Path) -> None:
    """The finished file belongs to the service account (0640), which serves,
    summarises, prunes and deletes it."""
    try:
        os.chmod(path, 0o640)
        if os.geteuid() == 0:
            os.chown(path, pwd.getpwnam(SERVICE_USER).pw_uid, grp.getgrnam(SERVICE_USER).gr_gid)
    except (OSError, KeyError) as e:
        log.warning("Could not hand %s to the service account: %s", path, e)


def run_capture(
    capture_id: str,
    *,
    run: Runner | None = None,
    binary: str = TCPDUMP,
    directory: Path = DEFAULT_DIRECTORY,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    handle_signals: bool = True,
) -> dict[str, Any]:
    """The whole sequence; returns the recorded payload."""
    run = run or subprocess_runner()
    capture_id = str(uuid.UUID(capture_id))
    payload: dict[str, Any] = {"id": capture_id, "state": "failed"}
    stopping = {"flag": False}

    def on_term(_signum: int, _frame: Any) -> None:
        stopping["flag"] = True

    if handle_signals:
        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGINT, on_term)
    proc = None
    path = directory / f"{capture_id}.pcap"
    try:
        data = load(run, capture_id)
        spec = filters.normalize(data.get("filter") or {})
        expression = filters.expression(spec)
        duration = min(max(int(data.get("duration_seconds") or 120), 10), 30 * 60)
        limit = min(max(int(data.get("size_limit_mb") or 50), 1), 500) * 1024 * 1024
        directory.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        proc = popen(
            tcpdump_argv(path, expression, binary),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        record(run, {"id": capture_id, "state": "running", "path": str(path)})
        started = clock()
        outcome, note = "finished", None
        while proc.poll() is None:
            sleep(0.5)
            if stopping["flag"]:
                outcome = "stopped"
                break
            if clock() - started >= duration:
                break
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size >= limit:
                note = "size limit reached"
                break
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
        stderr = (proc.stderr.read() if proc.stderr else "") or ""
        m = _CAPTURED_RE.search(stderr)
        packets = int(m.group(1)) if m else None
        exists = path.is_file()
        if not exists or (packets is None and proc.returncode not in (0, -15)):
            tail = [ln for ln in stderr.strip().splitlines() if ln.strip()]
            raise CaptureRunError(
                tail[-1][:300] if tail else f"tcpdump exited with {proc.returncode}"
            )
        hand_over(path)
        payload.update(
            {
                "state": outcome,
                "path": str(path),
                "bytes": path.stat().st_size,
                "packets": packets,
                "error": note,
                "finished_at": _now(),
            }
        )
    except Exception as e:
        log.exception("Capture failed")
        if proc is not None and proc.poll() is None:
            proc.kill()
        payload.update({"state": "failed", "error": str(e)[:1000], "finished_at": _now()})
        if path.is_file():
            hand_over(path)
            payload["bytes"] = path.stat().st_size
    r = record(run, payload)
    if not r.ok:
        log.error("Could not record the capture: %s", (r.stderr or r.stdout).strip()[:300])
    return payload
