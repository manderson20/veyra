"""Application settings.

Settings are read from environment variables prefixed with ``VEYRA_`` and,
when present, from the environment file written by the installer
(``/etc/veyra/veyra.env``). Secrets are never given defaults that would work
in production: the database URL must be supplied explicitly.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ENV_FILE = Path("/etc/veyra/veyra.env")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VEYRA_",
        env_file=os.environ.get("VEYRA_ENV_FILE", str(DEFAULT_ENV_FILE)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.PRODUCTION

    # --- Database -------------------------------------------------------------
    database_url: str = Field(
        default="",
        description="SQLAlchemy URL, e.g. postgresql+psycopg://veyra@/veyra?host=/run/postgresql",
    )
    database_pool_size: int = 10

    # --- Paths ----------------------------------------------------------------
    config_dir: Path = Path("/etc/veyra")
    data_dir: Path = Path("/var/lib/veyra")
    log_dir: Path = Path("/var/log/veyra")
    module_paths: Annotated[list[Path], NoDecode] = Field(
        default_factory=lambda: [Path("/opt/veyra/modules")]
    )
    template_paths: Annotated[list[Path], NoDecode] = Field(
        default_factory=lambda: [Path("/opt/veyra/provisioning/templates")]
    )

    # --- Sessions & security --------------------------------------------------
    session_ttl_hours: int = 12
    session_idle_minutes: int = 60
    cookie_secure: bool = True
    login_rate_limit_per_minute: int = 10
    account_lockout_threshold: int = 10
    account_lockout_minutes: int = 15
    trusted_proxy_count: int = 1

    # --- Modules --------------------------------------------------------------
    # Unsigned modules may only be loaded in development. Never enable this
    # in production; the setting is ignored when environment == production.
    allow_unsigned_modules: bool = False

    # --- Telephony ------------------------------------------------------------
    telephony_engine: str = "asterisk"
    asterisk_ari_url: str = "http://127.0.0.1:8088/ari"
    asterisk_ari_username: str = "veyra"
    asterisk_ari_password_file: Path = Path("/etc/veyra/secrets/ari_password")

    # --- Updates --------------------------------------------------------------
    update_metadata_url: str = ""

    @field_validator("module_paths", "template_paths", mode="before")
    @classmethod
    def _split_paths(cls, value: object) -> object:
        if isinstance(value, str):
            return [Path(p) for p in value.split(":") if p]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def unsigned_modules_permitted(self) -> bool:
        return self.allow_unsigned_modules and not self.is_production

    @property
    def trust_dir(self) -> Path:
        return self.config_dir / "trust"

    @property
    def node_identity_file(self) -> Path:
        return self.config_dir / "node.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
