# SPDX-License-Identifier: AGPL-3.0-or-later
"""Feature codes (docs/CALL_FEATURES.md §3.1): what a phone dials to change
its own state. Defaults follow FreePBX so a migrating site keeps its habits;
an administrator may change or disable each code. Stored as one settings
document (``telephony.feature_codes``) holding only the overrides, so a new
default reaches every installation without a migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

SETTINGS_KEY = "telephony.feature_codes"
# Codes that are part of the dialplan since earlier milestones and never move.
FIXED_CODES: dict[str, str] = {
    "*43": "echo test",
    "*60": "speaking clock",
    "*8": "group pickup",
    "*95": "prompt recording",
    "*97": "own voicemail",
    "*98": "any voicemail box",
}
FIXED_PREFIXES = ("**",)  # directed pickup **<ext>
_CODE_RE = re.compile(r"^[*#][0-9*#]{0,6}$")


@dataclass(frozen=True)
class FeatureCodeDef:
    key: str
    code: str
    label: str
    description: str
    milestone: int
    # The code is followed by a number (``*72<number>``) as well as dialled alone.
    takes_number: bool = False


DEFAULTS: tuple[FeatureCodeDef, ...] = (
    FeatureCodeDef(
        "dnd_on", "*78", "Do Not Disturb on", "Callers hear busy or the busy greeting.", 18
    ),
    FeatureCodeDef("dnd_off", "*79", "Do Not Disturb off", "The phone rings again.", 18),
    FeatureCodeDef(
        "dnd_toggle", "*76", "Do Not Disturb toggle", "Also the BLF hint: a key lit while on.", 18
    ),
    FeatureCodeDef(
        "cf_on",
        "*72",
        "Forward all calls",
        "Dial with the number, or alone and enter it.",
        18,
        True,
    ),
    FeatureCodeDef("cf_off", "*73", "Forward all calls off", "", 18),
    FeatureCodeDef(
        "cfb_on", "*90", "Forward on busy", "Dial with the number, or alone and enter it.", 18, True
    ),
    FeatureCodeDef("cfb_off", "*91", "Forward on busy off", "", 18),
    FeatureCodeDef(
        "cfu_on",
        "*52",
        "Forward on no answer",
        "Dial with the number, or alone and enter it.",
        18,
        True,
    ),
    FeatureCodeDef("cfu_off", "*53", "Forward on no answer off", "", 18),
    FeatureCodeDef("fmfm_toggle", "*21", "Find me / follow me toggle", "", 18),
    FeatureCodeDef(
        "intercom",
        "*80",
        "Intercom",
        "Dialled with the extension: the phone answers on speaker.",
        18,
        True,
    ),
    FeatureCodeDef(
        "vm_direct",
        "*",
        "Direct to voicemail",
        "Followed by an extension (dialled, or as a transfer target): straight to its greeting.",
        18,
        True,
    ),
)
BY_KEY = {d.key: d for d in DEFAULTS}


class FeatureCodeError(ValueError):
    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key, self.message = key, message


def _overrides(db: Session) -> dict[str, dict[str, Any]]:
    row = db.get(SystemSetting, SETTINGS_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {k: v for k, v in value.items() if k in BY_KEY and isinstance(v, dict)}


def load(db: Session) -> list[dict[str, Any]]:
    """Every code with its current value, default and state."""
    over = _overrides(db)
    out = []
    for d in DEFAULTS:
        o = over.get(d.key, {})
        out.append(
            {
                "key": d.key,
                "label": d.label,
                "description": d.description,
                "code": str(o.get("code") or d.code),
                "default_code": d.code,
                "enabled": bool(o.get("enabled", True)),
                "takes_number": d.takes_number,
                "milestone": d.milestone,
            }
        )
    return out


def active(db: Session) -> dict[str, str]:
    """key -> code for the enabled codes (what the generator renders)."""
    return {c["key"]: c["code"] for c in load(db) if c["enabled"]}


def validate(codes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalise ``{key: {code, enabled}}``; raise FeatureCodeError on the first
    problem (unknown key, bad format, a fixed code, a duplicate)."""
    out: dict[str, dict[str, Any]] = {}
    for key, value in codes.items():
        if key not in BY_KEY:
            raise FeatureCodeError(key, "unknown feature code")
        if not isinstance(value, dict):
            raise FeatureCodeError(key, "expected {code, enabled}")
        code = str(value.get("code") or BY_KEY[key].code).strip()
        if not _CODE_RE.match(code):
            raise FeatureCodeError(
                key, "a code starts with * or # and has 1 to 7 characters (digits, * or #)"
            )
        if code in FIXED_CODES or code.startswith(FIXED_PREFIXES):
            raise FeatureCodeError(
                key, f"{code} is already used ({FIXED_CODES.get(code, 'directed pickup')})"
            )
        out[key] = {"code": code, "enabled": bool(value.get("enabled", True))}
    merged = {d.key: {"code": d.code, "enabled": True} for d in DEFAULTS}
    merged.update(out)
    seen: dict[str, str] = {}
    for key, v in merged.items():
        if not v["enabled"]:
            continue
        code = str(v["code"])
        if code in seen:
            raise FeatureCodeError(key, f"{code} is also used by {BY_KEY[seen[code]].label}")
        seen[code] = key
    return out


def save(db: Session, codes: dict[str, dict[str, Any]], by: Any) -> list[dict[str, Any]]:
    """Store the overrides (keys left at their default are dropped)."""
    value = {**_overrides(db), **validate(codes)}
    value = {k: v for k, v in value.items() if v["code"] != BY_KEY[k].code or not v["enabled"]}
    row = db.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    db.flush()
    return load(db)
