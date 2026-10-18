# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where every phone registers from (docs/CALL_FEATURES.md §2.1).

``GET /telephony/registrations`` lists each registered contact with the
address the phone advertised and the address the registration arrived
from, so an administrator can tell a phone on the LAN from one behind a
remote NAT, see its user agent, transport, expiry and round-trip time.
Scoped like the extension list: platform administrators see every
contact, others the contacts of extensions in their organizations.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import ContactOut, _visible, contact_out
from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.models import Extension, Organization, SipTrunk
from veyra.core.security.principal import Principal
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported, TelephonyAdapter
from veyra.telephony.snapshot import provisioned_phones, registration_limit

router = APIRouter(prefix="/telephony", tags=["telephony"])


class RegistrationRow(ContactOut):
    endpoint: str
    extension_id: uuid.UUID | None = None
    extension_number: str | None = None
    extension_name: str | None = None
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    # How many phones are registered on this endpoint and how many it accepts
    # (docs/EXTENSIONS.md §1); the limit is None for an unknown endpoint.
    registered: int = 1
    registration_limit: int | None = None


class TrunkRegistrationRow(BaseModel):
    """Veyra's own registration to a carrier (issue #45)."""

    trunk_id: uuid.UUID
    name: str
    slug: str
    host: str
    status: str | None  # the engine's word, None when the engine reports nothing
    state: str  # registered | rejected | registering | unregistered | unknown
    reachable: bool | None


class RegistrationsOut(BaseModel):
    registrations: list[RegistrationRow]
    available: bool
    message: str | None = None
    # Endpoints that are enabled but have no registered contact right now.
    unregistered: int = 0
    # Registration trunks and how their registration stands (platform administrators).
    trunks: list[TrunkRegistrationRow] = []


@router.get(
    "/registrations",
    response_model=RegistrationsOut,
    summary="Registered phones and where they register from",
)
def list_registrations(
    request: Request,
    principal: Principal = Depends(require("extensions.read")),
    db: Session = Depends(get_db),
    organization_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
) -> RegistrationsOut:
    adapter: TelephonyAdapter = request.app.state.telephony
    if Capability.REGISTRATIONS not in adapter.capabilities():
        return RegistrationsOut(
            registrations=[],
            available=False,
            message="The telephony engine cannot report registration addresses.",
        )
    try:
        rows = adapter.registrations()
    except (EngineUnavailable, NotSupported) as e:
        return RegistrationsOut(registrations=[], available=False, message=str(e))
    stmt = _visible(principal, "extensions.read").where(Extension.is_enabled.is_(True))
    if organization_id is not None:
        stmt = stmt.where(Extension.organization_id == organization_id)
    exts = db.scalars(stmt).all()
    orgs = {o.id: o.name for o in db.query(Organization).all()} if exts else {}
    by_endpoint = {e.endpoint_name: e for e in exts}
    phones = provisioned_phones(db, {e.id for e in exts})
    registered = Counter(r.endpoint for r in rows)
    needle = (q or "").strip().lower()
    out: list[RegistrationRow] = []
    seen: set[str] = set()
    for r in rows:
        ext = by_endpoint.get(r.endpoint)
        if ext is None and (not principal.is_platform_admin or organization_id is not None):
            continue
        seen.add(r.endpoint)
        row = RegistrationRow(
            **contact_out(r).model_dump(),
            endpoint=r.endpoint,
            extension_id=ext.id if ext else None,
            extension_number=ext.number if ext else None,
            extension_name=ext.display_name if ext else None,
            organization_id=ext.organization_id if ext else None,
            organization_name=orgs.get(ext.organization_id) if ext else None,
            registered=registered[r.endpoint],
            registration_limit=(
                registration_limit(ext.max_registrations, phones.get(ext.id, 0)) if ext else None
            ),
        )
        if needle and not any(
            needle in str(v).lower()
            for v in (
                row.endpoint,
                row.extension_number,
                row.extension_name,
                row.contact_host,
                row.source_host,
                row.user_agent,
            )
            if v
        ):
            continue
        out.append(row)
    # Known extensions first, then contacts no extension claims (platform administrators only).
    out.sort(
        key=lambda x: (
            x.extension_id is None,
            x.organization_name or "",
            x.extension_number or "",
            x.endpoint,
        )
    )
    unregistered = sum(1 for name in by_endpoint if name not in seen)
    trunks: list[TrunkRegistrationRow] = []
    if principal.is_platform_admin and organization_id is None:
        from veyra.api.v1.trunks import Live, registration_state, routing_name

        live = Live(
            {s.endpoint: s.registered for s in _safe(adapter.endpoint_statuses)},
            {r.section: r.status for r in _safe(adapter.trunk_registrations)},
        )
        for t in db.scalars(
            select(SipTrunk).where(SipTrunk.is_enabled.is_(True)).order_by(SipTrunk.name)
        ):
            name = routing_name(t)
            word = live.registrations.get(name) if t.auth_mode == "registration" else None
            reachable = live.reachable.get(name)
            if t.auth_mode != "registration":
                state = "unknown" if reachable is None else ("online" if reachable else "offline")
            else:
                state = registration_state(word) or ("registered" if word else "unknown")
            trunks.append(
                TrunkRegistrationRow(
                    trunk_id=t.id,
                    name=t.name,
                    slug=t.slug,
                    host=t.host,
                    status=word,
                    state=state,
                    reachable=reachable,
                )
            )
    return RegistrationsOut(
        registrations=out, available=True, unregistered=unregistered, trunks=trunks
    )


def _safe(call: Any) -> list[Any]:
    try:
        return list(call())
    except (EngineUnavailable, NotSupported):
        return []
