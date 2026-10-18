# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared API schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

CALLER_ID_NUMBER_RE = re.compile(r"^\+?[0-9]{2,20}$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
# Deliberately permissive: internal domains such as "district.local" are common.
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63})*$")


def normalize_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 320 or not EMAIL_RE.match(v):
        raise ValueError("not a valid email address")
    return v


Email = Annotated[str, AfterValidator(normalize_email)]


def check_timezone(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError("unknown time zone") from e
    return v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- organizations
class OrganizationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=63)
    timezone: str = "UTC"

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("use lower-case letters, digits and dashes")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        return check_timezone(v)


class OrganizationPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    timezone: str | None = None
    is_active: bool | None = None
    # Default hold music set of the organization's phones; null = built-in.
    moh_class_id: uuid.UUID | None = None
    # The plain-HTTP bootstrap also carries the enrollment credential
    # (docs/FIREWALL_TRUST.md §6.4).
    bootstrap_includes_credential: bool | None = None
    # Numbers extensions may present as outbound caller ID besides the
    # organization's DIDs (docs/CALL_FEATURES.md §3.5); needs routing.write.
    caller_id_allow_list: list[str] | None = Field(None, max_length=100)
    # Intercom default for the organization's phones (docs/CALL_FEATURES.md §3.6).
    intercom_default: str | None = Field(None, pattern=r"^(allow|deny)$")

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return check_timezone(v) if v is not None else v

    @field_validator("caller_id_allow_list")
    @classmethod
    def _allow_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for raw in v:
            n = raw.strip()
            if not n:
                continue
            if not CALLER_ID_NUMBER_RE.match(n):
                raise ValueError(f"{n!r}: digits (and a leading +) only")
            if n not in out:
                out.append(n)
        return out


class OrganizationOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    is_active: bool
    moh_class_id: uuid.UUID | None = None
    bootstrap_includes_credential: bool = False
    caller_id_allow_list: list[str] = []
    intercom_default: str = "allow"
    # Prefix of the organization's engine names; empty: today's names
    # (docs/MULTI_TENANCY.md §2).
    engine_namespace: str = ""
    created_at: datetime


# ---------------------------------------------------------------- users
class UserOut(ORM):
    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    is_recovery_admin: bool
    auth_source: str
    home_organization_id: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime
    # Lockout ends at this time (None when not locked). The sign-in response
    # never reveals it; administrators see it here.
    locked_until: datetime | None = None
    password_changed_at: datetime | None = None
    must_change_password: bool = False
    # Whether a confirmed second factor exists (filled in by the handlers).
    mfa_enabled: bool = False


class UserCreate(BaseModel):
    email: Email
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    home_organization_id: uuid.UUID | None = None
    # The initial password is temporary by default (see UserPatch).
    require_password_change: bool = True


class UserPatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    is_active: bool | None = None
    password: str | None = Field(None, min_length=1, max_length=1024)
    # When an administrator sets a password it is temporary by default: the
    # user must choose their own at the next sign-in.
    require_password_change: bool = True


class UserSessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    is_current: bool = False


class PasswordResetLinkOut(BaseModel):
    """Shown once to the administrator; the token is not stored in clear."""

    token: str
    path: str
    expires_at: datetime


class RoleOut(ORM):
    id: uuid.UUID
    key: str
    name: str
    description: str
    is_system: bool


class RoleAssignmentIn(BaseModel):
    role_key: str
    scope_type: str = Field(pattern="^(platform|organization|site)$")
    organization_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None


class RoleAssignmentOut(BaseModel):
    id: uuid.UUID
    role_key: str
    role_name: str
    scope_type: str
    organization_id: uuid.UUID | None
    organization_name: str | None
    site_id: uuid.UUID | None


class MessageOut(BaseModel):
    message: str
