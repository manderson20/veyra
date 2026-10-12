"""Asterisk adapter (Milestone 0: health only).

Uses the Asterisk REST Interface (ARI) over loopback HTTP. ARI is bound to
127.0.0.1 by the installer and never exposed publicly. Configuration
generation and reload arrive in Milestones 3-5.
"""

from __future__ import annotations

import base64
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from veyra.telephony.adapter import Capability, EngineHealth, TelephonyAdapter

_TIMEOUT_SECONDS = 2.0


class AsteriskAdapter(TelephonyAdapter):
    name = "asterisk"

    def __init__(self, ari_url: str, username: str, password_file: Path) -> None:
        self.ari_url = ari_url.rstrip("/")
        self.username = username
        self.password_file = password_file

    def capabilities(self) -> set[Capability]:
        return {Capability.HEALTH}

    def _password(self) -> str | None:
        try:
            return self.password_file.read_text().strip() or None
        except OSError:
            return None

    def health(self) -> EngineHealth:
        if shutil.which("asterisk") is None and not Path("/usr/sbin/asterisk").exists():
            return EngineHealth("not_installed", self.name, message="Asterisk is not installed.")
        password = self._password()
        if password is None:
            return EngineHealth(
                "not_configured", self.name, message="ARI credentials are not configured."
            )
        if not self.ari_url.startswith(("http://127.", "http://localhost", "http://[::1]")):
            return EngineHealth(
                "not_configured", self.name, message="ARI must be reached over loopback."
            )
        req = urllib.request.Request(f"{self.ari_url}/asterisk/info")  # noqa: S310
        auth = base64.b64encode(f"{self.username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        try:
            # Loopback HTTP only (checked above).
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:  # noqa: S310
                info = json.load(resp)
        except urllib.error.HTTPError as e:
            return EngineHealth("unreachable", self.name, message=f"ARI returned HTTP {e.code}.")
        except (urllib.error.URLError, OSError, ValueError) as e:
            return EngineHealth("unreachable", self.name, message=f"ARI is not reachable: {e}")
        build = info.get("system", {}).get("version") or info.get("build", {}).get("version")
        return EngineHealth(
            "running",
            self.name,
            version=build,
            message="Asterisk is running.",
            details={"entity_id": info.get("system", {}).get("entity_id")},
        )
