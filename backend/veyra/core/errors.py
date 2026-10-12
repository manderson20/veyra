"""Consistent error responses using RFC 9457 problem details."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("veyra.errors")

PROBLEM_JSON = "application/problem+json"


class ProblemError(Exception):
    """Raise from anywhere in request handling to return a problem response."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        code: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail
        self.code = code
        self.errors = errors
        self.headers = headers


def not_found(what: str = "Resource") -> ProblemError:
    return ProblemError(404, "Not found", f"{what} was not found.", code="not_found")


def forbidden(detail: str = "You do not have permission to perform this action.") -> ProblemError:
    return ProblemError(403, "Forbidden", detail, code="forbidden")


def conflict(detail: str, code: str = "conflict") -> ProblemError:
    return ProblemError(409, "Conflict", detail, code=code)


def problem_body(
    request: Request,
    status: int,
    title: str,
    detail: str | None,
    code: str | None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"https://veyra.dev/problems/{code or status}",
        "title": title,
        "status": status,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if detail:
        body["detail"] = detail
    if code:
        body["code"] = code
    if errors:
        body["errors"] = errors
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return JSONResponse(
            problem_body(request, exc.status, exc.title, exc.detail, exc.code, exc.errors),
            status_code=exc.status,
            media_type=PROBLEM_JSON,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = {404: "Not found", 405: "Method not allowed"}.get(exc.status_code, "Error")
        detail = exc.detail if isinstance(exc.detail, str) else None
        return JSONResponse(
            problem_body(request, exc.status_code, title, detail, None),
            status_code=exc.status_code,
            media_type=PROBLEM_JSON,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"),
                "message": err.get("msg", "Invalid value"),
                "type": err.get("type"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            problem_body(
                request,
                422,
                "Validation failed",
                "One or more fields are invalid.",
                "validation_failed",
                errors,
            ),
            status_code=422,
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "Unhandled error", extra={"request_id": getattr(request.state, "request_id", None)}
        )
        return JSONResponse(
            problem_body(
                request,
                500,
                "Internal server error",
                "An unexpected error occurred. "
                "The request ID can be used to find details in the server log.",
                "internal_error",
            ),
            status_code=500,
            media_type=PROBLEM_JSON,
        )
