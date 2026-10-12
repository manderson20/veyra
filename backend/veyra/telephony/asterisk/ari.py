# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minimal client for the Asterisk REST Interface over loopback HTTP.

Only the handful of calls Veyra needs: engine information, module status
and reload, endpoints and channels. The URL must be a loopback address;
ARI is never exposed on the network (installer, verify.sh).
"""

from __future__ import annotations

import base64
import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from veyra.telephony.adapter import EngineUnavailable

_TIMEOUT_SECONDS = 5.0
LOOPBACK_PREFIXES = ("http://127.", "http://localhost", "http://[::1]")


class AriClient:
    def __init__(self, url: str, username: str, password_file: Path) -> None:
        self.url = url.rstrip("/")
        self.username = username
        self.password_file = password_file

    @property
    def is_loopback(self) -> bool:
        return self.url.startswith(LOOPBACK_PREFIXES)

    def password(self) -> str | None:
        try:
            return self.password_file.read_text().strip() or None
        except OSError:
            return None

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.is_loopback:
            raise EngineUnavailable("ARI must be reached over loopback.")
        password = self.password()
        if password is None:
            raise EngineUnavailable("ARI credentials are not configured.")
        url = f"{self.url}/{path.lstrip('/')}"
        if params:
            query = {k: str(v) for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(query)}"
        req = urllib.request.Request(url, method=method)  # noqa: S310
        auth = base64.b64encode(f"{self.username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        try:
            # Loopback HTTP only (checked above).
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:  # noqa: S310
                body = resp.read()
        except urllib.error.HTTPError as e:
            detail = ""
            with contextlib.suppress(ValueError, OSError):
                detail = json.loads(e.read().decode()).get("message", "")
            msg = f"ARI {method} {path} returned HTTP {e.code} {detail}".strip()
            raise EngineUnavailable(msg) from e
        except (urllib.error.URLError, OSError) as e:
            raise EngineUnavailable(f"ARI is not reachable: {e}") from e
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError as e:
            raise EngineUnavailable("ARI returned a response that is not JSON.") from e

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def put(self, path: str) -> Any:
        return self._request("PUT", path)

    # --- the calls Veyra uses --------------------------------------------------

    def info(self) -> dict[str, Any]:
        return self._request("GET", "asterisk/info") or {}

    def module(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"asterisk/modules/{name}") or {}

    def reload_module(self, name: str) -> None:
        self._request("PUT", f"asterisk/modules/{name}")

    def endpoints(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "endpoints") or [])

    def channels(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "channels") or [])

    def originate(
        self,
        endpoint: str,
        extension: str,
        context: str,
        caller_id: str,
        timeout: int,
    ) -> dict[str, Any]:
        """``POST /channels``: ring ``endpoint``; once it answers the channel
        runs the dialplan at ``extension@context`` (which places the call)."""
        return (
            self._request(
                "POST",
                "channels",
                {
                    "endpoint": endpoint,
                    "extension": extension,
                    "context": context,
                    "priority": 1,
                    "callerId": caller_id,
                    "timeout": timeout,
                },
            )
            or {}
        )
