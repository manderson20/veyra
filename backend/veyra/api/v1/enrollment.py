# SPDX-License-Identifier: AGPL-3.0-or-later
"""The organization enrollment credential phones use for their first
provisioning fetch (docs/DEVICE_PROVISIONING.md §3.2)."""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import forbidden, not_found
from veyra.core.models import Organization
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/organizations", tags=["devices"])

READ = "devices.read"
WRITE = "devices.write"
SECRET_ALPHABET = string.ascii_letters + string.digits
SECRET_LENGTH = 24


def enrollment_purpose(organization_id: uuid.UUID) -> str:
    return f"organization.provisioning_secret:{organization_id}"


def device_purpose(device_id: uuid.UUID) -> str:
    return f"device.provisioning_secret:{device_id}"


def new_secret() -> str:
    return "".join(secrets.choice(SECRET_ALPHABET) for _ in range(SECRET_LENGTH))


def enrollment_user(org: Organization) -> str:
    return f"veyra-{org.slug}"[:63]


def provisioning_url(request: Request) -> str:
    settings = request.app.state.settings
    host = getattr(settings, "public_host", None) or request.headers.get("host") or "localhost"
    return f"https://{host}/provisioning/"


class CredentialOut(BaseModel):
    organization_id: uuid.UUID
    username: str | None
    url: str
    http_enabled: bool
    # What plain HTTP serves: the trust bootstrap only, or every file.
    http_mode: str = "bootstrap"
    rotated_at: datetime | None


class RotatedOut(CredentialOut):
    password: str


def _org(db: Session, principal: Principal, organization_id: uuid.UUID, perm: str) -> Organization:
    if not principal.has(perm, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    return org


def _out(request: Request, org: Organization) -> CredentialOut:
    settings = request.app.state.settings
    return CredentialOut(
        organization_id=org.id,
        username=org.provisioning_user,
        url=provisioning_url(request),
        http_enabled=bool(getattr(settings, "provisioning_http", False)),
        http_mode=getattr(settings, "provisioning_http_mode", "bootstrap"),
        rotated_at=org.provisioning_secret_changed_at,
    )


def rotate(org: Organization, key: InstallationKey) -> str:
    secret = new_secret()
    org.provisioning_user = enrollment_user(org)
    org.provisioning_secret_ciphertext = key.encrypt(secret, enrollment_purpose(org.id))
    org.provisioning_secret_changed_at = utcnow()
    return secret


@router.get(
    "/{organization_id}/provisioning-credential",
    response_model=CredentialOut,
    summary="Enrollment credential of an organization (no secret)",
)
def get_credential(
    organization_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> CredentialOut:
    return _out(request, _org(db, principal, organization_id, READ))


@router.post(
    "/{organization_id}/provisioning-credential/rotate",
    response_model=RotatedOut,
    summary="Create or rotate the enrollment credential (the password is shown once)",
)
def rotate_credential(
    organization_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RotatedOut:
    org = _org(db, principal, organization_id, WRITE)
    secret = rotate(org, installation_key(request))
    audit.record(
        db,
        action="provisioning_credential.rotate",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"username": org.provisioning_user},
    )
    db.commit()
    return RotatedOut(**_out(request, org).model_dump(), password=secret)
