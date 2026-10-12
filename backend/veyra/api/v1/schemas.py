"""Shared API schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return check_timezone(v) if v is not None else v


class OrganizationOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    is_active: bool
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


class UserCreate(BaseModel):
    email: Email
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    home_organization_id: uuid.UUID | None = None


class UserPatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    is_active: bool | None = None
    password: str | None = Field(None, min_length=1, max_length=1024)


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
