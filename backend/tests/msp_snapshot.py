# SPDX-License-Identifier: AGPL-3.0-or-later
"""A snapshot of one organization that uses every feature the generator
knows, for the isolation check's twin (docs/MULTI_TENANCY_MSP.md §3.1)."""

from __future__ import annotations

from typing import Any

from test_generator_callflow import _ann, _flow, _lot, _room, _tc
from test_generator_groups import _group, _member, _queue
from test_generator_routing import _route, _trunk
from test_generator_voicemail_ivr import _box, _ext, _menu

from veyra.telephony.features import DEFAULT_CODES
from veyra.telephony.settings import SipSettings

SITE = "6f1c2a52-7d7e-4c4e-9a43-1b8f5d2c0a11"
TC = "0b6b3c55-2f5e-4d8f-9e4c-3c1a7f2b9d22"


def rich_snapshot(org: str = "example") -> dict[str, Any]:
    exts = [
        _ext(
            "1001",
            org=org,
            pickup_groups=["front"],
            site=SITE,
            emergency_caller_id_number="5735550199",
            max_contacts=1,
        ),
        _ext("1002", org=org, pickup_groups=["front"], max_contacts=1),
    ]
    return {
        "snapshot_version": 11,
        "veyra_version": "test",
        "installation": {"name": "Test", "multi_tenancy_enabled": False},
        "sip": SipSettings().model_dump(mode="json"),
        "smtp": {"enabled": False, "from_address": "pbx@example.org", "from_name": "PBX"},
        "custom_dialplan": "",
        "feature_codes": dict(DEFAULT_CODES),
        "numbering": {"extension_length": 4},
        "organizations": [
            {"slug": org, "name": "Example", "timezone": "UTC", "namespace": "", "is_active": True}
        ],
        "extensions": exts,
        "shared_mailboxes": {},
        "voicemail_boxes": [_box("1001", organization=org), _box("1002", organization=org)],
        "ivr_menus": [_menu(organization=org), _menu("after-hours", organization=org, entries=[])],
        "ring_groups": [
            _group(organization=org, members=[_member("1001", org=org), _member("1002", org=org)])
        ],
        "queues": [_queue(organization=org, members=[_member("1001", org=org, penalty=0)])],
        "announcements": [_ann(organization=org)],
        "call_flows": [_flow(organization=org)],
        "caller_block_policies": [
            {"organization": org, "block_anonymous": True, "destination": {"type": "hangup"}}
        ],
        "parking_lots": [_lot(organization=org)],
        "conference_rooms": [_room(organization=org)],
        "classes_of_service": [],
        "disa_lines": [],
        "fax_inboxes": [],
        "hold_music": [
            {
                "slug": "jazz",
                "name": "Jazz",
                "organization": org,
                "random": False,
                "stream_url": None,
                "files": ["000-track"],
            }
        ],
        "time_conditions": [_tc(TC, organization=org)],
        "sites": [
            {
                "id": SITE,
                "slug": "main",
                "name": "Main",
                "organization": org,
                "emergency_caller_id_number": "5735550199",
                "callback_minutes": 30,
                "responder": "1002",
            }
        ],
        "trunks": [_trunk()],
        "outbound_routes": [
            _route(
                "e911", is_emergency=True, patterns=[{"prefix": "", "match": "911", "prepend": ""}]
            ),
            _route(),
            _route(
                "org-only",
                organization=org,
                patterns=[{"prefix": "8", "match": "NXXNXXXXXX", "prepend": "1"}],
            ),
        ],
        "numbers": [
            {"organization": org, "first": "5735550100", "last": "5735550199", "trunk": None}
        ],
        "inbound_routes": [
            {
                "did": "5735550100",
                "trunk": None,
                "destination": {"type": "queue", "queue": "support"},
                "after_hours": {"type": "voicemail", "number": "1001"},
                "time_condition": TC,
                "caller_id_prefix": None,
                "caller_rules": [],
                "organization": "11111111-2222-4333-8444-555555555555",
                "organization_slug": org,
            }
        ],
        "paging": {
            "defaults": {"delay_ms": 200, "ttl": 1},
            "zones": [
                {
                    "slug": "all",
                    "name": "All",
                    "organization": org,
                    "number": "3000",
                    "port": 40000,
                    "multicast_address": None,
                    "multicast_port": None,
                    "poly_address": None,
                    "poly_port": None,
                    "poly_group": None,
                    "kind": "phones",
                    "codec": "g722",
                    "allowed": "everyone",
                    "members": ["1001", "1002"],
                    "max_seconds": 60,
                }
            ],
            "pages": [],
        },
        "recording": [
            {
                "id": "22222222-3333-4444-8555-666666666666",
                "organization": org,
                "organization_id": "11111111-2222-4333-8444-555555555555",
                "inbound": True,
                "outbound": True,
                "internal": False,
                "all": False,
                "extensions": ["1001"],
                "endpoints": [f"{org}-1001"],
                "ring_groups": [],
                "queues": [],
                "routes": ["5735550100"],
                "announcement": None,
            }
        ],
    }
