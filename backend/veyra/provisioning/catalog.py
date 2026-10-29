# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a template can use, for the template editor's "Insert a Veyra
variable" panel (docs/DEVICE_PROVISIONING.md §4.1, §7). Every fact listed
here is checked against real facts by the tests, so the panel cannot offer
a name the renderer does not provide."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veyra.provisioning.spec import CORE_VARIABLES


@dataclass(frozen=True)
class Fact:
    # What the editor inserts, e.g. ``line.extension_number``.
    expr: str
    description: str
    sensitive: bool = False


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    description: str
    facts: tuple[Fact, ...]
    # Inside a loop: the loop the editor wraps a lone insert in, and the
    # name the facts use for the item (``line`` in ``line.extension_number``).
    loop: str | None = None
    item: str | None = None
    # Where the item comes from in the facts, for the tests (``lines``).
    source: str | None = None


@dataclass(frozen=True)
class Snippet:
    title: str
    description: str
    text: str


GROUPS: tuple[Group, ...] = (
    Group(
        "device",
        "Device",
        "The phone or adapter this file is for.",
        (
            Fact("device.mac", "MAC address, lower case without separators"),
            Fact("device.mac_upper", "MAC address, upper case"),
            Fact("device.model", "Model, as chosen on the device"),
            Fact("device.model_slug", "Model in lower case with dashes"),
            Fact("device.manufacturer", "Manufacturer"),
            Fact("device.label", "The device's label (may be empty)"),
            Fact("device.site_name", "Site name (may be empty)"),
            Fact("device.site_slug", "Site slug (may be empty)"),
            Fact("device.credential_user", "User name the device signs in with to fetch files"),
            Fact("device.credential_password", "The device's own password", sensitive=True),
        ),
    ),
    Group(
        "organization",
        "Organization",
        "The organization the device belongs to.",
        (
            Fact("organization.name", "Name"),
            Fact("organization.slug", "Slug"),
        ),
    ),
    Group(
        "lines",
        "Lines",
        "The device's registrations in order: line 1 is the primary extension.",
        (
            Fact("line.index", "Position, 1 for the first line"),
            Fact("line.extension_number", "Extension number"),
            Fact("line.sip_username", "SIP user name (the endpoint)"),
            Fact("line.sip_password", "SIP password", sensitive=True),
            Fact("line.display_name", "The extension's name"),
            Fact("line.label", "Label for the line key"),
            Fact("line.caller_id_name", "Caller ID name (may be empty)"),
            Fact("line.caller_id_number", "Caller ID number"),
            Fact("line.voicemail", "True when the extension has a mailbox"),
            Fact("line.voicemail_number", "Number that reaches voicemail (*97)"),
            Fact(
                "line.hotline", "Hotline number dialled when the handset is lifted (may be empty)"
            ),
            Fact("line.hotline_delay", "Warm-line delay in seconds (0: at once)"),
            Fact("line.fax_t38", "True when the extension is a fax machine (T.38)"),
        ),
        loop="{% for line in lines %}\n{}\n{% endfor %}",
        item="line",
        source="lines",
    ),
    Group(
        "keys",
        "Keys",
        "The profile's (or device's) programmable keys in order.",
        (
            Fact("key.index", "Position, 1 for the first key"),
            Fact("key.type", "line, blf, speed_dial, page, park, voicemail, transfer…"),
            Fact("key.value", "Number, line index or zone, by type"),
            Fact("key.label", "Label shown on the phone"),
        ),
        loop="{% for key in keys %}\n{}\n{% endfor %}",
        item="key",
        source="keys",
    ),
    Group(
        "paging",
        "Paging",
        "Multicast paging zones from the device's profile.",
        (
            Fact("paging.enabled", "True when the profile has paging zones"),
            Fact("paging.codec", "G.711Mu or G.722"),
            Fact("paging.address", "Poly group paging address"),
            Fact("paging.port", "Poly group paging port"),
            Fact("paging.default_group", "Poly group the phone pages by default"),
            Fact("paging.priority_group", "Poly priority group (may be empty)"),
            Fact("paging.emergency_group", "Poly emergency group (may be empty)"),
        ),
    ),
    Group(
        "paging_groups",
        "Paging zones",
        "Each paging zone of the profile.",
        (
            Fact("zone.label", "Zone name"),
            Fact("zone.slug", "Zone slug"),
            Fact("zone.number", "Poly group number"),
            Fact("zone.multicast_address", "Multicast address the speakers listen on"),
            Fact("zone.multicast_port", "Multicast port"),
            Fact("zone.subscribed", "True when the device listens to this zone"),
            Fact("zone.transmit", "True when the device may page this zone"),
            Fact("zone.kind", "normal, priority or emergency"),
        ),
        loop="{% for zone in paging.groups %}\n{}\n{% endfor %}",
        item="zone",
        source="paging.groups",
    ),
    Group(
        "server",
        "Server",
        "This Veyra server, as the device should reach it.",
        (
            Fact("server.sip_host", "SIP server host or address"),
            Fact("server.sip_port", "SIP port for the profile's transport"),
            Fact("server.transport", "UDPOnly, TCPOnly, TLS or DNSnaptr"),
            Fact("server.host", "Web host name"),
            Fact("server.provisioning_url", "Provisioning address, ending in /"),
            Fact("server.provisioning_path", "Provisioning path without the host"),
            Fact("server.provisioning_server_type", "HTTPS or HTTP"),
            Fact("server.directory_url", "Phone directory address, ending in /"),
            Fact("server.ntp_server", "Time server"),
            Fact("server.timezone", "IANA time zone, e.g. America/Chicago"),
            Fact("server.dst.enabled", "True when the zone has daylight saving"),
            Fact("server.dst.standard_offset", "Standard offset from UTC in seconds"),
            Fact("server.dst.start.month", "Daylight saving starts: month"),
            Fact("server.dst.start.week", "Daylight saving starts: week of the month (5 = last)"),
            Fact("server.dst.start.day_of_week", "Daylight saving starts: weekday (1 = Sunday)"),
            Fact("server.dst.start.hour", "Daylight saving starts: hour"),
            Fact("server.dst.stop.month", "Daylight saving ends: month"),
            Fact("server.dst.stop.week", "Daylight saving ends: week of the month (5 = last)"),
            Fact("server.dst.stop.day_of_week", "Daylight saving ends: weekday (1 = Sunday)"),
            Fact("server.dst.stop.hour", "Daylight saving ends: hour"),
            Fact("server.voicemail_number", "Number that reaches voicemail (*97)"),
            Fact("server.pickup_prefix", "Directed pickup prefix (**)"),
            Fact("server.group_pickup_code", "Group pickup code"),
            Fact("server.feature_codes.dnd_toggle", "A feature code by key (here: DND toggle)"),
            Fact("server.firmware_url", "Firmware image address (empty when none is assigned)"),
            Fact("server.firmware_version", "Firmware version (empty when none is assigned)"),
            Fact("server.ca_certificate", "The Veyra CA certificate (PEM)"),
        ),
    ),
    Group(
        "features",
        "Features",
        "What the device's extensions and profile use.",
        (
            Fact("features.voicemail", "True when line 1 has a mailbox"),
            Fact("features.blf", "True when any key is a BLF"),
            Fact("features.paging", "True when the profile has paging zones"),
        ),
    ),
)

SNIPPETS: tuple[Snippet, ...] = (
    Snippet(
        "Every line",
        "Repeat a block for each registration",
        "{% for line in lines %}\n{{ line.extension_number }}\n{% endfor %}",
    ),
    Snippet(
        "Every key of a type",
        "Only the BLF keys, numbered from 1",
        '{% for key in keys if key.type == "blf" %}\n'
        "{{ loop.index }}: {{ key.value }}\n{% endfor %}",
    ),
    Snippet(
        "Subscribed paging zones",
        "The zones the device listens to",
        "{% for zone in paging.groups if zone.subscribed %}\n"
        "{{ zone.multicast_address }}:{{ zone.multicast_port }}\n{% endfor %}",
    ),
    Snippet(
        "Only when set",
        "Write a setting only when the value is not empty",
        "{% if vlan_id %}\nvlan={{ vlan_id }}\n{% endif %}",
    ),
    Snippet(
        "Yes/no as 1/0",
        "A yes/no variable written as 1 or 0: replace my_switch with one of this template's",
        "{{ my_switch | bool01 }}",
    ),
    Snippet(
        "Override a block",
        "In a template under a parent: replace one of the parent's blocks",
        "{% block model_settings %}\n{% endblock %}",
    ),
)


def lookup(facts: dict[str, Any], path: str) -> Any:
    """The value at ``a.b.c`` in the facts; KeyError when a step is missing."""
    value: Any = facts
    for part in path.split("."):
        value = value[part]
    return value


def payload() -> dict[str, Any]:
    return {
        "groups": [
            {
                "key": g.key,
                "title": g.title,
                "description": g.description,
                "loop": g.loop,
                "facts": [
                    {"expr": f.expr, "description": f.description, "sensitive": f.sensitive}
                    for f in g.facts
                ],
            }
            for g in GROUPS
        ],
        "snippets": [
            {"title": s.title, "description": s.description, "text": s.text} for s in SNIPPETS
        ],
        "core_variables": [v.name for v in CORE_VARIABLES],
    }
