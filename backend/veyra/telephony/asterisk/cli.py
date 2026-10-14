# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asterisk command-line access for the few operations ARI does not offer:
sending a NOTIFY to a phone (docs/DEVICE_PROVISIONING.md §3.5). The service
account needs the control socket (the installer sets ``astctlgroup`` and
``astctlpermissions`` in ``asterisk.conf``)."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

log = logging.getLogger("veyra.telephony.cli")

NOTIFY_TYPES = {"check_config": "veyra-check-config", "reboot": "veyra-reboot"}
_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def asterisk_available() -> bool:
    return shutil.which("asterisk") is not None


def run(command: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Run one Asterisk CLI command; ``(ok, output)``."""
    binary = shutil.which("asterisk")
    if binary is None:
        return False, "the asterisk command is not installed on this server"
    try:
        proc = subprocess.run(  # noqa: S603 — fixed binary, validated arguments
            [binary, "-rx", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0 or "Unable to connect" in out:
        return False, out or f"asterisk -rx exited with {proc.returncode}"
    return True, out


def send_notify(action: str, endpoint: str) -> tuple[bool, str]:
    """NOTIFY ``endpoint`` with the type for ``action`` (check_config, reboot)."""
    notify = NOTIFY_TYPES.get(action)
    if notify is None:
        return False, f"unknown action {action!r}"
    if not _ENDPOINT_RE.match(endpoint):
        return False, "invalid endpoint name"
    ok, out = run(f"pjsip send notify {notify} endpoint {endpoint}")
    if ok and ("not found" in out.lower() or "unable" in out.lower()):
        return False, out
    log.info("notify %s to %s: %s (%s)", notify, endpoint, "sent" if ok else "failed", out[:200])
    return ok, out
