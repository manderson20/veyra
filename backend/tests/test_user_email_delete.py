# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changing a user's address and deleting a user (issue #352)."""

import email
import email.policy
import uuid

from conftest import ADMIN_PASSWORD, enable_multi_tenancy, login
from fastapi.testclient import TestClient
from sqlalchemy import select

from veyra.core import mail
from veyra.core.db import session_scope
from veyra.core.models import (
    AuditEvent,
    Extension,
    IdentityProvider,
    PasswordResetToken,
    User,
    UserIdentity,
    UserSession,
)
from veyra.core.models.base import utcnow

USERS = "/api/v1/users"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]["id"]


def _user(admin, org, email="sam@example.org"):
    r = admin.post(
        USERS,
        json={
            "email": email,
            "display_name": "Sam",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_change_email(admin, app):
    org = _org(admin)
    sam = _user(admin, org)
    _user(admin, org, "taken@example.org")
    url = f"{USERS}/{sam['id']}"
    assert admin.post(f"{url}/password-reset-link").status_code == 201
    sam_client = login(TestClient(app, base_url="http://veyra.test"), sam["email"], ADMIN_PASSWORD)
    assert sam_client.get("/api/v1/auth/sessions").status_code == 200
    r = admin.patch(url, json={"email": "TAKEN@example.org"})
    assert r.status_code == 409 and r.json()["code"] == "email_in_use"
    r = admin.patch(url, json={"email": "not an address"})
    assert r.status_code == 422
    r = admin.patch(url, json={"email": "New.Sam@example.org"})
    assert r.status_code == 200 and r.json()["email"] == "new.sam@example.org"
    # Signed out, the old reset link gone, the old address no longer signs in.
    assert sam_client.get("/api/v1/auth/sessions").status_code == 401
    with session_scope() as db:
        assert not db.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == uuid.UUID(sam["id"]))
        ).first()
        ev = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "user.update")
            .order_by(AuditEvent.id.desc())
        ).first()
        assert ev.details["email"] == {"from": "sam@example.org", "to": "new.sam@example.org"}
    fresh = TestClient(app, base_url="http://veyra.test")
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "sam@example.org", "password": ADMIN_PASSWORD}
        ).status_code
        == 401
    )
    login(fresh, "new.sam@example.org", ADMIN_PASSWORD)
    # Saving the same address again changes nothing.
    assert admin.patch(url, json={"email": "new.sam@example.org"}).status_code == 200


def test_email_of_a_provider_account_is_refused(admin):
    sam = _user(admin, _org(admin))
    with session_scope() as db:
        idp = db.scalars(select(IdentityProvider)).first()
        if idp is None:
            db.get(User, uuid.UUID(sam["id"])).auth_source = "oidc"
        else:
            db.add(
                UserIdentity(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(sam["id"]),
                    provider_id=idp.id,
                    subject="s",
                    email=sam["email"],
                    created_at=utcnow(),
                )
            )
    r = admin.patch(f"{USERS}/{sam['id']}", json={"email": "other@example.org"})
    assert r.status_code == 409 and r.json()["code"] == "email_from_provider"


def test_delete_user(admin):
    org = _org(admin)
    sam = _user(admin, org)
    url = f"{USERS}/{sam['id']}"
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1088", "display_name": "S", "user_id": sam["id"]},
    ).json()
    r = admin.delete(url)
    assert r.status_code == 409 and r.json()["code"] == "user_active"
    assert admin.patch(url, json={"is_active": False}).status_code == 200
    assert admin.delete(url).status_code == 204
    assert admin.get(url).status_code == 404
    with session_scope() as db:
        assert db.get(User, uuid.UUID(sam["id"])) is None
        # The phone stays, unassigned; the audit log remembers.
        phone = db.get(Extension, uuid.UUID(ext["id"]))
        assert phone is not None and phone.user_id is None
        assert not db.scalars(
            select(UserSession).where(UserSession.user_id == uuid.UUID(sam["id"]))
        ).first()
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "user.delete")).one()
        assert ev.details["email"] == sam["email"] and ev.details["extensions"] == ["1088"]


def test_delete_refusals(admin):
    me = admin.get(USERS).json()["items"]
    recovery = next(u for u in me if u["is_recovery_admin"])
    r = admin.delete(f"{USERS}/{recovery['id']}")
    assert r.status_code == 409 and r.json()["code"] == "self_deletion"


def test_other_organizations_guard(admin, app):
    enable_multi_tenancy()
    org_a = _org(admin)
    org_b = admin.post("/api/v1/organizations", json={"name": "Other", "slug": "other"}).json()[
        "id"
    ]
    boss = _user(admin, org_a, "boss@example.org")
    r = admin.post(
        f"{USERS}/{boss['id']}/roles",
        json={"role_key": "org_admin", "scope_type": "organization", "organization_id": org_a},
    )
    assert r.status_code == 201, r.text
    both = _user(admin, org_a, "both@example.org")
    r = admin.post(
        f"{USERS}/{both['id']}/roles",
        json={"role_key": "standard_user", "scope_type": "organization", "organization_id": org_b},
    )
    assert r.status_code == 201, r.text
    client = login(
        TestClient(app, base_url="http://veyra.test"), "boss@example.org", ADMIN_PASSWORD
    )
    url = f"{USERS}/{both['id']}"
    assert client.patch(url, json={"email": "x@example.org"}).status_code == 403
    assert admin.patch(url, json={"is_active": False}).status_code == 200
    assert client.delete(url).status_code == 403


def test_old_address_is_told(admin, app, monkeypatch):
    sam = _user(admin, _org(admin))
    smtp = mail.SmtpSettings(enabled=True, host="mail.example.org", from_address="pbx@example.org")
    monkeypatch.setattr(mail, "load_smtp_settings", lambda db: smtp)
    assert (
        admin.patch(f"{USERS}/{sam['id']}", json={"email": "moved@example.org"}).status_code == 200
    )
    queued = list(app.state.settings.mailqueue_dir.glob(f"*{mail.QUEUE_SUFFIX}"))
    msgs = [email.message_from_bytes(q.read_bytes(), policy=email.policy.default) for q in queued]
    msg = next(m for m in msgs if m["To"] == "sam@example.org")
    assert "moved@example.org" in msg.get_content()
