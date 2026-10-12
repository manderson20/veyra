"""Offset pagination shared by list endpoints."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")

MAX_LIMIT = 200


class PageParams(BaseModel):
    limit: int = 50
    offset: int = 0


def page_params(
    limit: int = Query(50, ge=1, le=MAX_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Items to skip"),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def paginate(db: Session, stmt: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(params.limit).offset(params.offset)))
    return rows, total
