# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone directory (docs/PROVISIONING_BREADTH.md §5): an organization's
extensions and ring groups in the formats the phone families download."""

from __future__ import annotations

import csv
import io
import uuid
from xml.sax.saxutils import escape, quoteattr

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Extension, RingGroup

FORMATS = {
    "poly.xml": "application/xml",
    "yealink.xml": "application/xml",
    "grandstream.xml": "application/xml",
    "contacts.csv": "text/csv",
}


def entries(db: Session, organization_id: uuid.UUID) -> list[tuple[str, str]]:
    """(name, number) of the enabled extensions and ring groups, by name."""
    out = [
        (e.display_name or e.number, e.number)
        for e in db.scalars(
            select(Extension).where(
                Extension.organization_id == organization_id, Extension.is_enabled.is_(True)
            )
        )
    ]
    out += [
        (g.name, g.number)
        for g in db.scalars(
            select(RingGroup).where(
                RingGroup.organization_id == organization_id, RingGroup.is_enabled.is_(True)
            )
        )
    ]
    return sorted(out, key=lambda e: (e[0].lower(), e[1]))


def render(fmt: str, rows: list[tuple[str, str]], title: str) -> str:
    if fmt == "poly.xml":
        items = "".join(
            f"<item><fn>{escape(n)}</fn><ct>{escape(num)}</ct></item>" for n, num in rows
        )
        head = '<?xml version="1.0" encoding="UTF-8"?>'
        return f"{head}<directory><item_list>{items}</item_list></directory>"
    if fmt == "yealink.xml":
        units = "".join(f"<Unit Name={quoteattr(n)} Phone1={quoteattr(num)} />" for n, num in rows)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<YealinkIPPhoneBook><Title>{escape(title)}</Title>"
            f"<Menu Name={quoteattr(title)}>{units}</Menu></YealinkIPPhoneBook>"
        )
    if fmt == "grandstream.xml":
        contacts = "".join(
            f'<Contact><FirstName>{escape(n)}</FirstName><Phone type="Work">'
            f"<phonenumber>{escape(num)}</phonenumber><accountindex>1</accountindex></Phone></Contact>"
            for n, num in rows
        )
        return f'<?xml version="1.0" encoding="UTF-8"?><AddressBook>{contacts}</AddressBook>'
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "number"])
    for n, num in rows:
        w.writerow([n, num])
    return buf.getvalue()
