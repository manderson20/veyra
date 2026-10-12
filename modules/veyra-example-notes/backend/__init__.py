# SPDX-License-Identifier: AGPL-3.0-or-later
"""Example: Notes — reference implementation of a Veyra module.

Only ``veyra.sdk`` is imported from the core; everything else is the
module's own code.
"""

from __future__ import annotations

from veyra.sdk import Event, HealthResult, ModuleContext

from .api import build_router
from .models import metadata


class NotesModule:
    def register(self, ctx: ModuleContext) -> None:
        ctx.register_metadata(metadata)
        ctx.add_router(build_router(ctx))
        ctx.add_health_check(lambda: _health(ctx))
        ctx.subscribe("organization.created", lambda event: _on_org_created(ctx, event))

    # Optional lifecycle hooks -------------------------------------------------
    def on_install(self, ctx: ModuleContext) -> None:
        ctx.log.info("Example notes module installed")

    def on_enable(self, ctx: ModuleContext) -> None:
        ctx.log.info("Example notes module enabled")

    def on_disable(self, ctx: ModuleContext) -> None:
        ctx.log.info("Example notes module disabled")

    def on_uninstall(self, ctx: ModuleContext, purge: bool) -> None:
        ctx.log.info("Example notes module uninstalled (purge=%s)", purge)


def _health(ctx: ModuleContext) -> HealthResult:
    from sqlalchemy import func, select

    from .models import notes

    with ctx.session() as db:
        count = db.scalar(select(func.count()).select_from(notes))
    return HealthResult("ok", f"{count} note(s) stored.", {"notes": count})


def _on_org_created(ctx: ModuleContext, event: Event) -> None:
    ctx.log.info("New organization %s — nothing to provision for notes", event.payload.get("slug"))


module = NotesModule()
