# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured facts for spec version 2 templates and the rendering of one
device (docs/DEVICE_PROVISIONING.md §4): lines from the device's extensions,
line keys with resolved labels, paging groups from the profile's zones, the
server's addresses and daylight-saving rules."""

from __future__ import annotations

import calendar
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import (
    CallFlow,
    CallQueue,
    Device,
    DeviceProfile,
    DeviceProfilePaging,
    Extension,
    FirmwareImage,
    Organization,
    PagingZone,
    ParkingLot,
    RingGroup,
    Site,
    TimeCondition,
    VoicemailBox,
)
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.provisioning import bootstrap
from veyra.provisioning.renderer import (
    MASK,
    RenderedFile,
    TemplateCatalog,
    model_slug,
    render,
)
from veyra.provisioning.spec import TemplateError
from veyra.provisioning.variables import VarsView, resolve_reference, scopes_of
from veyra.provisioning.variables import resolve as resolve_variables
from veyra.telephony import features
from veyra.telephony.settings import load_sip_settings
from veyra.telephony.snapshot import secret_purpose

PICKUP_PREFIX = "**"
GROUP_PICKUP_CODE = "*8"
VOICEMAIL_NUMBER = "*97"


class ProvisioningError(Exception):
    """The device cannot be rendered; ``code`` names why (no_profile,
    no_template, render_error, secret_unreadable)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ----------------------------------------------------------------- daylight saving


def _offset_seconds(dt: datetime) -> int:
    off = dt.utcoffset()
    return int(off.total_seconds()) if off else 0


def _rule(day: datetime, hour: int) -> dict[str, Any]:
    """A "nth weekday of the month" rule in Poly's terms: ``day_of_week`` 1 =
    Sunday … 7 = Saturday; ``date`` is the earliest day the nth weekday can
    fall on; ``last_in_month`` when it is the last such weekday."""
    nth = (day.day - 1) // 7 + 1
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    last = day.day + 7 > days_in_month
    return {
        "month": day.month,
        "week": 5 if last else nth,
        "day_of_week": day.isoweekday() % 7 + 1,
        "weekday": day.strftime("%A"),
        "date": 1 if last else 1 + 7 * (nth - 1),
        "last_in_month": last,
        "hour": hour,
    }


def dst_rules(tz_name: str, year: int | None = None) -> dict[str, Any]:
    """Daylight-saving rules of ``tz_name`` for ``year`` (this year by default)
    derived from the zone database: ``enabled``, ``standard_offset`` (seconds
    east of UTC), ``start`` and ``stop`` rules (§4.3). Unknown zones count as
    UTC without daylight saving."""
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return {"enabled": False, "standard_offset": 0, "start": None, "stop": None}
    year = year or datetime.now(zone).year
    first = datetime(year, 1, 1, 12, tzinfo=zone)
    transitions: list[tuple[datetime, int, int]] = []
    prev = first
    for n in range(1, 367):
        day = first + timedelta(days=n)
        if day.year != year:
            break
        if _offset_seconds(day) != _offset_seconds(prev):
            transitions.append((day, _offset_seconds(prev), _offset_seconds(day)))
        prev = day
    if not transitions:
        return {
            "enabled": False,
            "standard_offset": _offset_seconds(first),
            "start": None,
            "stop": None,
        }
    standard = min(_offset_seconds(first), *(t[2] for t in transitions))
    start = stop = None
    for day, before, after in transitions:
        # The change happens between the previous noon and this one: find the
        # local wall-clock hour (in the old offset) at which it occurred.
        hour = 2
        probe = (day - timedelta(days=1)).astimezone(ZoneInfo("UTC"))
        for h in range(1, 25):
            t = probe + timedelta(hours=h)
            if _offset_seconds(t.astimezone(zone)) == after:
                hour = (t + timedelta(seconds=before)).hour
                break
        rule = _rule(day, hour)
        if after > before:
            start = rule
        else:
            stop = rule
    return {
        "enabled": start is not None and stop is not None,
        "standard_offset": standard,
        "start": start,
        "stop": stop,
    }


# ----------------------------------------------------------------- facts


@dataclass
class DeviceContext:
    device: Device
    profile: DeviceProfile
    organization: Organization
    site: Site | None
    template_key: str


def _host(settings: Settings, host: str | None) -> str:
    """The configured public host wins over the request's Host header (which
    may be an address a technician typed into the phone)."""
    return (settings.public_host or host or socket.getfqdn() or "localhost").strip().split(":")[0]


def provisioning_url(settings: Settings, host: str | None = None, scheme: str = "https") -> str:
    return f"{scheme}://{_host(settings, host)}/provisioning/"


def _secret(key: InstallationKey | None, token: str | None, purpose: str, what: str) -> str | None:
    if not token:
        return None
    if key is None:
        raise ProvisioningError(
            "secret_unreadable", f"the installation key is not available ({what})"
        )
    try:
        return key.decrypt(token, purpose)
    except DecryptionError as e:
        raise ProvisioningError("secret_unreadable", f"{what} cannot be read: {e}") from e


def _line(
    index: int, ext: Extension, key: InstallationKey | None, boxes: set[uuid.UUID], mask: bool
) -> dict[str, Any]:
    secret = (
        MASK
        if mask
        else _secret(
            key,
            ext.sip_secret_ciphertext,
            secret_purpose(ext.id),
            f"the SIP secret of {ext.number}",
        )
    )
    return {
        "index": index,
        "extension_id": str(ext.id),
        "extension_number": ext.number,
        "sip_username": ext.endpoint_name,
        "sip_password": secret or "",
        "display_name": ext.display_name,
        "caller_id_name": ext.caller_id_name,
        "caller_id_number": ext.caller_id_number or ext.number,
        "label": ext.display_name,
        "voicemail": ext.id in boxes,
        "voicemail_number": VOICEMAIL_NUMBER,
        # Hotline (issue #168): dialled when the handset is lifted; a delay
        # in seconds makes it a warm line (0: at once).
        "hotline": ext.hotline_target or None,
        "hotline_delay": int(ext.hotline_delay or 0),
        # A fax machine on an ATA port: the ATA uses T.38 (PROVISIONING_BREADTH.md §4.4).
        "fax_t38": bool(ext.fax_t38),
    }


def merge_user_keys(
    raw: list[dict[str, Any]], user_keys: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Fill the ``user`` slots of a key list with the device's user keys
    (docs/USER_PORTAL.md §8); a slot the user left empty stays empty (the
    phone shows no key there), every other key is the administrator's."""
    out: list[dict[str, Any]] = []
    for i, k in enumerate(raw, 1):
        if str(k.get("type") or "") != "user":
            out.append(dict(k))
            continue
        chosen = (user_keys or {}).get(str(i))
        if isinstance(chosen, dict) and chosen.get("type") in ("blf", "speed_dial"):
            out.append(
                {
                    "type": chosen["type"],
                    "label": chosen.get("label"),
                    "value": str(chosen.get("value") or ""),
                }
            )
        else:
            out.append({"type": "user", "label": None, "value": ""})
    return out


def _keys(
    db: Session,
    org_id: uuid.UUID,
    raw: list[dict[str, Any]],
    zones: dict[str, PagingZone],
    variables: VarsView | None = None,
    own_number: str | None = None,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    # A key value may be "$name": the variable's value for this phone
    # (docs/PROVISIONING_BREADTH.md §2.3).
    raw = [{**k, "value": resolve_reference(k.get("value"), variables)} for k in raw]
    raw = _feature_keys(db, org_id, raw, own_number, warnings)
    numbers = {k.get("value") for k in raw if k.get("type") in ("blf", "speed_dial")}
    names: dict[str, str] = {}
    if numbers:
        for e in db.scalars(
            select(Extension).where(
                Extension.organization_id == org_id, Extension.number.in_(numbers)
            )
        ):
            names[e.number] = e.display_name
        for g in db.scalars(
            select(RingGroup).where(
                RingGroup.organization_id == org_id, RingGroup.number.in_(numbers)
            )
        ):
            names.setdefault(g.number, g.name)
    out: list[dict[str, Any]] = []
    blf = speed = 0
    for i, k in enumerate(raw, 1):
        kind = str(k.get("type") or "")
        value = str(k.get("value") or "")
        label = k.get("label") or None
        entry: dict[str, Any] = {"index": i, "type": kind, "value": value, "label": label}
        if k.get("feature"):
            entry["feature"] = k["feature"]
        if kind == "blf":
            blf += 1
            entry["blf_index"] = blf
            entry["label"] = label or names.get(value, value)
        elif kind == "speed_dial":
            speed += 1
            entry["speed_dial_index"] = speed
            entry["label"] = label or names.get(value, value)
        elif kind == "page":
            zone = zones.get(value)
            if zone is None:
                continue  # zone removed since the key was saved
            entry["group"] = zone.poly_group
            entry["multicast_address"] = zone.multicast_address
            entry["multicast_port"] = zone.multicast_port
            entry["label"] = label or zone.name
        elif kind == "line":
            entry["label"] = label or f"Line {value}"
        elif kind == "user":
            continue  # an open slot the user has not filled: no key rendered
        out.append(entry)
    return out


FEATURE_LABELS = {
    "voicemail": "Voicemail",
    "dnd": "DND",
    "presence": "Presence",
    "intercom": "Intercom",
    "park": "Park",
    "agent": "Queue log-in",
}


def _feature_keys(
    db: Session,
    org_id: uuid.UUID,
    raw: list[dict[str, Any]],
    own_number: str | None,
    warnings: list[str] | None,
) -> list[dict[str, Any]]:
    """The M21 key types (docs/PROVISIONING_BREADTH.md §3) as the BLF and
    speed-dial keys every template already renders; ``feature`` keeps the
    original type. A lamp is a hint the generator publishes: pressing a BLF
    key dials the watched number, so each watched number is also the code."""
    kinds = {str(k.get("type") or "") for k in raw}
    if not kinds & {"park", "voicemail", "transfer", "intercom", "dnd", "toggle", "presence"}:
        return raw
    codes = features.active(db)

    def note(text: str) -> None:
        if warnings is not None:
            warnings.append(text)

    out: list[dict[str, Any]] = []
    for k in raw:
        kind = str(k.get("type") or "")
        value = str(k.get("value") or "")
        label = k.get("label") or None
        if kind == "voicemail":
            out.append(
                {
                    **k,
                    "type": "speed_dial",
                    "value": VOICEMAIL_NUMBER,
                    "feature": kind,
                    "label": label or FEATURE_LABELS[kind],
                }
            )
        elif kind == "intercom":
            code = codes.get("intercom")
            if not code:
                note("an intercom key: the intercom code is turned off")
                continue
            out.append(
                {
                    **k,
                    "type": "speed_dial",
                    "value": f"{code}{value}",
                    "feature": kind,
                    "label": label or f"Intercom {value}",
                }
            )
        elif kind == "presence":
            # A BLF on the colleague's presence hint (issue #132).
            code = codes.get("presence_watch")
            if not code:
                note("a presence key: the colleague's presence code is off")
                continue
            out.append(
                {
                    **k,
                    "type": "blf",
                    "value": f"{code}{value}",
                    "feature": kind,
                    "label": label or f"{value}",
                }
            )
        elif kind == "dnd":
            code = codes.get("dnd_toggle")
            if not code or not own_number:
                note("a DND key: the DND toggle code is off or the phone has no extension")
                continue
            out.append(
                {
                    **k,
                    "type": "blf",
                    "value": f"{code}{own_number}",
                    "feature": kind,
                    "label": label or FEATURE_LABELS[kind],
                }
            )
        elif kind == "park":
            lot_slug, _, slot = value.partition(":")
            lot = db.scalar(
                select(ParkingLot).where(
                    ParkingLot.organization_id == org_id, ParkingLot.slug == lot_slug
                )
            )
            if lot is None:
                note(f"a park key: parking lot {lot_slug} no longer exists")
                continue
            if slot:
                out.append(
                    {
                        **k,
                        "type": "blf",
                        "value": slot,
                        "feature": kind,
                        "label": label or f"Park {slot}",
                    }
                )
            else:
                out.append(
                    {
                        **k,
                        "type": "speed_dial",
                        "value": lot.park_exten,
                        "feature": kind,
                        "label": label or f"Park ({lot.name})",
                    }
                )
        elif kind == "toggle":
            entry = _toggle_key(db, org_id, value, codes, own_number)
            if entry is None:
                note(f"a toggle key {value}: its target or code is gone")
                continue
            number, default_label = entry
            out.append(
                {
                    **k,
                    "type": "blf",
                    "value": number,
                    "feature": kind,
                    "label": label or default_label,
                }
            )
        elif kind == "transfer":
            # Kept as its own type: families with a transfer key render it
            # (feature "key_transfer"); render_device warns for the others.
            out.append({**k, "type": "transfer", "feature": kind, "label": label or "Transfer"})
        else:
            out.append(k)
    return out


def _toggle_key(
    db: Session, org_id: uuid.UUID, value: str, codes: dict[str, str], own_number: str | None
) -> tuple[str, str] | None:
    if value == "agent":
        login = codes.get("queue_login")
        return (f"{login}*{own_number}", FEATURE_LABELS["agent"]) if login and own_number else None
    if value.startswith("queue:"):
        login = codes.get("queue_login")
        queue = db.scalar(
            select(CallQueue).where(
                CallQueue.organization_id == org_id, CallQueue.slug == value[6:]
            )
        )
        if not login or queue is None or not own_number:
            return None
        return f"{login}{queue.number}*{own_number}", f"Log in {queue.name}"
    if value.startswith("flow:"):
        prefix = codes.get("callflow_toggle_prefix")
        flow = db.scalar(
            select(CallFlow).where(CallFlow.organization_id == org_id, CallFlow.slug == value[5:])
        )
        if not prefix or flow is None or flow.code_index is None:
            return None
        return f"{prefix}{flow.code_index}", flow.name
    if value.startswith("tc:"):
        prefix = codes.get("tc_override_prefix")
        try:
            tc = db.get(TimeCondition, uuid.UUID(value[3:]))
        except ValueError:
            tc = None
        if not prefix or tc is None or tc.organization_id != org_id or tc.code_index is None:
            return None
        return f"{prefix}{tc.code_index}", tc.name
    return None


def _paging(db: Session, profile: DeviceProfile) -> dict[str, Any]:
    rows = db.execute(
        select(DeviceProfilePaging, PagingZone)
        .join(PagingZone, PagingZone.id == DeviceProfilePaging.zone_id)
        .where(DeviceProfilePaging.profile_id == profile.id, PagingZone.is_enabled.is_(True))
        .order_by(PagingZone.poly_group)
    ).all()
    groups = []
    roles: dict[str, int | None] = {"default": None, "priority": None, "emergency": None}
    for m, z in rows:
        groups.append(
            {
                "number": z.poly_group,
                "label": z.name,
                "slug": z.slug,
                "subscribed": bool(m.subscribed),
                "transmit": bool(m.transmit),
                "kind": z.kind,
                "multicast_address": z.multicast_address,
                "multicast_port": z.multicast_port,
            }
        )
        if m.role in roles and roles[m.role] is None:
            roles[m.role] = z.poly_group
    for _m, z in rows:
        if z.kind == "emergency" and roles["emergency"] is None:
            roles["emergency"] = z.poly_group
        if z.kind == "priority" and roles["priority"] is None:
            roles["priority"] = z.poly_group
    first = rows[0][1] if rows else None
    return {
        "enabled": bool(rows),
        "address": first.poly_address if first else None,
        "port": first.poly_port if first else None,
        "codec": first.codec if first else "G.711Mu",
        "groups": groups,
        "default_group": roles["default"] or (groups[0]["number"] if groups else None),
        "priority_group": roles["priority"],
        "emergency_group": roles["emergency"],
    }


def resolve_device(catalog: TemplateCatalog, db: Session, device: Device) -> DeviceContext:
    """The profile, organization, site and concrete template of a device."""
    from veyra.api.v1.device_common import model_templates  # local import: API helper

    if device.profile_id is None:
        raise ProvisioningError("no_profile", "the device has no profile")
    profile = db.get(DeviceProfile, device.profile_id)
    if profile is None:
        raise ProvisioningError("no_profile", "the device's profile is missing")
    rec = catalog.records.get(profile.template_key)
    if rec is None:
        raise ProvisioningError("no_template", f"template {profile.template_key} is missing")
    if rec.manifest.template.abstract:
        found = model_templates(
            catalog, profile.template_key, device.model, device.organization_id
        )
        if not found:
            raise ProvisioningError(
                "no_template", f"no template under {profile.template_key} supports {device.model}"
            )
        template_key = found[0]
    elif device.model not in rec.manifest.template.models:
        raise ProvisioningError(
            "no_template", f"template {profile.template_key} does not support {device.model}"
        )
    else:
        template_key = profile.template_key
    org = db.get(Organization, device.organization_id)
    assert org is not None
    site = db.get(Site, device.site_id) if device.site_id else None
    return DeviceContext(device, profile, org, site, template_key)


def build_facts(
    db: Session,
    settings: Settings,
    ctx: DeviceContext,
    *,
    key: InstallationKey | None,
    host: str | None = None,
    mask_secrets: bool = False,
    scheme: str = "https",
    values: dict[str, Any] | None = None,
    variables: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    device, profile, org = ctx.device, ctx.profile, ctx.organization
    values = values or {}
    vars_view = VarsView(variables or {})
    ext_ids = [device.primary_extension_id] if device.primary_extension_id else []
    for line in device.lines:
        try:
            ext_ids.append(uuid.UUID(str(line.get("extension_id"))))
        except (ValueError, AttributeError):
            continue
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ext_ids)))}
        if ext_ids
        else {}
    )
    boxes = (
        {
            i
            for i in db.scalars(
                select(VoicemailBox.extension_id).where(
                    VoicemailBox.extension_id.in_(ext_ids), VoicemailBox.is_enabled.is_(True)
                )
            )
            if i is not None
        }
        if ext_ids
        else set()
    )
    lines: list[dict[str, Any]] = []
    for ext_id in ext_ids:
        ext = exts.get(ext_id)
        if ext is None or not ext.is_enabled:
            continue
        lines.append(_line(len(lines) + 1, ext, key, boxes, mask_secrets))
    zones = {
        z.slug: z
        for z in db.scalars(select(PagingZone).where(PagingZone.organization_id == org.id))
    }
    raw_keys = device.keys if device.keys is not None else profile.keys
    own_number = lines[0]["extension_number"] if lines else None
    keys = _keys(
        db,
        org.id,
        merge_user_keys(list(raw_keys or []), device.user_keys),
        zones,
        vars_view,
        own_number,
        warnings,
    )
    paging = _paging(db, profile)
    sip = load_sip_settings(db)
    transport = str(values.get("sip_transport") or "UDPOnly")
    sip_port = sip.tls_port if transport == "TLS" and sip.tls_enabled else sip.udp_port
    sip_host = str(
        values.get("sip_server") or sip.external_signaling_address or _host(settings, host)
    )
    tz = (ctx.site.timezone if ctx.site and ctx.site.timezone else None) or org.timezone or "UTC"
    tz = str(values.get("timezone") or tz)
    fw_id = device.firmware_image_id or profile.firmware_image_id
    fw = db.get(FirmwareImage, fw_id) if fw_id else None
    base = f"{scheme}://{_host(settings, host)}"
    credential = (
        MASK
        if mask_secrets
        else _secret(
            key,
            device.provisioning_secret_ciphertext,
            f"device.provisioning_secret:{device.id}",
            "the device credential",
        )
    )
    return {
        "device": {
            "mac": device.mac_address,
            "mac_upper": device.mac_address.upper(),
            "model": device.model,
            "model_slug": model_slug(device.model),
            "manufacturer": device.manufacturer,
            "label": device.label,
            "site_name": ctx.site.name if ctx.site else None,
            "site_slug": ctx.site.slug if ctx.site else None,
            "credential_user": f"dev-{device.mac_address}" if credential else None,
            "credential_password": credential,
        },
        "organization": {"name": org.name, "slug": org.slug},
        "lines": lines,
        "keys": keys,
        "paging": paging,
        "server": {
            "sip_host": sip_host,
            "sip_port": sip_port,
            "transport": transport,
            "provisioning_url": f"{base}/provisioning/",
            "directory_url": f"{base}/provisioning/directory/",
            # For devices that take the server and the path separately (Algo).
            "host": _host(settings, host),
            "provisioning_path": "provisioning",
            "provisioning_server_type": "HTTPS" if scheme == "https" else "HTTP",
            "ntp_server": str(values.get("ntp_server") or "pool.ntp.org"),
            "timezone": tz,
            "dst": dst_rules(tz),
            "pickup_prefix": PICKUP_PREFIX,
            "group_pickup_code": GROUP_PICKUP_CODE,
            "voicemail_number": VOICEMAIL_NUMBER,
            # Enabled feature codes, key → code (issue #130): templates
            # write {{ server.feature_codes.dnd_toggle }} and the like.
            "feature_codes": features.active(db),
            "firmware_url": f"{base}/provisioning/firmware/{fw.id}/{fw.filename}" if fw else None,
            "firmware_version": fw.version if fw else None,
            # The Veyra CA (PEM), for phones that install a trusted CA from
            # their configuration (Grandstream, issue #36).
            "ca_certificate": bootstrap.ca_certificate(settings.config_dir),
        },
        "features": {
            "voicemail": bool(lines) and bool(lines[0]["voicemail"]),
            "blf": any(k["type"] == "blf" for k in keys),
            "paging": paging["enabled"],
        },
        "vars": vars_view,
    }


def render_device(
    db: Session,
    settings: Settings,
    catalog: TemplateCatalog,
    device: Device,
    *,
    key: InstallationKey | None,
    host: str | None = None,
    mask_secrets: bool = False,
    scheme: str = "https",
    warnings: list[str] | None = None,
) -> list[RenderedFile]:
    """Every file the device's template produces, with the provisioning
    variables (docs/PROVISIONING_BREADTH.md §2: a defined variable with a
    template variable's name fills it unless the profile or device set it),
    the profile's values, the device's overrides and the facts (§4.1). A
    ``warnings`` list, when given, receives the variables templates and keys
    referenced but nobody defined. Raises ``ProvisioningError`` or
    ``TemplateError``."""
    ctx = resolve_device(catalog, db, device)
    resolved = catalog.resolve(ctx.template_key)
    variables = resolve_variables(db, **scopes_of(device, ctx.profile))
    values: dict[str, Any] = {
        **{k: v for k, v in variables.items() if k in resolved.variables},
        **dict(ctx.profile.values),
        **dict(device.values),
    }
    facts = build_facts(
        db,
        settings,
        ctx,
        key=key,
        host=host,
        mask_secrets=mask_secrets,
        scheme=scheme,
        values=values,
        variables=variables,
        warnings=warnings,
    )
    line1 = facts["lines"][0] if facts["lines"] else None
    core = {
        "extension_number": line1["extension_number"] if line1 else "0",
        "sip_username": line1["sip_username"] if line1 else "none",
        "sip_password": line1["sip_password"] if line1 else "none",
        "sip_server": facts["server"]["sip_host"],
        "sip_port": facts["server"]["sip_port"],
        "display_name": line1["display_name"] if line1 else (device.label or ""),
        "caller_id": line1["caller_id_name"] if line1 else None,
        "timezone": facts["server"]["timezone"],
        "ntp_server": facts["server"]["ntp_server"],
        "provisioning_url": facts["server"]["provisioning_url"],
    }
    for name, value in core.items():
        if values.get(name) in (None, ""):
            values[name] = value
    try:
        files = render(
            resolved,
            values,
            mac=device.mac_address,
            model=device.model,
            mask_secrets=mask_secrets,
            facts=facts,
        )
    except TemplateError as e:
        raise ProvisioningError("render_error", "; ".join(e.errors)) from e
    if warnings is not None:
        warnings.extend(f"variable {n} is not defined" for n in sorted(facts["vars"].missing))
        if "key_transfer" not in resolved.features and any(
            k["type"] == "transfer" for k in facts["keys"]
        ):
            warnings.append(
                "a transfer key: this template has no transfer key; the phone's softkey does it"
            )
    return files


def sample_facts(values: dict[str, Any], mac: str, model: str) -> dict[str, Any]:
    """Facts for a preview without a device: one line from the sample values,
    no keys, paging off, the server from the values (§7 template editor)."""
    tz = str(values.get("timezone") or "UTC")
    line = {
        "index": 1,
        "extension_id": None,
        "extension_number": str(values.get("extension_number") or "1001"),
        "sip_username": str(values.get("sip_username") or "example-1001"),
        "sip_password": str(values.get("sip_password") or MASK),
        "display_name": str(values.get("display_name") or "Sample Phone"),
        "caller_id_name": values.get("caller_id"),
        "caller_id_number": str(values.get("extension_number") or "1001"),
        "label": str(values.get("display_name") or "Sample Phone"),
        "voicemail": True,
        "voicemail_number": VOICEMAIL_NUMBER,
        "hotline": None,
        "hotline_delay": 0,
        "fax_t38": False,
    }
    host = str(values.get("sip_server") or "pbx.example.invalid")
    return {
        "device": {
            "mac": mac,
            "mac_upper": mac.upper(),
            "model": model,
            "model_slug": model_slug(model),
            "manufacturer": "",
            "label": "Sample device",
            "site_name": None,
            "site_slug": None,
            "credential_user": f"dev-{mac}",
            "credential_password": MASK,
        },
        "organization": {"name": "Sample organization", "slug": "sample"},
        "lines": [line],
        "keys": [],
        "paging": {
            "enabled": False,
            "address": None,
            "port": None,
            "codec": "G.711Mu",
            "groups": [],
            "default_group": None,
            "priority_group": None,
            "emergency_group": None,
        },
        "server": {
            "sip_host": host,
            "sip_port": int(values.get("sip_port") or 5060),
            "transport": str(values.get("sip_transport") or "UDPOnly"),
            "provisioning_url": str(
                values.get("provisioning_url") or f"https://{host}/provisioning/"
            ),
            "directory_url": f"https://{host}/provisioning/directory/",
            "host": host,
            "provisioning_path": "provisioning",
            "provisioning_server_type": "HTTPS",
            "ntp_server": str(values.get("ntp_server") or "pool.ntp.org"),
            "timezone": tz,
            "dst": dst_rules(tz),
            "pickup_prefix": PICKUP_PREFIX,
            "group_pickup_code": GROUP_PICKUP_CODE,
            "voicemail_number": VOICEMAIL_NUMBER,
            "feature_codes": dict(features.DEFAULT_CODES),
            "firmware_url": None,
            "firmware_version": None,
            "ca_certificate": None,
        },
        "features": {"voicemail": True, "blf": False, "paging": False},
        "vars": {},
    }


def master_filename(mac: str) -> str:
    return f"{mac}.cfg"
