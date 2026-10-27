# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension templates (issue #172): one set of settings many extensions
follow, from the Metaswitch comparison's "Call Service Groups". A template
sets some of the fields below; the extension takes them when it is created
with the template or when the template is applied again, and while it
follows the template the ``locked`` fields cannot be changed on it."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import (
    ClassOfService,
    Department,
    Extension,
    ExtensionTemplate,
    VoicemailBox,
)
from veyra.core.models.base import utcnow
from veyra.telephony import extension_state

# field -> where it lives: "extension" (a column), "state" (ExtensionState)
# or "voicemail" (the extension's own box, when it has one).
FIELDS: dict[str, str] = {
    "class_of_service_id": "extension",
    "intercom": "extension",
    "max_registrations": "extension",
    "department_id": "extension",
    "outbound_caller_id_number": "extension",
    "outbound_caller_id_name": "extension",
    "ring_seconds": "state",
    "call_waiting_off": "state",
    "anonymous_reject": "state",
    "cf_busy": "state",
    "cf_no_answer": "state",
    "cf_unavailable": "state",
    "vm_attach_audio": "voicemail",
    "vm_delete_after_email": "voicemail",
    "vm_keep_days": "voicemail",
    "vm_operator_extension": "voicemail",
}
# Fields a change of which waits for a deployment (the rest is live).
DEPLOYED = {
    "class_of_service_id",
    "intercom",
    "max_registrations",
    "ring_seconds",
    "outbound_caller_id_number",
    "outbound_caller_id_name",
    "vm_attach_audio",
    "vm_delete_after_email",
    "vm_operator_extension",
}
_FORWARDS = ("cf_busy", "cf_no_answer", "cf_unavailable")
_CID_NUMBER_RE = re.compile(r"^\+?[0-9]{2,20}$")
_CID_NAME_RE = re.compile(r"^[A-Za-z0-9 .'&()-]{1,60}$")


def voicemail_field(field: str) -> str:
    """The VoicemailBox column of a ``vm_`` template field."""
    return field.removeprefix("vm_")


class TemplateError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field, self.message = field, message


def normalize(
    db: Session, organization_id: uuid.UUID, settings: dict[str, Any], locked: list[str]
) -> tuple[dict[str, Any], list[str]]:
    """Check a template's settings and locks; values as stored (JSON)."""
    out: dict[str, Any] = {}
    for field, value in settings.items():
        if field not in FIELDS:
            raise TemplateError(field, "not a template field")
        if field in ("class_of_service_id", "department_id"):
            if value in (None, ""):
                out[field] = None
                continue
            try:
                ref = uuid.UUID(str(value))
            except ValueError as e:
                raise TemplateError(field, "not an id") from e
            model: Any = ClassOfService if field == "class_of_service_id" else Department
            row = db.get(model, ref)
            if row is None or row.organization_id != organization_id:
                raise TemplateError(field, "not in this organization")
            out[field] = str(ref)
        elif field == "intercom":
            if value not in ("default", "allow", "deny"):
                raise TemplateError(field, "default, allow or deny")
            out[field] = value
        elif field == "max_registrations":
            if value in (None, ""):
                out[field] = None
            elif not isinstance(value, int) or not 1 <= value <= 16:
                raise TemplateError(field, "1 to 16, or empty")
            else:
                out[field] = value
        elif field in _FORWARDS:
            try:
                out[field] = extension_state.normalize_number(field, value)
            except extension_state.StateError as e:
                raise TemplateError(field, e.message) from e
        elif field in ("outbound_caller_id_number", "outbound_caller_id_name"):
            text = str(value or "").strip()
            pattern = _CID_NUMBER_RE if field.endswith("number") else _CID_NAME_RE
            if text and not pattern.match(text):
                raise TemplateError(field, "not a valid caller ID")
            out[field] = text or None
        elif field == "vm_keep_days":
            if value in (None, ""):
                out[field] = None
            elif not isinstance(value, int) or not 1 <= value <= 3650:
                raise TemplateError(field, "1 to 3650 days, or empty")
            else:
                out[field] = value
        elif field == "vm_operator_extension":
            number = str(value or "").strip()
            if number and (
                db.scalar(
                    select(Extension.id).where(
                        Extension.organization_id == organization_id, Extension.number == number
                    )
                )
                is None
            ):
                raise TemplateError(field, f"extension {number} is not in this organization")
            out[field] = number or None
        elif field == "ring_seconds":
            if not isinstance(value, int) or not (
                extension_state.RING_MIN <= value <= extension_state.RING_MAX
            ):
                raise TemplateError(field, "5 to 120 seconds")
            out[field] = value
        else:
            if not isinstance(value, bool):
                raise TemplateError(field, "true or false")
            out[field] = value
    if out.get("vm_delete_after_email") and out.get("vm_attach_audio") is False:
        raise TemplateError("vm_delete_after_email", "needs the recording attached to the email")
    for field in locked:
        if field not in out:
            raise TemplateError("locked", f"{field} is locked but the template does not set it")
    return out, sorted(set(locked))


def _box(db: Session, ext: Extension) -> VoicemailBox | None:
    return db.scalar(select(VoicemailBox).where(VoicemailBox.extension_id == ext.id))


def _current(db: Session, ext: Extension) -> dict[str, Any]:
    state = extension_state.get(db, ext.id)
    box = _box(db, ext)
    vm: dict[str, Any] = (
        {
            "vm_attach_audio": box.attach_audio,
            "vm_delete_after_email": box.delete_after_email,
            "vm_keep_days": box.keep_days,
            "vm_operator_extension": box.operator_extension,
        }
        if box is not None
        else {}
    )
    return {
        **vm,
        "outbound_caller_id_number": ext.outbound_caller_id_number,
        "outbound_caller_id_name": ext.outbound_caller_id_name,
        **{f: getattr(state, f) if state else None for f in _FORWARDS},
        "class_of_service_id": str(ext.class_of_service_id) if ext.class_of_service_id else None,
        "intercom": ext.intercom,
        "max_registrations": ext.max_registrations,
        "department_id": str(ext.department_id) if ext.department_id else None,
        "ring_seconds": state.ring_seconds if state else extension_state.RING_DEFAULT,
        "call_waiting_off": bool(state.call_waiting_off) if state else False,
        "anonymous_reject": bool(state.anonymous_reject) if state else False,
    }


def differences(
    db: Session, template: ExtensionTemplate, ext: Extension, only: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    """field -> {from, to} where the extension differs from the template.
    Voicemail fields count only for an extension with its own box, and
    delete-after-email only for a box with an email address."""
    have = _current(db, ext)
    box = _box(db, ext) if "vm_delete_after_email" in (template.settings or {}) else None
    return {
        f: {"from": have[f], "to": v}
        for f, v in (template.settings or {}).items()
        if f in FIELDS
        and (only is None or f in only)
        and f in have
        and have[f] != v
        and not (f == "vm_delete_after_email" and v and not (box and box.email))
    }


def apply(
    db: Session,
    template: ExtensionTemplate,
    ext: Extension,
    *,
    by: str,
    adapter: Any = None,
    only: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Give the extension the template's values (``only``: just these
    fields). State switches reach the engine at once; the rest waits for a
    deployment, which the caller marks when DEPLOYED fields changed."""
    diff = differences(db, template, ext, only)
    state_changes: dict[str, Any] = {}
    for field, change in diff.items():
        value = change["to"]
        if FIELDS[field] == "voicemail":
            box = _box(db, ext)
            if box is not None:
                setattr(box, voicemail_field(field), value)
                if field == "vm_delete_after_email" and value:
                    box.attach_audio = True
        elif FIELDS[field] == "extension":
            if field in ("class_of_service_id", "department_id"):
                value = uuid.UUID(value) if value else None
            setattr(ext, field, value)
        elif field == "ring_seconds":
            row = extension_state.ensure(db, ext)
            row.ring_seconds = int(value)
            row.updated_by = "admin"
            row.updated_at = utcnow()
        else:
            state_changes[field] = value
    if state_changes:
        extension_state.apply(db, ext, state_changes, by=by, adapter=adapter)
    db.flush()
    return diff


def members(db: Session, template: ExtensionTemplate) -> list[Extension]:
    return list(
        db.scalars(
            select(Extension).where(Extension.template_id == template.id).order_by(Extension.number)
        )
    )


def locked_change(
    db: Session, ext: Extension, changes: dict[str, Any]
) -> tuple[str, ExtensionTemplate] | None:
    """The first locked field ``changes`` would move away from the
    extension's template, with the template; None when nothing is locked."""
    if ext.template_id is None:
        return None
    template = db.get(ExtensionTemplate, ext.template_id)
    if template is None:
        return None
    have = _current(db, ext)
    for field in template.locked or []:
        if field not in changes:
            continue
        value = changes[field]
        if isinstance(value, uuid.UUID):
            value = str(value)
        # Resending the value it has is no change (a form sends every field).
        if value != have.get(field) and value != (template.settings or {}).get(field):
            return field, template
    return None
