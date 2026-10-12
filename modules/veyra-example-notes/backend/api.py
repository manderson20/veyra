# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from veyra.sdk import (
    ModuleContext,
    Page,
    PageParams,
    Principal,
    ProblemError,
    forbidden,
    get_db,
    not_found,
    page_params,
    utcnow,
)

from .models import notes


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field("", max_length=4000)
    organization_id: uuid.UUID | None = None


def build_router(ctx: ModuleContext) -> APIRouter:
    router = APIRouter()
    can_read = ctx.require("example_notes.read")
    can_write = ctx.require("example_notes.write")

    def visible(principal: Principal):  # type: ignore[no-untyped-def]
        stmt = select(notes)
        orgs = principal.organization_ids_with("example_notes.read")
        if orgs is not None:
            stmt = stmt.where(notes.c.organization_id.in_(orgs or {uuid.UUID(int=0)}))
        return stmt

    @router.get("/notes", response_model=Page[dict[str, Any]])
    def list_notes(
        page: PageParams = Depends(page_params),
        principal: Principal = Depends(can_read),
        db: Session = Depends(get_db),
    ) -> Page[dict[str, Any]]:
        stmt = visible(principal)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.execute(
            stmt.order_by(notes.c.created_at.desc()).limit(page.limit).offset(page.offset)
        ).mappings()
        items = [
            {**r, "id": str(r["id"]), "organization_id": str(r["organization_id"])} for r in rows
        ]
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.post("/notes", status_code=201)
    def create_note(
        body: NoteIn, principal: Principal = Depends(can_write), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        org_id = body.organization_id or ctx.default_organization(db, principal)
        if org_id is None:
            raise ProblemError(422, "Validation failed", "Choose an organization for this note.")
        if not principal.has("example_notes.write", org_id):
            raise forbidden()
        limit = int(ctx.get_config(db, org_id)["max_notes_per_organization"])
        count = (
            db.scalar(
                select(func.count()).select_from(notes).where(notes.c.organization_id == org_id)
            )
            or 0
        )
        if count >= limit:
            raise ProblemError(
                409, "Limit reached", f"This organization already has {limit} notes."
            )
        note_id = uuid.uuid4()
        row = {
            "id": note_id,
            "organization_id": org_id,
            "title": body.title,
            "body": body.body,
            "created_by": principal.label,
            "created_at": utcnow(),
        }
        db.execute(insert(notes).values(**row))
        ctx.audit(
            db,
            principal,
            "note.create",
            organization_id=org_id,
            target_type="note",
            target_id=note_id,
            details={"title": body.title},
        )
        db.commit()
        ctx.publish("example_notes.note_created", {"note_id": str(note_id)})
        return {**row, "id": str(note_id), "organization_id": str(org_id)}

    @router.delete("/notes/{note_id}")
    def delete_note(
        note_id: uuid.UUID, principal: Principal = Depends(can_write), db: Session = Depends(get_db)
    ) -> dict[str, str]:
        row = db.execute(select(notes).where(notes.c.id == note_id)).mappings().first()
        if row is None or not principal.has("example_notes.read", row["organization_id"]):
            raise not_found("Note")
        if not principal.has("example_notes.write", row["organization_id"]):
            raise forbidden()
        db.execute(delete(notes).where(notes.c.id == note_id))
        ctx.audit(
            db,
            principal,
            "note.delete",
            organization_id=row["organization_id"],
            target_type="note",
            target_id=note_id,
        )
        db.commit()
        return {"message": "Note deleted."}

    return router
