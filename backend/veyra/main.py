"""ASGI application factory.

Run in development with:
    uvicorn veyra.main:create_app --factory --reload
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from veyra.api.v1 import api_router
from veyra.core import bootstrap
from veyra.core.config import Settings, get_settings
from veyra.core.db import dispose_engine, init_engine, session_scope
from veyra.core.errors import install_error_handlers
from veyra.core.events import bus
from veyra.core.signing import Keyring
from veyra.modules.manager import ModuleManager
from veyra.provisioning.renderer import TemplateCatalog
from veyra.telephony import get_adapter
from veyra.version import __version__

log = logging.getLogger("veyra")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_engine(settings)
        with session_scope() as db:
            bootstrap.bootstrap(db)
            if not bootstrap.setup_required(db):
                bootstrap.ensure_local_node(db)
            app.state.modules.startup(app, db)
        log.info("Veyra %s started (%s)", __version__, settings.environment.value)
        yield
        dispose_engine()

    app = FastAPI(
        title="Veyra API",
        version=__version__,
        description="Management API for Veyra — Open Communications Platform.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    # Request handlers receive this app's settings, not the process-wide default.
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.keyring = Keyring.load(settings.trust_dir)
    app.state.modules = ModuleManager(settings, bus, app.state.keyring)
    app.state.telephony = get_adapter(settings)
    app.state.templates = TemplateCatalog.from_paths(settings.template_paths)
    app.state.modules.app = app

    @app.middleware("http")
    async def request_id_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = (
            incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    install_error_handlers(app)
    app.include_router(api_router)
    return app
