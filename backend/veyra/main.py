# SPDX-License-Identifier: AGPL-3.0-or-later
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
from fastapi.responses import JSONResponse

from veyra.api.v1 import api_router
from veyra.core import bootstrap
from veyra.core.callevents import CallEventHub
from veyra.core.config import Settings, get_settings
from veyra.core.db import dispose_engine, init_engine, session_scope
from veyra.core.deps import SAFE_METHODS
from veyra.core.errors import PROBLEM_JSON, install_error_handlers, problem_body
from veyra.core.events import bus
from veyra.core.security.crypto import InstallationKeyError, load_installation_key
from veyra.core.signing import Keyring
from veyra.modules.manager import ModuleManager
from veyra.provisioning.renderer import TemplateCatalog
from veyra.telephony import get_adapter
from veyra.telephony.asterisk.ari import AriClient
from veyra.telephony.asterisk.events import AriEventListener
from veyra.version import __version__

log = logging.getLogger("veyra")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}

# Fetch metadata (Sec-Fetch-Site) is sent by every current browser. The UI
# is served from the API's own origin, so a state-changing request that a
# browser labels as coming from another site is refused before any handler
# runs. Requests without the header (older clients, scripts, tests) fall
# through to the CSRF token check, so this is defence in depth, not the
# primary control.
_REJECTED_FETCH_SITES = frozenset({"cross-site", "same-site"})


def _start_event_listener(app: FastAPI) -> AriEventListener | None:
    """Call events for the Companion (docs/COMPANION.md §4): one ARI event
    socket per API process, only when the engine is Asterisk."""
    adapter = app.state.telephony
    ari = getattr(adapter, "ari", None)
    if ari is None or not isinstance(ari, AriClient):
        app.state.callevents.state = "disabled"
        return None
    listener = AriEventListener(ari, app.state.callevents)
    listener.start()
    app.state.callevents_listener = listener
    return listener


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
        try:
            key = load_installation_key(settings)
            log.info("Installation key loaded (fingerprint %s)", key.fingerprint)
        except InstallationKeyError as e:
            log.warning("No usable installation key: %s. SIP secrets cannot be stored.", e)
        listener = _start_event_listener(app)
        log.info("Veyra %s started (%s)", __version__, settings.environment.value)
        yield
        if listener is not None:
            await listener.stop()
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
    app.state.callevents = CallEventHub()
    app.state.modules.app = app

    @app.middleware("http")
    async def request_id_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = (
            incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex
        )
        response: Response
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get("sec-fetch-site", "").lower() in _REJECTED_FETCH_SITES
            # A bearer token is never attached by the browser on its own, so the
            # fetch-metadata check (which protects cookie sessions) does not apply.
            and not request.headers.get("authorization", "").lower().startswith("bearer ")
        ):
            response = JSONResponse(
                problem_body(
                    request,
                    403,
                    "Forbidden",
                    "Cross-site requests are not accepted.",
                    "cross_site_request",
                ),
                status_code=403,
                media_type=PROBLEM_JSON,
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    install_error_handlers(app)
    app.include_router(api_router)
    return app
