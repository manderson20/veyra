# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, Table, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from veyra.sdk import (
    ModuleContext,
    Page,
    PageParams,
    Principal,
    ProblemError,
    conflict,
    forbidden,
    get_db,
    not_found,
    page_params,
    utcnow,
)

from . import delivery as dl
from . import service
from .models import bell_messages, clocks, delivery, messages

READ, SEND, WRITE = "and_clocks.read", "and_clocks.send", "and_clocks.write"


def _blank(v: Any) -> Any:
    return None if v == "" else v


class ClockIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.\-:\[\]]+$")
    group_name: str = Field("", max_length=100)
    model: str = Field("", max_length=100)
    organization_id: uuid.UUID | None = None

    @field_validator("name", "address", "group_name", "model", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    send_to: str = Field("", max_length=100)
    color: str = "default"
    seconds: int = Field(60, ge=0, le=86400)
    priority: str = "normal"
    flashers: str = "off"
    send_at: str | None = Field(None, max_length=16)
    organization_id: uuid.UUID | None = None

    @field_validator("color", "priority", "flashers", "seconds", "send_at", mode="before")
    @classmethod
    def _defaults(cls, v: Any, info: Any) -> Any:
        if v in ("", None):
            return {"color": "default", "priority": "normal", "flashers": "off", "seconds": 60}.get(
                info.field_name
            )
        return v

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if v not in dl.COLORS:
            raise ValueError(f"must be one of {', '.join(dl.COLORS)}")
        return v

    @field_validator("priority")
    @classmethod
    def _prio(cls, v: str) -> str:
        if v not in dl.PRIORITIES:
            raise ValueError(f"must be one of {', '.join(dl.PRIORITIES)}")
        return v

    @field_validator("flashers")
    @classmethod
    def _flashers(cls, v: str) -> str:
        if v not in dl.FLASHERS:
            raise ValueError(f"must be one of {', '.join(dl.FLASHERS)}")
        return v


class BellMessageIn(BaseModel):
    bell_schedule: str = Field(min_length=1, max_length=100)
    text: str = Field("{summary}", max_length=200)
    send_to: str = Field("", max_length=100)
    color: str = "default"
    seconds: int = Field(60, ge=0, le=3600)
    organization_id: uuid.UUID | None = None

    @field_validator("text", "color", "seconds", mode="before")
    @classmethod
    def _defaults(cls, v: Any, info: Any) -> Any:
        if v in ("", None):
            return {"text": "{summary}", "color": "default", "seconds": 60}[info.field_name]
        return v

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if v not in dl.COLORS:
            raise ValueError(f"must be one of {', '.join(dl.COLORS)}")
        return v


class DeliveryIn(BaseModel):
    method: str = Field(pattern=r"^(GET|POST)$")
    scheme: str = "http"
    path: str = Field(min_length=1, max_length=500)
    content_type: str = "form"
    body: str = Field("", max_length=4000)
    auth: str = "none"
    username: str = Field("", max_length=100)
    password: str = Field("", max_length=200)
    organization_id: uuid.UUID | None = None

    @field_validator("scheme", "content_type", "auth", mode="before")
    @classmethod
    def _defaults(cls, v: Any, info: Any) -> Any:
        if v in ("", None):
            return {"scheme": "http", "content_type": "form", "auth": "none"}[info.field_name]
        return v

    @field_validator("scheme")
    @classmethod
    def _scheme(cls, v: str) -> str:
        if v not in ("http", "https"):
            raise ValueError("must be http or https")
        return v

    @field_validator("content_type")
    @classmethod
    def _ct(cls, v: str) -> str:
        if v not in dl.CONTENT_TYPES:
            raise ValueError(f"must be one of {', '.join(dl.CONTENT_TYPES)}")
        return v

    @field_validator("auth")
    @classmethod
    def _auth(cls, v: str) -> str:
        if v not in ("none", "basic", "digest"):
            raise ValueError("must be none, basic or digest")
        return v

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        v = v.strip()
        if "://" in v or not v.startswith("/") or any(c in v for c in " \r\n"):
            raise ValueError("must start with / and be the part of the address after the clock")
        return v


def _visible(table: Table, principal: Principal, permission: str = READ) -> Select[Any]:
    stmt = select(table)
    orgs = principal.organization_ids_with(permission)
    if orgs is not None:
        stmt = stmt.where(table.c.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _page(
    db: Session, stmt: Select[Any], order: Any, page: PageParams, fn: Any
) -> Page[dict[str, Any]]:
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(*order).limit(page.limit).offset(page.offset))
    return Page(items=[fn(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


def _ids(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    return {**d, "id": str(d["id"]), "organization_id": str(d["organization_id"])}


def build_router(ctx: ModuleContext) -> APIRouter:
    router = APIRouter()
    can_read = ctx.require(READ)
    can_send = ctx.require(SEND)
    can_write = ctx.require(WRITE)

    def org_for(
        db: Session, principal: Principal, requested: uuid.UUID | None, perm: str
    ) -> uuid.UUID:
        org = requested or ctx.default_organization(db, principal)
        if org is None:
            raise ProblemError(422, "Validation failed", "Choose an organization.")
        if not principal.has(perm, org):
            raise forbidden()
        return org

    def owned(
        db: Session, principal: Principal, table: Table, row_id: uuid.UUID, perm: str, what: str
    ) -> Any:
        row = db.execute(select(table).where(table.c.id == row_id)).first()
        if row is None or not principal.has(READ, row.organization_id):
            raise not_found(what)
        if not principal.has(perm, row.organization_id):
            raise forbidden()
        return row

    # -- clocks ---------------------------------------------------------------
    @router.get("/clocks", response_model=Page[dict[str, Any]])
    def list_clocks(
        q: str | None = None,
        page: PageParams = Depends(page_params),
        principal: Principal = Depends(can_read),
        db: Session = Depends(get_db),
    ) -> Page[dict[str, Any]]:
        stmt = _visible(clocks, principal)
        if q:
            like = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                func.lower(clocks.c.name).like(like)
                | func.lower(clocks.c.group_name).like(like)
                | clocks.c.address.like(like)
            )
        return _page(db, stmt, (clocks.c.group_name, clocks.c.name), page, _ids)

    @router.post("/clocks", status_code=201)
    def create_clock(
        body: ClockIn, principal: Principal = Depends(can_write), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        org = org_for(db, principal, body.organization_id, WRITE)
        exists = db.scalar(
            select(func.count())
            .select_from(clocks)
            .where(clocks.c.organization_id == org, func.lower(clocks.c.name) == body.name.lower())
        )
        if exists:
            raise conflict(f"A clock called {body.name} already exists.")
        row = {
            "id": uuid.uuid4(),
            "organization_id": org,
            "name": body.name,
            "address": body.address,
            "group_name": body.group_name,
            "model": body.model,
            "reachability": "unknown",
            "last_checked_at": None,
            "created_at": utcnow(),
        }
        db.execute(insert(clocks).values(**row))
        ctx.audit(
            db,
            principal,
            "clock.create",
            organization_id=org,
            target_type="clock",
            target_id=row["id"],
            details={"name": body.name, "address": body.address},
        )
        db.commit()
        return {**row, "id": str(row["id"]), "organization_id": str(org)}

    @router.delete("/clocks/{clock_id}")
    def delete_clock(
        clock_id: uuid.UUID,
        principal: Principal = Depends(can_write),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        row = owned(db, principal, clocks, clock_id, WRITE, "Clock")
        db.execute(delete(clocks).where(clocks.c.id == clock_id))
        ctx.audit(
            db,
            principal,
            "clock.delete",
            organization_id=row.organization_id,
            target_type="clock",
            target_id=clock_id,
            details={"name": row.name},
        )
        db.commit()
        return {"message": "Clock removed."}

    # -- messages -------------------------------------------------------------
    def message_out(r: Any) -> dict[str, Any]:
        d = _ids(r)
        d["send_to_label"] = service.target_label(d["send_to"])
        d["when"] = (d.get("sent_at") or d["send_at"]).isoformat()
        return d

    @router.get("/messages", response_model=Page[dict[str, Any]])
    def list_messages(
        status: str | None = None,
        page: PageParams = Depends(page_params),
        principal: Principal = Depends(can_read),
        db: Session = Depends(get_db),
    ) -> Page[dict[str, Any]]:
        stmt = _visible(messages, principal)
        if status:
            stmt = stmt.where(messages.c.status == status)
        # Scheduled first (soonest on top), then the log, newest first.
        order = (
            (messages.c.status != "scheduled"),
            func.coalesce(messages.c.sent_at, messages.c.send_at).desc(),
        )
        return _page(db, stmt, order, page, message_out)

    @router.post("/messages", status_code=201)
    def create_message(
        body: MessageIn, principal: Principal = Depends(can_send), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        org = org_for(db, principal, body.organization_id, SEND)
        now = utcnow()
        send_at = now
        if body.send_at:
            tz = ZoneInfo(ctx.organization_timezone(db, org))
            try:
                local = datetime.strptime(body.send_at.strip(), "%Y-%m-%d %H:%M")
            except ValueError as e:
                raise ProblemError(
                    422,
                    "Validation failed",
                    "Send at must look like 2026-10-20 08:15.",
                ) from e
            send_at = local.replace(tzinfo=tz)
            if send_at < now - timedelta(minutes=1):
                raise ProblemError(422, "Validation failed", "Send at is in the past.")
            if send_at > now + timedelta(days=366):
                raise ProblemError(422, "Validation failed", "Send at is more than a year away.")
        if not service.resolve(db, org, body.send_to):
            raise ProblemError(
                422,
                "Validation failed",
                "No clocks to send to: add clocks first."
                if body.send_to.strip().lower() in service.ALL
                else f"No clock or group is called {body.send_to.strip()!r}.",
            )
        immediate = send_at <= now + timedelta(seconds=30)
        message_id = uuid.uuid4()
        row = {
            "id": message_id,
            "organization_id": org,
            "text": body.text,
            "send_to": body.send_to.strip(),
            "color": body.color,
            "seconds": body.seconds,
            "priority": body.priority,
            "flashers": body.flashers,
            "send_at": send_at,
            "status": "sending" if immediate else "scheduled",
            "source": "user",
            "created_by": principal.label,
            "created_at": now,
        }
        db.execute(insert(messages).values(**row))
        ctx.audit(
            db,
            principal,
            "message.create",
            organization_id=org,
            target_type="clock_message",
            target_id=message_id,
            details={
                "send_to": row["send_to"],
                "send_at": send_at.isoformat(),
                "priority": body.priority,
            },
        )
        db.commit()
        result: dict[str, Any] = {"status": row["status"], "result": "", "outcomes": []}
        if immediate:
            result = service.deliver(ctx, message_id)
        return {
            **row,
            **result,
            "id": str(message_id),
            "organization_id": str(org),
            "send_to_label": service.target_label(row["send_to"]),
        }

    @router.delete("/messages/{message_id}")
    def delete_message(
        message_id: uuid.UUID,
        principal: Principal = Depends(can_send),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        row = owned(db, principal, messages, message_id, SEND, "Message")
        if row.status == "sending":
            raise conflict("The message is being sent right now.")
        db.execute(delete(messages).where(messages.c.id == message_id))
        ctx.audit(
            db,
            principal,
            "message.delete",
            organization_id=row.organization_id,
            target_type="clock_message",
            target_id=message_id,
            details={"status": row.status},
        )
        db.commit()
        return {
            "message": "Scheduled message cancelled."
            if row.status == "scheduled"
            else "Message removed from the log."
        }

    # -- bell messages --------------------------------------------------------
    def bell_out(r: Any) -> dict[str, Any]:
        return {**_ids(r), "send_to_label": service.target_label(r.send_to)}

    @router.get("/bell-messages", response_model=Page[dict[str, Any]])
    def list_bell_messages(
        page: PageParams = Depends(page_params),
        principal: Principal = Depends(can_read),
        db: Session = Depends(get_db),
    ) -> Page[dict[str, Any]]:
        stmt = _visible(bell_messages, principal)
        return _page(
            db, stmt, (bell_messages.c.bell_schedule, bell_messages.c.created_at), page, bell_out
        )

    @router.post("/bell-messages", status_code=201)
    def create_bell_message(
        body: BellMessageIn,
        principal: Principal = Depends(can_write),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        org = org_for(db, principal, body.organization_id, WRITE)
        row = {
            "id": uuid.uuid4(),
            "organization_id": org,
            "bell_schedule": body.bell_schedule.strip(),
            "text": body.text,
            "send_to": body.send_to.strip(),
            "color": body.color,
            "seconds": body.seconds,
            "created_at": utcnow(),
        }
        db.execute(insert(bell_messages).values(**row))
        ctx.audit(
            db,
            principal,
            "bell_message.create",
            organization_id=org,
            target_type="clock_bell_message",
            target_id=row["id"],
            details={"bell_schedule": row["bell_schedule"], "send_to": row["send_to"]},
        )
        db.commit()
        return {
            **row,
            "id": str(row["id"]),
            "organization_id": str(org),
            "send_to_label": service.target_label(row["send_to"]),
        }

    @router.delete("/bell-messages/{rule_id}")
    def delete_bell_message(
        rule_id: uuid.UUID, principal: Principal = Depends(can_write), db: Session = Depends(get_db)
    ) -> dict[str, str]:
        row = owned(db, principal, bell_messages, rule_id, WRITE, "Bell message")
        db.execute(delete(bell_messages).where(bell_messages.c.id == rule_id))
        ctx.audit(
            db,
            principal,
            "bell_message.delete",
            organization_id=row.organization_id,
            target_type="clock_bell_message",
            target_id=rule_id,
        )
        db.commit()
        return {"message": "Bell message removed."}

    # -- delivery setup -------------------------------------------------------
    def delivery_out(r: Any) -> dict[str, Any]:
        d = _ids(r)
        d.pop("password_ciphertext", None)
        d["has_password"] = bool(r.password_ciphertext)
        d["url_label"] = f"{r.scheme}://<clock>{r.path}"
        return d

    @router.get("/delivery", response_model=Page[dict[str, Any]])
    def list_delivery(
        page: PageParams = Depends(page_params),
        principal: Principal = Depends(can_write),
        db: Session = Depends(get_db),
    ) -> Page[dict[str, Any]]:
        stmt = _visible(delivery, principal, WRITE)
        return _page(db, stmt, (delivery.c.updated_at.desc(),), page, delivery_out)

    @router.post("/delivery", status_code=201)
    def save_delivery(
        body: DeliveryIn, principal: Principal = Depends(can_write), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        org = org_for(db, principal, body.organization_id, WRITE)
        current = db.execute(select(delivery).where(delivery.c.organization_id == org)).first()
        if body.password:
            ciphertext = ctx.encrypt(body.password)
        else:  # blank keeps the stored password
            ciphertext = current.password_ciphertext if current else ""
        values = {
            "method": body.method,
            "scheme": body.scheme,
            "path": body.path,
            "content_type": body.content_type if body.method == "POST" else "none",
            "body": body.body if body.method == "POST" else "",
            "auth": body.auth,
            "username": body.username,
            "password_ciphertext": ciphertext,
            "updated_by": principal.label,
            "updated_at": utcnow(),
        }
        stmt = pg_insert(delivery).values(id=uuid.uuid4(), organization_id=org, **values)
        db.execute(stmt.on_conflict_do_update(index_elements=["organization_id"], set_=values))
        ctx.audit(
            db,
            principal,
            "delivery.save",
            organization_id=org,
            target_type="clock_delivery",
            details={
                k: v for k, v in values.items() if k not in ("password_ciphertext", "updated_at")
            },
        )
        db.commit()
        row = db.execute(select(delivery).where(delivery.c.organization_id == org)).one()
        return delivery_out(row)

    @router.delete("/delivery/{delivery_id}")
    def delete_delivery(
        delivery_id: uuid.UUID,
        principal: Principal = Depends(can_write),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        row = owned(db, principal, delivery, delivery_id, WRITE, "Delivery setup")
        db.execute(delete(delivery).where(delivery.c.id == delivery_id))
        ctx.audit(
            db,
            principal,
            "delivery.delete",
            organization_id=row.organization_id,
            target_type="clock_delivery",
            target_id=delivery_id,
        )
        db.commit()
        return {"message": "Delivery setup removed; messages are no longer sent."}

    @router.post("/delivery/preview")
    def preview_delivery(
        body: MessageIn, principal: Principal = Depends(can_write), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        """The request one clock would receive (password shown as ****)."""
        org = org_for(db, principal, body.organization_id, WRITE)
        setup = service.load_delivery(ctx, db, org)
        if setup is None:
            raise not_found("Delivery setup")
        masked = dl.Delivery(**{**setup.__dict__, "password": "****"})
        method, url, content, headers = dl.build_request(
            "<clock>",
            dl.Message(body.text, body.color, body.seconds, body.priority, body.flashers),
            masked,
        )
        return {"method": method, "url": url, "headers": headers, "body": content.decode()}

    return router
