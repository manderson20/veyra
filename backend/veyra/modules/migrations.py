"""Per-module database migrations.

Each module keeps an independent Alembic history with its own version table
(``alembic_version_<module>``), so modules can be upgraded independently of
the core and of each other.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from veyra.modules.manifest import Manifest


def version_table(manifest: Manifest) -> str:
    name = "alembic_version_" + re.sub(r"[^a-z0-9]+", "_", manifest.id)
    if len(name) > 63:  # PostgreSQL identifier limit
        name = name[:52] + "_" + hashlib.sha256(manifest.id.encode()).hexdigest()[:10]
    return name


def _config(manifest: Manifest, module_dir: Path, connection: object) -> Config | None:
    if not manifest.database or not manifest.database.migrations:
        return None
    script_dir = (module_dir / manifest.database.migrations).resolve()
    if not script_dir.is_relative_to(module_dir.resolve()):
        raise ValueError("database.migrations must be inside the module directory")
    cfg = Config()
    cfg.set_main_option("script_location", str(script_dir))
    cfg.attributes["connection"] = connection
    cfg.attributes["version_table"] = version_table(manifest)
    return cfg


def upgrade(engine: Engine, manifest: Manifest, module_dir: Path, revision: str = "heads") -> bool:
    with engine.begin() as conn:
        cfg = _config(manifest, module_dir, conn)
        if cfg is None:
            return False
        command.upgrade(cfg, revision)
    return True


def downgrade_to_base(engine: Engine, manifest: Manifest, module_dir: Path) -> bool:
    """Drop the module's schema. Only called for an explicit, confirmed purge."""
    with engine.begin() as conn:
        cfg = _config(manifest, module_dir, conn)
        if cfg is None:
            return False
        command.downgrade(cfg, "base")
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{version_table(manifest)}"')
    return True


def module_tables(engine: Engine, manifest: Manifest) -> list[str]:
    if not manifest.database:
        return []
    prefix = manifest.database.table_prefix
    return [t for t in inspect(engine).get_table_names() if t.startswith(prefix)]
