# SPDX-License-Identifier: AGPL-3.0-or-later
"""SRTP per device profile (docs/PRODUCTION_HARDENING.md §3.3, issue #49). The
keys travel in the signalling (SDES), so SRTP without TLS would only look safe:
it counts only on the TLS transport, for the phone's file and the engine alike.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MODES = ("off", "optional", "required")


def requested(values: dict[str, Any]) -> str:
    mode = str(values.get("srtp") or "off")
    return mode if mode in MODES else "off"


def effective(values: dict[str, Any], sip: Any) -> str:
    if str(values.get("sip_transport") or "UDPOnly") != "TLS" or not sip.tls_enabled:
        return "off"
    return requested(values)


def problem(values: dict[str, Any], sip: Any) -> str | None:
    """Why the SRTP asked for is not in effect, for the person setting it."""
    if requested(values) == "off":
        return None
    if str(values.get("sip_transport") or "UDPOnly") != "TLS":
        return "SRTP needs the TLS transport: the encryption keys travel in the signalling."
    if not sip.tls_enabled:
        return "SRTP needs TLS, which is off in Telephony settings."
    return None


def for_extension(modes: Iterable[str]) -> str:
    """The engine's setting for one extension, from the phones that carry it.
    Plain audio is refused only when every phone encrypts, so that a shared
    extension never loses a phone: any mix falls back to optional."""
    found = set(modes)
    if not found or found == {"off"}:
        return "off"
    return "required" if found == {"required"} else "optional"
