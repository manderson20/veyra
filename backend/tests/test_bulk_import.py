# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk CSV import and export (issue #41): dry run changes nothing, a real
run creates and updates in place through the API's own checks, a bad row
is reported and rolled back alone, and an export imports unchanged."""

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Extension, VoicemailBox


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _import(admin, kind, org, text, dry_run):
    r = admin.post(
        f"/api/v1/bulk/{kind}/import",
        params={"organization_id": org, "dry_run": str(dry_run).lower()},
        json={"csv": text},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_users_extensions_dry_run_and_update(admin):
    org = _org(admin)["id"]
    pg = admin.post("/api/v1/pickup-groups", json={"organization_id": org, "name": "Office"})
    assert pg.status_code == 201, pg.text
    users = "email,display_name,roles\npat@example.org,Pat Lee,standard_user\n"
    out = _import(admin, "users", org, users, dry_run=True)
    assert out["counts"]["create"] == 1 and out["rows"][0]["notes"]
    assert admin.get("/api/v1/users", params={"q": "pat@"}).json()["total"] == 0
    assert _import(admin, "users", org, users, dry_run=False)["counts"]["create"] == 1

    csv_text = (
        "number,display_name,user_email,voicemail,voicemail_attach_audio,pickup_groups\n"
        "2001,Front desk,pat@example.org,yes,yes,Office\n"
        "2002,Hallway,,,,\n"
        "2003,Bad user,nobody@example.org,,,\n"
        "2002,Twice,,,,\n"
        "abc,Bad number,,,,\n"
    )
    dry = _import(admin, "extensions", org, csv_text, dry_run=True)
    assert [r["action"] for r in dry["rows"]] == ["create", "create", "error", "error", "error"]
    assert "import the users first" in dry["rows"][2]["message"]
    assert "twice" in dry["rows"][3]["message"]
    with session_scope() as db:
        assert db.query(Extension).filter(Extension.number.in_(["2001", "2002"])).count() == 0
        assert db.query(AuditEvent).filter_by(action="extension.create").count() == 0

    real = _import(admin, "extensions", org, csv_text, dry_run=False)
    assert real["counts"] == {"create": 2, "update": 0, "unchanged": 0, "error": 3}
    with session_scope() as db:
        ext = db.query(Extension).filter_by(number="2001").one()
        assert ext.user_id is not None
        box = db.query(VoicemailBox).filter_by(extension_id=ext.id).one()
        assert box.email == "pat@example.org"
        assert db.query(AuditEvent).filter_by(action="extension.create").count() == 2
        assert db.query(AuditEvent).filter_by(action="bulk.import").count() == 2
    groups = admin.get("/api/v1/pickup-groups").json()["items"]
    assert len(groups[0]["members"]) == 1

    # The export is a valid import: nothing changes.
    exp = admin.get("/api/v1/bulk/extensions/export.csv", params={"organization_id": org})
    assert exp.status_code == 200 and exp.text.startswith("number,display_name,user_email")
    again = _import(admin, "extensions", org, exp.text, dry_run=False)
    assert again["counts"]["unchanged"] == 2 and again["counts"]["error"] == 0, again
    # Update in place; "-" clears; empty leaves.
    upd = _import(
        admin,
        "extensions",
        org,
        "number,display_name,location,user_email,pickup_groups\n2001,Reception,Lobby,-,-\n",
        dry_run=False,
    )
    assert upd["rows"][0]["action"] == "update", upd
    with session_scope() as db:
        ext = db.query(Extension).filter_by(number="2001").one()
        assert (ext.display_name, ext.location, ext.user_id) == ("Reception", "Lobby", None)
    assert admin.get("/api/v1/pickup-groups").json()["items"][0]["members"] == []

    # Unknown columns and a missing key column are refused before any row.
    r = admin.post(
        "/api/v1/bulk/extensions/import",
        params={"organization_id": org},
        json={"csv": "nombre,display_name\n1,x\n"},
    )
    assert r.status_code == 422 and r.json()["code"] == "bad_header"
    t = admin.get(
        "/api/v1/bulk/extensions/export.csv", params={"organization_id": org, "template": "true"}
    )
    assert t.text.strip().count("\n") == 0


def test_inbound_routes_and_shared_inboxes(admin):
    org = _org(admin)["id"]
    r = admin.post(
        "/api/v1/extensions", json={"organization_id": org, "number": "3001", "display_name": "A"}
    )
    assert r.status_code == 201, r.text
    inbox = _import(
        admin,
        "shared_inboxes",
        org,
        "number,name,members,email\n3900,Attendance,3001,att@example.org\n",
        dry_run=False,
    )
    assert inbox["counts"]["create"] == 1, inbox
    routes = (
        "did,destination,description\n"
        "+15550100,extension:3001,Main line\n"
        "+15550101,voicemail_box:3900,Attendance line\n"
        "+15550102,ivr:Nope,Bad\n"
    )
    out = _import(admin, "inbound_routes", org, routes, dry_run=False)
    assert [r["action"] for r in out["rows"]] == ["create", "create", "error"], out
    exp = admin.get("/api/v1/bulk/inbound_routes/export.csv", params={"organization_id": org})
    assert "extension:3001" in exp.text and "voicemail_box:3900" in exp.text
    assert _import(admin, "inbound_routes", org, exp.text, dry_run=True)["counts"]["unchanged"] == 2
    exp = admin.get("/api/v1/bulk/shared_inboxes/export.csv", params={"organization_id": org})
    assert "3900,Attendance,3001,att@example.org" in exp.text
