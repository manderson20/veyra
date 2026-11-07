# SPDX-License-Identifier: AGPL-3.0-or-later
"""The isolation check's twin copies everything an organization owns
(docs/MULTI_TENANCY_MSP.md §3.1)."""

from msp_snapshot import rich_snapshot

from veyra.core import tenancy
from veyra.telephony import snapshot as snapshot_module
from veyra.telephony.asterisk import generator, isolation

CLASSIFIED = (
    set(snapshot_module.ORG_LISTS)
    | set(snapshot_module.ORG_NESTED)
    | set(snapshot_module.SHARED_KEYS)
    | {snapshot_module.ORGANIZATIONS_KEY}
)


def test_every_snapshot_key_is_classified(admin, app):
    """A new snapshot key must be listed as organization-owned or shared, or
    the isolation check would silently leave it out."""
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import load_installation_key

    with session_scope() as db:
        snap = snapshot_module.build_snapshot(db, load_installation_key(app.state.settings))
    assert set(snap) == CLASSIFIED, (
        "classify the new snapshot key in veyra/telephony/snapshot.py "
        f"(ORG_LISTS, ORG_NESTED or SHARED_KEYS): {sorted(set(snap) ^ CLASSIFIED)}"
    )


def test_rich_snapshot_covers_every_organization_list():
    snap = rich_snapshot()
    assert set(snap) == CLASSIFIED
    for key in snapshot_module.ORG_LISTS:
        if key in ("classes_of_service", "disa_lines", "fax_inboxes"):
            continue  # need encrypted data; covered by their own generator tests
        assert snap[key], f"rich_snapshot has no {key}"


def test_twin_copies_every_organization_item():
    snap = rich_snapshot()
    twin = tenancy._with_twin(snap)
    for key in snapshot_module.ORG_LISTS:
        src = [i for i in snap[key] if tenancy._owner(i) == "example"]
        copies = [i for i in twin[key] if tenancy._owner(i) == tenancy.CHECK_NAMESPACE]
        assert len(copies) == len(src), key
    for key, members in snapshot_module.ORG_NESTED.items():
        for m in members:
            src = [i for i in snap[key][m] if i["organization"] == "example"]
            copies = [i for i in twin[key][m] if i["organization"] == tenancy.CHECK_NAMESPACE]
            assert len(copies) == len(src), f"{key}.{m}"
    # References stay inside the twin; numbers and shared names do not collide.
    t_ext = next(e for e in twin["extensions"] if e["organization"] == "zzcheck")
    t_site = next(s for s in twin["sites"] if s["organization"] == "zzcheck")
    assert t_ext["endpoint_name"] == "zzcheck-1001" and t_ext["site"] == t_site["id"]
    assert t_site["id"] != snap["sites"][0]["id"]
    assert t_site["emergency_caller_id_number"] == "005735550199"
    t_route = next(r for r in twin["inbound_routes"] if r["organization_slug"] == "zzcheck")
    t_tc = next(c for c in twin["time_conditions"] if c["organization"] == "zzcheck")
    assert t_route["did"] == "005735550100" and t_route["time_condition"] == t_tc["key"]
    t_rec = next(r for r in twin["recording"] if r["organization"] == "zzcheck")
    assert t_rec["organization_id"] == t_route["organization"]
    assert t_rec["endpoints"] == ["zzcheck-1001"] and t_rec["routes"] == ["005735550100"]
    zones = twin["paging"]["zones"]
    assert len({z["port"] for z in zones}) == len(zones)
    out = {r["slug"] for r in twin["outbound_routes"]}
    assert {"org-only", "zzcheck-org-only", "local", "e911"} == out


def test_twin_of_the_rich_snapshot_generates_and_is_isolated():
    files = generator.generate(tenancy._with_twin(rich_snapshot()))
    assert isolation.verify(files) == []
    dp = next(f for f in files if f.path == "extensions.conf").content
    for ctx in ("veyra_zzcheck-internal", "veyra_zzcheck-rg-sales", "veyra_zzcheck-queue-support"):
        assert f"[{ctx}]" in dp


# ----------------------------------------------------------------- verifier


def _clean():
    files = {f.path: f for f in generator.generate(tenancy._with_twin(rich_snapshot()))}
    orgs = {"example": "", "zzcheck": "zzcheck"}
    assert isolation.verify(files.values(), organizations=orgs) == []
    return files, orgs


def _leak(files, path, find, add):
    from veyra.telephony.adapter import GeneratedFile

    text = files[path].content
    assert find in text, find
    out = dict(files)
    out[path] = GeneratedFile(path, text.replace(find, find + add, 1))
    return out.values()


TWIN_INTERNAL = "[veyra_zzcheck-internal]\n"


def _problems(files, path, find, add, orgs, **kw):
    return isolation.verify(_leak(files, path, find, add), organizations=orgs, **kw)


def test_verifier_catches_each_new_kind_of_leak():
    files, orgs = _clean()
    cases = [
        # A message copied into the other organization's box.
        ("extensions.conf", TWIN_INTERNAL, "exten => 77,1,VoiceMail(1001@veyra)\n", "voicemail"),
        # A conference with the other organization's bridge profile.
        (
            "extensions.conf",
            TWIN_INTERNAL,
            "exten => 78,1,ConfBridge(veyra_zzcheck-conf-board,veyra-conf-board-bridge)\n",
            "veyra-conf-board-bridge",
        ),
        # The other organization's parking lot.
        ("extensions.conf", TWIN_INTERNAL, "exten => 79,1,Goto(veyra-park-main,71,1)\n", "park"),
        # A hint with the other organization's phone.
        ("extensions.conf", TWIN_INTERNAL, "exten => 80,hint,PJSIP/example-1001\n", "example-1001"),
        # The other organization's Do Not Disturb lamp.
        (
            "extensions.conf",
            TWIN_INTERNAL,
            "exten => 81,hint,Custom:veyra-dnd-example-1001\n",
            "device state",
        ),
        # The other organization's call forward in the engine store.
        (
            "extensions.conf",
            TWIN_INTERNAL,
            "exten => 82,1,Set(X=${DB(veyra/ext/example/1001/cf_always)})\n",
            "engine store",
        ),
        # A parking lot whose timeout goes to the other organization.
        (
            "res_parking.conf",
            "[veyra_zzcheck-park-main]\n",
            "comebackcontext=veyra-park-main-timeout\n",
            "parking lot",
        ),
        # A conference profile with the other organization's hold music.
        (
            "confbridge.conf",
            "[veyra_zzcheck-conf-board-user]\n",
            "music_on_hold_class=veyra-jazz\n",
            "conference",
        ),
        # A queue with the other organization's hold music.
        ("queues.conf", "[veyra_zzcheck-support]\n", "musicclass=veyra-jazz\n", "queue"),
        # Hold music read from the other organization's folder.
        (
            "musiconhold.conf",
            "[veyra_zzcheck-jazz]\n",
            "directory=/var/lib/veyra/moh/jazz\n",
            "hold music",
        ),
        # A mailbox context nobody owns.
        ("voicemail.conf", "[zonemessages]\n", "[stray]\n1 => 1,x\n", "voicemail context"),
        # One DID in the shared context to one organization, on a trunk to the other.
        (
            "extensions.conf",
            "[veyra-from-trunk]\n",
            "exten => 5735550001,1,Goto(veyra-internal,1001,1)\n"
            "[veyra-from-trunk-carrier]\n"
            "exten => +15735550001,1,Goto(veyra_zzcheck-internal,1001,1)\n"
            "[veyra-from-trunk]\n",
            "across trunks",
        ),
        # A DID block reading the other organization's block list.
        (
            "extensions.conf",
            "[veyra-from-trunk]\n",
            "exten => 5550002,1,Goto(veyra-internal,1001,1)\n"
            " same => n,GotoIf(${DB_EXISTS(veyra/blacklist/zzcheck/x)}?b)\n",
            "several organizations",
        ),
    ]
    for path, find, add, expect in cases:
        found = _problems(files, path, find, add, orgs)
        assert any(expect in p for p in found), (expect, found)


def test_verifier_paging_ports_and_did_owners():
    import json

    from veyra.telephony.adapter import GeneratedFile

    files, orgs = _clean()
    doc = json.loads(files["paging.json"].content)
    doc["zones"][1]["port"] = doc["zones"][0]["port"]
    bad = dict(files)
    bad["paging.json"] = GeneratedFile("paging.json", json.dumps(doc))
    assert any("paging port" in p for p in isolation.verify(bad.values(), organizations=orgs))
    # The number inventory says who owns each DID.
    # ELINs are numbers of the inventory too.
    owners = {
        "5735550100": "",
        "005735550100": "zzcheck",
        "5735550199": "",
        "005735550199": "zzcheck",
    }
    assert isolation.verify(files.values(), organizations=orgs, dids=owners) == []
    wrong = {**owners, "5735550100": "zzcheck"}
    found = isolation.verify(files.values(), organizations=orgs, dids=wrong)
    assert any("does not own it" in p for p in found)


def test_slugs_with_hyphens_are_told_apart():
    assert isolation._owner_slug("acme-co-1001", {"acme", "acme-co"}) == "acme-co"
    assert isolation._owner_slug("acme-1001", {"acme", "acme-co"}) == "acme"
    assert isolation._owner_slug("other-1", {"acme"}) is None
