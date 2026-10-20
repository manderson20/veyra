# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pages started from a phone (issue #139): the paging dialplan sends
``UserEvent(VeyraPage, Org, Kind: zone|page, Slug, By)``; the page log gets a
``dial`` row and the ``page.sent`` webhook fires, as for pages Veyra starts."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Organization, Page, PageLog, PagingZone
from veyra.core.models.base import utcnow
from veyra.integrations import webhooks

log = logging.getLogger("veyra.paging")


def parse_userevent(userevent: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("Org", "Kind", "Slug", "By"):
        value = userevent.get(key)
        if value is None:
            value = userevent.get(key.lower())
        out[key.lower()] = str(value or "").strip()[:200]
    return out


def handle_userevent(db: Session, userevent: dict[str, Any]) -> bool:
    f = parse_userevent(userevent)
    org = db.scalar(select(Organization).where(Organization.slug == f["org"]))
    if org is None or f["kind"] not in ("zone", "page"):
        return False
    caller = f["by"] or None
    if f["kind"] == "zone":
        zone = db.scalar(
            select(PagingZone).where(
                PagingZone.organization_id == org.id, PagingZone.slug == f["slug"]
            )
        )
        if zone is None:
            return False
        name, zones, page_id = zone.name, [zone], None
        subject: dict[str, Any] = {"zone": {"name": zone.name, "slug": zone.slug}}
    else:
        page = db.scalar(select(Page).where(Page.organization_id == org.id, Page.slug == f["slug"]))
        if page is None:
            return False
        from veyra.api.v1.pages import _zones_of

        zones = _zones_of(db, {page.id})[page.id]
        name, page_id = page.name, page.id
        subject = {"page": {"id": str(page.id), "name": page.name, "number": page.number}}
    db.add(
        PageLog(
            id=uuid.uuid4(),
            at=utcnow(),
            organization_id=org.id,
            page_id=page_id,
            page_name=name,
            zones=[z.slug for z in zones],
            trigger="dial",
            actor=caller,
            outcome="started",
            detail={"kind": f["kind"]},
        )
    )
    webhooks.emit(
        db,
        org.id,
        "page.sent",
        {
            **subject,
            "zones": [{"name": z.name, "slug": z.slug} for z in zones],
            "audio": None,
            "trigger": "dial",
            "started_by": caller,
        },
    )
    return True
