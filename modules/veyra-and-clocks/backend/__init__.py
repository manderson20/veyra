# SPDX-License-Identifier: AGPL-3.0-or-later
"""AND Clock Messages: text and alerts to Advanced Network Devices clocks and
signs, like AND's Clockwise software (docs/PAGING_RECORDINGS.md §6).

Only ``veyra.sdk`` is imported from the core.
"""

from __future__ import annotations

from sqlalchemy import func, select

from veyra.sdk import HealthResult, ModuleContext

from . import service
from .api import build_router
from .models import clocks, delivery, metadata


class AndClocksModule:
    def register(self, ctx: ModuleContext) -> None:
        ctx.register_metadata(metadata)
        ctx.add_router(build_router(ctx))
        ctx.add_health_check(lambda: _health(ctx))
        ctx.subscribe("bell.rang", lambda event: service.on_bell(ctx, event))
        # Run by the worker service (module API 1.1).
        ctx.add_periodic_task("send-due-messages", 5, lambda: service.dispatch_due(ctx))
        ctx.add_periodic_task("check-clocks", 60, lambda: service.check_reachability(ctx))


def _health(ctx: ModuleContext) -> HealthResult:
    with ctx.session() as db:
        total = db.scalar(select(func.count()).select_from(clocks)) or 0
        down = (
            db.scalar(
                select(func.count())
                .select_from(clocks)
                .where(clocks.c.reachability == "unreachable")
            )
            or 0
        )
        orgs_with_clocks = set(db.scalars(select(clocks.c.organization_id).distinct()))
        orgs_with_delivery = set(db.scalars(select(delivery.c.organization_id)))
    missing = orgs_with_clocks - orgs_with_delivery
    details = {"clocks": total, "unreachable": down, "organizations_without_delivery": len(missing)}
    if missing:
        return HealthResult("degraded", "Clocks exist but delivery is not set up.", details)
    if down:
        return HealthResult("degraded", f"{down} of {total} clock(s) unreachable.", details)
    return HealthResult("ok", f"{total} clock(s) reachable.", details)


module = AndClocksModule()
