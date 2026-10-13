# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call destinations shared by inbound routes and IVR menus
(docs/VOICEMAIL_IVR.md §6): an extension, an extension's voicemail box, an
IVR menu, or (menus only) a hang-up. Validation checks that the target
exists in the organization and is usable; output carries a label and a
``missing`` flag so the interface can show a broken target."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.errors import ProblemError
from veyra.core.models import Extension, IvrMenu, VoicemailBox

DestinationType = Literal["extension", "voicemail", "ivr", "hangup"]


def validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


class DestinationIn(BaseModel):
    type: DestinationType = "extension"
    extension_id: uuid.UUID | None = None
    ivr_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _shape(self) -> DestinationIn:
        if self.type in ("extension", "voicemail"):
            self.ivr_id = None
        elif self.type == "ivr":
            self.extension_id = None
        else:
            self.extension_id = None
            self.ivr_id = None
        return self


class DestinationOut(BaseModel):
    type: str
    extension_id: uuid.UUID | None
    ivr_id: uuid.UUID | None
    # Human form: "2214 — Front Office", "Voicemail of 2214 (Front Office)",
    # "Menu: Main menu", "Hang up"; None when the target is gone.
    label: str | None
    missing: bool


def check_destination(
    db: Session,
    organization_id: uuid.UUID,
    dest: DestinationIn,
    *,
    field: str,
    allow_hangup: bool,
    exclude_ivr: uuid.UUID | None = None,
) -> None:
    """422 when the target is absent, in another organization or unusable."""
    if dest.type == "hangup":
        if not allow_hangup:
            raise validation(field, "choose where the call goes")
        return
    if dest.type == "ivr":
        if dest.ivr_id is None:
            raise validation(field, "choose the IVR menu")
        menu = db.get(IvrMenu, dest.ivr_id)
        if menu is None or menu.organization_id != organization_id:
            raise validation(field, "IVR menu not found in this organization")
        if not menu.is_enabled:
            raise validation(field, f"the menu {menu.name} is disabled")
        return
    if dest.extension_id is None:
        raise validation(field, "choose the extension")
    ext = db.get(Extension, dest.extension_id)
    if ext is None or ext.organization_id != organization_id:
        raise validation(field, "extension not found in this organization")
    if dest.type == "voicemail":
        box = db.scalar(select(VoicemailBox).where(VoicemailBox.extension_id == ext.id))
        if box is None:
            raise validation(field, f"extension {ext.number} has no voicemail box")
        if not box.is_enabled:
            raise validation(field, f"the voicemail box of {ext.number} is disabled")


class Resolver:
    """Loads the targets of many destinations at once and labels them."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.extensions: dict[uuid.UUID, Extension] = {}
        self.menus: dict[uuid.UUID, IvrMenu] = {}
        self.boxes: dict[uuid.UUID, VoicemailBox] = {}
        self._loaded: set[uuid.UUID] = set()

    def load(self, refs: list[tuple[str, Any, Any]]) -> None:
        ext_ids = {e for t, e, _ in refs if e and t in ("extension", "voicemail")}
        ivr_ids = {i for t, _, i in refs if i and t == "ivr"}
        ext_ids -= self._loaded
        ivr_ids -= self._loaded
        if ext_ids:
            for e in self.db.scalars(select(Extension).where(Extension.id.in_(ext_ids))):
                self.extensions[e.id] = e
            for b in self.db.scalars(
                select(VoicemailBox).where(VoicemailBox.extension_id.in_(ext_ids))
            ):
                self.boxes[b.extension_id] = b
        if ivr_ids:
            for m in self.db.scalars(select(IvrMenu).where(IvrMenu.id.in_(ivr_ids))):
                self.menus[m.id] = m
        self._loaded |= ext_ids | ivr_ids

    def out(self, kind: str | None, extension_id: Any, ivr_id: Any) -> DestinationOut:
        kind = kind or "extension"
        if kind == "hangup":
            return DestinationOut(
                type="hangup", extension_id=None, ivr_id=None, label="Hang up", missing=False
            )
        if kind == "ivr":
            menu = self.menus.get(ivr_id) if ivr_id else None
            ok = menu is not None and menu.is_enabled
            return DestinationOut(
                type="ivr",
                extension_id=None,
                ivr_id=ivr_id,
                label=(
                    f"Menu: {menu.name}" + ("" if menu.is_enabled else " (disabled)")
                    if menu
                    else None
                ),
                missing=not ok,
            )
        ext = self.extensions.get(extension_id) if extension_id else None
        if ext is None:
            return DestinationOut(
                type=kind, extension_id=extension_id, ivr_id=None, label=None, missing=True
            )
        if kind == "voicemail":
            box = self.boxes.get(ext.id)
            ok = box is not None and box.is_enabled
            label = f"Voicemail of {ext.number} ({ext.display_name})"
            if box is None:
                label += " (no box)"
            elif not box.is_enabled:
                label += " (box disabled)"
            return DestinationOut(
                type="voicemail", extension_id=ext.id, ivr_id=None, label=label, missing=not ok
            )
        return DestinationOut(
            type="extension",
            extension_id=ext.id,
            ivr_id=None,
            label=f"{ext.number} — {ext.display_name}",
            missing=False,
        )
