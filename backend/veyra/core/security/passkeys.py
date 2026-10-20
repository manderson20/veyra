# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passkeys (WebAuthn) as a second factor (issue #107; docs/MFA_DESIGN.md §2).

Thin wrapper around ``py_webauthn``: options for the browser, verification
of what it returns, and the stored credential ``{id, public_key, sign_count,
transports, aaguid}`` (base64url). The relying party is the host name the
browser used (``VEYRA_WEBAUTHN_RP_ID`` overrides it); WebAuthn refuses IP
addresses and pages with a certificate error, so the interface explains when
passkeys cannot work on the current address.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.parse
from typing import Any

from fastapi import Request
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from veyra.core.config import Settings
from veyra.core.models import MfaMethod, User


class PasskeyError(ValueError):
    pass


def relying_party(request: Request, settings: Settings) -> tuple[str, str]:
    """(rp_id, expected origin) for this request. The origin is what the
    browser shows: https and the Host header NGINX passes on."""
    host = (request.headers.get("host") or "").strip().lower()
    if not host:
        raise PasskeyError("the request names no host")
    name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    rp_id = (getattr(settings, "webauthn_rp_id", "") or name).strip().lower()
    try:
        ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        pass
    else:
        raise PasskeyError(
            "passkeys need the server's name, not its address: open Veyra by its host name "
            "(with a trusted certificate) to use them"
        )
    if not (name == rp_id or name.endswith("." + rp_id)):
        raise PasskeyError(f"this address ({name}) is not under the passkey domain {rp_id}")
    # The browser's Origin (with a non-default port, which NGINX's $host
    # drops) when it names this host; else https and the host.
    origin = (request.headers.get("origin") or "").strip().lower()
    parts = urllib.parse.urlsplit(origin)
    if parts.hostname == name and parts.scheme in ("https", "http"):
        if parts.scheme == "http" and name != "localhost":
            raise PasskeyError("passkeys need https")
        return rp_id, f"{parts.scheme}://{parts.netloc}"
    scheme = "http" if name == "localhost" else "https"
    return rp_id, f"{scheme}://{host}"


def _descriptors(methods: list[MfaMethod]) -> list[PublicKeyCredentialDescriptor]:
    out = []
    for m in methods:
        cred = m.credential or {}
        if m.type != "webauthn" or "id" not in cred:
            continue
        transports = []
        for t in cred.get("transports") or []:
            try:
                transports.append(AuthenticatorTransport(t))
            except ValueError:
                continue
        out.append(
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(cred["id"]), transports=transports or None
            )
        )
    return out


def registration_options(
    user: User, rp_id: str, rp_name: str, existing: list[MfaMethod]
) -> tuple[str, str]:
    """(options JSON for ``navigator.credentials.create``, challenge)."""
    opts = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_name=user.email,
        user_id=user.id.bytes,
        user_display_name=user.display_name,
        exclude_credentials=_descriptors(existing),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return options_to_json(opts), bytes_to_base64url(opts.challenge)


def verify_registration(
    credential: dict[str, Any], challenge: str, rp_id: str, origin: str
) -> dict[str, Any]:
    """The credential to store, or :class:`PasskeyError`."""
    try:
        v = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as e:
        raise PasskeyError(f"the passkey was not accepted: {e}") from e
    transports = (credential.get("response") or {}).get("transports") or []
    return {
        "id": bytes_to_base64url(v.credential_id),
        "public_key": bytes_to_base64url(v.credential_public_key),
        "sign_count": v.sign_count,
        "transports": [str(t) for t in transports][:8],
        "aaguid": str(v.aaguid),
        "backed_up": bool(getattr(v, "credential_backed_up", False)),
    }


def authentication_options(rp_id: str, methods: list[MfaMethod]) -> tuple[str, str]:
    opts = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=_descriptors(methods),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json(opts), bytes_to_base64url(opts.challenge)


def verify_authentication(
    credential: dict[str, Any], challenge: str, rp_id: str, origin: str, methods: list[MfaMethod]
) -> MfaMethod:
    """The passkey that signed, with its sign count updated."""
    cred_id = str(credential.get("id") or credential.get("rawId") or "")
    method = next(
        (m for m in methods if m.type == "webauthn" and (m.credential or {}).get("id") == cred_id),
        None,
    )
    if method is None:
        raise PasskeyError("this passkey is not registered for your account")
    stored = dict(method.credential or {})
    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=base64url_to_bytes(stored["public_key"]),
            credential_current_sign_count=int(stored.get("sign_count") or 0),
        )
    except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError) as e:
        raise PasskeyError(f"the passkey was not accepted: {e}") from e
    stored["sign_count"] = v.new_sign_count
    method.credential = stored
    return method


def options_dict(options_json: str) -> dict[str, Any]:
    return dict(json.loads(options_json))
