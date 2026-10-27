# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension templates (issue #172): settings applied on create, locked
fields refused on the extension and in My Phone, a preview and apply for
the template's extensions, and deletion leaving the settings."""

from fake_adapter import FakeAdapter

T = "/api/v1/extension-templates"
EXT = "/api/v1/extensions"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]["id"]


def test_template_applies_locks_and_reapplies(admin, app):
    app.state.telephony = FakeAdapter()
    o = _org(admin)
    cos = admin.post(
        "/api/v1/classes-of-service", json={"organization_id": o, "name": "Classroom"}
    ).json()
    r = admin.post(
        T,
        json={
            "organization_id": o,
            "name": "Classroom phones",
            "settings": {
                "class_of_service_id": cos["id"],
                "intercom": "allow",
                "ring_seconds": 25,
                "call_waiting_off": True,
            },
            "locked": ["class_of_service_id"],
        },
    )
    assert r.status_code == 201, r.text
    tpl = r.json()
    bad = admin.post(T, json={"organization_id": o, "name": "Bad", "settings": {"nope": 1}})
    assert bad.status_code == 422
    bad = admin.post(T, json={"organization_id": o, "name": "Bad", "locked": ["intercom"]})
    assert bad.status_code == 422

    # Created with the template: its settings, except what the request gives
    # (unless locked).
    r = admin.post(
        EXT,
        json={
            "organization_id": o,
            "number": "1101",
            "display_name": "Room 101",
            "template_id": tpl["id"],
            "intercom": "deny",
        },
    )
    assert r.status_code == 201, r.text
    ext = r.json()
    assert ext["class_of_service_id"] == cos["id"] and ext["intercom"] == "deny"
    assert ext["template_name"] == "Classroom phones" and ext["locked_fields"] == [
        "class_of_service_id"
    ]
    state = admin.get(f"{EXT}/{ext['id']}/state").json()
    assert state["ring_seconds"] == 25 and state["call_waiting_off"] is True

    # Locked: refused on the extension; unlocked fields change freely.
    r = admin.patch(f"{EXT}/{ext['id']}", json={"class_of_service_id": None})
    assert r.status_code == 409 and r.json()["code"] == "locked_by_template"
    assert admin.patch(f"{EXT}/{ext['id']}", json={"intercom": "default"}).status_code == 200

    # Preview, then apply: the extension comes back to the template.
    r = admin.post(f"{T}/{tpl['id']}/apply", json={"dry_run": True})
    assert r.status_code == 200, r.text
    (row,) = r.json()["extensions"]
    assert row["number"] == "1101" and row["changes"]["intercom"] == {
        "from": "default",
        "to": "allow",
    }
    r = admin.post(f"{T}/{tpl['id']}/apply", json={"dry_run": False})
    assert r.json()["needs_deployment"] is True
    assert admin.get(f"{EXT}/{ext['id']}").json()["intercom"] == "allow"
    assert admin.post(f"{T}/{tpl['id']}/apply", json={"dry_run": True}).json()["extensions"] == []

    # A locked state field is refused in the state API too.
    admin.patch(f"{T}/{tpl['id']}", json={"locked": ["class_of_service_id", "call_waiting_off"]})
    r = admin.put(f"{EXT}/{ext['id']}/state", json={"call_waiting_off": False})
    assert r.status_code == 409

    # Deleting the template: the extension keeps its settings.
    assert admin.delete(f"{T}/{tpl['id']}").status_code == 204
    ext = admin.get(f"{EXT}/{ext['id']}").json()
    assert ext["template_id"] is None and ext["class_of_service_id"] == cos["id"]
    assert admin.patch(f"{EXT}/{ext['id']}", json={"class_of_service_id": None}).status_code == 200


def test_following_a_template_later_applies_it_whole(admin):
    o = _org(admin)
    tpl = admin.post(
        T, json={"organization_id": o, "name": "Front office", "settings": {"max_registrations": 3}}
    ).json()
    ext = admin.post(
        EXT, json={"organization_id": o, "number": "1201", "display_name": "Front"}
    ).json()
    r = admin.patch(f"{EXT}/{ext['id']}", json={"template_id": tpl["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["max_registrations"] == 3 and r.json()["template_name"] == "Front office"
    listed = admin.get(T, params={"organization_id": o}).json()["items"]
    assert [t["extensions"] for t in listed] == [1]


def test_resending_the_current_value_of_a_locked_field_is_not_a_change(admin):
    o = _org(admin)
    tpl = admin.post(
        T,
        json={
            "organization_id": o,
            "name": "Desks",
            "settings": {"intercom": "allow"},
            "locked": ["intercom"],
        },
    ).json()
    ext = admin.post(
        EXT,
        json={
            "organization_id": o,
            "number": "1301",
            "display_name": "Desk",
            "template_id": tpl["id"],
        },
    ).json()
    # The template changes but is not applied yet: the form resends "allow".
    admin.patch(f"{T}/{tpl['id']}", json={"settings": {"intercom": "deny"}})
    r = admin.patch(f"{EXT}/{ext['id']}", json={"display_name": "Desk 1", "intercom": "allow"})
    assert r.status_code == 200, r.text
    assert admin.patch(f"{EXT}/{ext['id']}", json={"intercom": "default"}).status_code == 409


def test_forwarding_caller_id_and_voicemail_defaults(admin, app):
    app.state.telephony = FakeAdapter()
    o = _org(admin)
    admin.post(EXT, json={"organization_id": o, "number": "1190", "display_name": "Office"})
    bad = admin.post(
        T,
        json={
            "organization_id": o,
            "name": "Bad vm",
            "settings": {"vm_operator_extension": "9999"},
        },
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == (
        "settings.vm_operator_extension"
    )
    tpl = admin.post(
        T,
        json={
            "organization_id": o,
            "name": "Front office",
            "settings": {
                "cf_no_answer": "1190",
                "cf_unavailable": "(555) 010-2000",
                "outbound_caller_id_number": "+15550102000",
                "vm_keep_days": 60,
                "vm_operator_extension": "1190",
                "vm_attach_audio": False,
            },
            "locked": ["vm_keep_days", "cf_unavailable"],
        },
    ).json()
    assert tpl["settings"]["cf_unavailable"] == "5550102000"

    ext = admin.post(
        EXT,
        json={
            "organization_id": o,
            "number": "1191",
            "display_name": "Desk 1191",
            "template_id": tpl["id"],
        },
    ).json()
    assert ext["outbound_caller_id_number"] == "+15550102000"
    state = admin.get(f"{EXT}/{ext['id']}/state").json()
    assert state["cf_no_answer"] == "1190" and state["cf_unavailable"] == "5550102000"
    # A locked forward cannot change on the extension.
    r = admin.put(f"{EXT}/{ext['id']}/state", json={"cf_unavailable": "1190"})
    assert r.status_code == 409 and r.json()["code"] == "locked_by_template"

    # The box made later takes the template's voicemail options, except what
    # the request gives (unless locked).
    box = admin.post(
        "/api/v1/voicemail",
        json={"extension_id": ext["id"], "attach_audio": True, "keep_days": 10},
    ).json()
    assert box["attach_audio"] is True and box["keep_days"] == 60
    assert box["operator_extension"] == "1190"
    r = admin.patch(f"/api/v1/voicemail/{box['id']}", json={"keep_days": 30})
    assert r.status_code == 409 and r.json()["code"] == "locked_by_template"
    assert (
        admin.patch(f"/api/v1/voicemail/{box['id']}", json={"ring_seconds": 25}).status_code == 200
    )

    # Apply: the preview shows the box's own difference only.
    preview = admin.post(f"{T}/{tpl['id']}/apply", json={"dry_run": True}).json()
    assert preview["extensions"] == [
        {
            "extension_id": ext["id"],
            "number": "1191",
            "changes": {"vm_attach_audio": {"from": True, "to": False}},
        }
    ]
    assert preview["needs_deployment"]
