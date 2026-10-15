# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test fixtures. Tests run against a real PostgreSQL database.

Set VEYRA_TEST_DATABASE_URL to a database the tests may freely drop and
recreate (default: postgresql+psycopg://veyra_dev:veyra_dev@127.0.0.1/veyra_test).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

os.environ.setdefault("VEYRA_ENV_FILE", "/dev/null")

import veyra
from veyra.core import bootstrap
from veyra.core.config import Environment, Settings
from veyra.core.db import dispose_engine, init_engine, session_scope
from veyra.core.events import bus
from veyra.core.security.crypto import InstallationKey
from veyra.core.security.permissions import registry
from veyra.main import create_app

REPO = Path(__file__).resolve().parents[2]
TEST_DB_URL = os.environ.get(
    "VEYRA_TEST_DATABASE_URL", "postgresql+psycopg://veyra_dev:veyra_dev@127.0.0.1/veyra_test"
)
ADMIN_EMAIL = "admin@district.local"
ADMIN_PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = make_url(TEST_DB_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(veyra.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")
    yield TEST_DB_URL


def make_settings(database_url: str, tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": database_url,
        "database_pool_size": 2,
        "config_dir": tmp_path / "etc",
        "data_dir": tmp_path / "data",
        "log_dir": tmp_path / "log",
        "upgrade_dir": tmp_path / "upgrade",
        "module_paths": [REPO / "modules"],
        "template_paths": [REPO / "provisioning" / "templates"],
        "cookie_secure": False,
        "allow_unsigned_modules": True,
        "telephony_engine": "none",
    }
    values.update(overrides)
    settings = Settings(**values)  # type: ignore[arg-type]
    # Every test installation has its own key, like a real one.
    if not settings.installation_key_path.exists():
        InstallationKey.generate().write(settings.installation_key_path)
    return settings


def _reset_database(url: str) -> None:
    """Drop module tables and their version tables, truncate core tables."""
    engine = create_engine(url)
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        ]
        drop = [t for t in tables if t.startswith(("mod_", "alembic_version_"))]
        if drop:
            conn.execute(text("DROP TABLE " + ", ".join(f'"{t}"' for t in drop) + " CASCADE"))
        core = [t for t in tables if t not in drop and t != "alembic_version"]
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in core) + " CASCADE"))
    engine.dispose()


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return make_settings(database_url, tmp_path)


@pytest.fixture
def db_ready(settings: Settings) -> Iterator[None]:
    import veyra.api.v1.auth as auth_mod

    # The sign-in limiters are per process; a test run signs in far more
    # often than ten times a minute from one address.
    auth_mod._ip_limiter = None
    auth_mod._reset_limiter = None
    _reset_database(settings.database_url)
    init_engine(settings)
    with session_scope() as db:
        bootstrap.bootstrap(db)
    yield
    dispose_engine()
    for perm in [p for p in registry.all() if p.module_id != "core"]:
        registry.unregister_module(perm.module_id)
    bus._subs.clear()


@pytest.fixture
def app(settings: Settings, db_ready: None):  # type: ignore[no-untyped-def]
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with TestClient(app, base_url="http://veyra.test") as c:
        yield c


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("veyra_csrf", "")}


def complete_setup(client: TestClient) -> dict[str, object]:
    with session_scope() as db:
        token = bootstrap.create_setup_token(db)
    r = client.post(
        "/api/v1/setup/initialize",
        json={
            "setup_token": token,
            "installation_name": "Test District",
            "administrator": {
                "email": ADMIN_EMAIL,
                "display_name": "Admin",
                "password": ADMIN_PASSWORD,
            },
            "organization": {
                "name": "Example Schools",
                "slug": "example",
                "timezone": "America/Chicago",
            },
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    """A client signed in as the platform administrator created by setup."""
    complete_setup(client)
    client.headers.update(csrf_headers(client))
    return client


def login(client: TestClient, email: str, password: str) -> TestClient:
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers.update(csrf_headers(client))
    return client
