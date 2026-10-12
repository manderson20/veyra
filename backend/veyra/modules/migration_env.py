# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared Alembic environment for module migrations.

A module's ``migrations/env.py`` contains only::

    from veyra.modules.migration_env import run
    run()

Veyra passes the connection, the module's version table and its table
prefix through the Alembic config attributes.
"""

from __future__ import annotations

from alembic import context


def run() -> None:
    config = context.config
    connection = config.attributes["connection"]
    version_table = config.attributes["version_table"]
    context.configure(
        connection=connection,
        target_metadata=config.attributes.get("target_metadata"),
        version_table=version_table,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()
