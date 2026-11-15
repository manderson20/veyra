# SPDX-License-Identifier: AGPL-3.0-or-later
"""What each Veyra field can hold (docs/CONFIG_VERIFICATION.md §3.0). A
template fills a phone's settings from these fields; the precheck tries a
field's typical, shortest and longest values instead of every phone's own.
The shapes repeat the validators that guard the data when it is saved, and
``tests/test_config_precheck.py`` checks that the two agree."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from veyra.provisioning.spec import VariableDef

Kind = Literal["text", "digits", "int", "bool", "host", "url", "ip", "enum"]


@dataclass(frozen=True)
class Domain:
    kind: Kind
    description: str
    min_length: int = 0
    max_length: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    values: tuple[str, ...] = ()
    # The values the precheck tries: typical first. The typical values are
    # distinctive so the checker can tell which field filled a setting.
    typical: str = ""
    shortest: str | None = None
    longest: str | None = None

    def samples(self) -> dict[str, str]:
        out = {"typical": self.typical}
        if self.shortest is not None and self.shortest != self.typical:
            out["shortest"] = self.shortest
        if self.longest is not None and self.longest != self.typical:
            out["longest"] = self.longest
        return out

    def summary(self) -> str:
        if self.kind == "enum":
            return "one of " + ", ".join(self.values)
        if self.kind in ("int",) and (self.minimum is not None or self.maximum is not None):
            return f"a number from {self.minimum} to {self.maximum}"
        if self.max_length:
            return f"{self.description}, up to {self.max_length} characters"
        return self.description


def _text(desc: str, typical: str, max_length: int, min_length: int = 1, ch: str = "W") -> Domain:
    return Domain(
        "text",
        desc,
        min_length=min_length,
        max_length=max_length,
        typical=typical,
        shortest=ch * min_length if min_length else "",
        longest=(typical + ch * max_length)[:max_length],
    )


def _digits(desc: str, typical: str, max_length: int, min_length: int = 1) -> Domain:
    return Domain(
        "digits",
        desc,
        min_length=min_length,
        max_length=max_length,
        typical=typical,
        shortest="9" * min_length,
        longest="9" * max_length,
    )


# Extension fields: backend/veyra/api/v1/extensions.py (ExtensionIn).
EXTENSION_NUMBER_MAX = 32
DISPLAY_NAME_MAX = 200
CALLER_ID_NAME_MAX = 60
CALLER_ID_NUMBER_MAX = 32
HOTLINE_MAX = 20
# Endpoint names are "<organization slug>-<number>" in a column of 80.
SIP_USERNAME_MAX = 80

FACT_DOMAINS: dict[str, Domain] = {
    "line.extension_number": _digits("digits", "7391", EXTENSION_NUMBER_MAX),
    "line.sip_username": Domain(
        "text",
        "organization slug and number",
        min_length=3,
        max_length=SIP_USERNAME_MAX,
        typical="vqorg-7391",
        shortest="a-1",
        longest=("v" * (SIP_USERNAME_MAX - 6)) + "-99999",
    ),
    "line.sip_password": _text("secret", "Sq7pass0wordXq", 64, 16, "x"),
    "line.display_name": _text("text", "Ada Quorn", DISPLAY_NAME_MAX),
    "line.label": _text("text", "Qline label", DISPLAY_NAME_MAX),
    "line.caller_id_name": _text(
        "letters, digits and . ' & ( ) -", "Qcid Name", CALLER_ID_NAME_MAX
    ),
    "line.caller_id_number": _digits("digits (and a leading +)", "5550142", CALLER_ID_NUMBER_MAX),
    "line.hotline": _digits("digits, * and #", "5550199", HOTLINE_MAX),
    "line.voicemail_number": Domain("text", "feature code", typical="*97"),
    "device.label": _text("text", "Qroom 104", 200, 0),
    "device.credential_user": Domain(
        "text", "dev- and the MAC", min_length=16, max_length=16, typical="dev-0004f2aabbcc"
    ),
    "device.credential_password": _text("secret", "Dq7devicePassw0rdQ", 64, 16, "x"),
    "organization.name": _text("text", "Qorg District", 200),
    "server.sip_host": Domain(
        "host",
        "host name or address",
        min_length=1,
        max_length=253,
        typical="pbx.qhost.example",
        shortest="a",
        longest=".".join(["q" * 60] * 4)[:253],
    ),
    "server.ntp_server": Domain(
        "host", "host name or address", max_length=255, typical="ntp.qtime.example"
    ),
    "server.provisioning_url": Domain(
        "url", "https address ending in /", typical="https://pbx.qhost.example/provisioning/"
    ),
    "server.directory_url": Domain(
        "url",
        "https address ending in /",
        typical="https://pbx.qhost.example/provisioning/directory/",
    ),
    "key.value": _text("number or line", "7392", 64),
    "key.label": _text("text", "Qkey Label", DISPLAY_NAME_MAX, 0),
    "zone.label": _text("text", "Qzone Hall", 100),
    "zone.multicast_address": Domain("ip", "multicast address", typical="239.7.3.91"),
}


def variable_domain(var: VariableDef) -> Domain:
    """A template or provisioning variable's shape from its definition."""
    if var.type == "boolean":
        return Domain("bool", "yes or no", typical="true")
    if var.type == "integer":
        number = var.default if isinstance(var.default, int) else 0
        return Domain("int", "a whole number", typical=str(number))
    choices = _choices(var.pattern)
    if choices:
        typical = str(var.default) if var.default in choices else choices[0]
        return Domain("enum", "a choice", values=tuple(choices), typical=typical)
    text = "" if var.default is None else str(var.default)
    return Domain("text", var.description or "text", max_length=var.max_length, typical=text)


def _choices(pattern: str | None) -> list[str]:
    """``^(a|b|c)$`` as its alternatives; anything else is not a choice."""
    if not pattern:
        return []
    m = re.fullmatch(r"\^\(?((?:[A-Za-z0-9_.\-]+\|)+[A-Za-z0-9_.\-]+)\)?\$", pattern)
    return m.group(1).split("|") if m else []
