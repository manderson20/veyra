# SPDX-License-Identifier: AGPL-3.0-or-later
"""The module catalog and store (docs/MODULE_CATALOG.md §2-4).

* A catalog is a signed ``index.json`` (``index.json.sig`` next to it)
  listing modules, versions, package URLs and SHA-256 sums; it is accepted
  only when signed by a key in ``/etc/veyra/trust/catalog/``.
* Packages are verified twice: the download must match the index's
  SHA-256, and the extracted module must carry a valid publisher signature
  (whose trust directory decides the trust level, as for any module).
* The store keeps what runs in ``<data>/module-store/active/<dir>`` (first
  in the module search path) and the previous version in
  ``<data>/module-store/versions/<id>-<version>``."""

from __future__ import annotations

import ipaddress
import json
import logging
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from veyra.core.semver import Version, VersionRange
from veyra.core.signing import (
    Keyring,
    SignatureError,
    TrustedKey,
    TrustLevel,
    load_public_key,
    verify,
)
from veyra.modules.manifest import Manifest, ManifestError, load_manifest
from veyra.modules.packages import extract_package, verify_directory

log = logging.getLogger("veyra.modules")

MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
TIMEOUT = 30
CATALOG_TRUST = "catalog"


class CatalogError(Exception):
    pass


# ------------------------------------------------------------------ index


class CatalogVersion(BaseModel):
    version: str
    core_api: str
    url: str = Field(max_length=1000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=1, le=MAX_PACKAGE_BYTES)
    released: str | None = None
    notes: str | None = Field(None, max_length=4000)

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        Version.parse(v)
        return v

    @field_validator("core_api")
    @classmethod
    def _range(cls, v: str) -> str:
        VersionRange.parse(v)
        return v


class CatalogModule(BaseModel):
    id: str = Field(max_length=128)
    name: str = Field(max_length=200)
    summary: str | None = Field(None, max_length=1000)
    publisher: str | None = Field(None, max_length=200)
    homepage: str | None = Field(None, max_length=500)
    versions: list[CatalogVersion] = Field(min_length=1)


class CatalogIndex(BaseModel):
    catalog_version: int = 1
    name: str = Field("Modules", max_length=200)
    generated_at: str | None = None
    modules: list[CatalogModule] = Field(default_factory=list)


def catalog_keyring(trust_dir: Path) -> Keyring:
    """Keys trusted to sign catalog indexes (not packages)."""
    keys: list[TrustedKey] = []
    d = trust_dir / CATALOG_TRUST
    if d.is_dir():
        for f in sorted(d.glob("*.pub")):
            try:
                keys.append(TrustedKey(f.stem, TrustLevel.OFFICIAL, load_public_key(f.read_text())))
            except SignatureError:
                log.warning("Ignoring malformed catalog key %s", f)
    return Keyring(keys)


def parse_index(data: bytes, signature: str, keyring: Keyring) -> tuple[CatalogIndex, str]:
    """Verify and parse; returns the index and the key id that signed it."""
    if not len(keyring):
        raise CatalogError("No catalog key is trusted on this server (/etc/veyra/trust/catalog/).")
    try:
        key = verify(data, signature, keyring)
    except SignatureError as e:
        raise CatalogError(f"The catalog signature is not valid: {e}") from e
    try:
        return CatalogIndex.model_validate(json.loads(data)), key.key_id
    except (ValueError, ValidationError) as e:
        raise CatalogError(f"The catalog index is malformed: {str(e).splitlines()[0]}") from e


# --------------------------------------------------------------- download


def _check_url(url: str) -> None:
    """HTTPS, or plain HTTP to this machine only (a local test catalog)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        return
    if parts.scheme == "http":
        host = parts.hostname or ""
        try:
            if host == "localhost" or ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
    raise CatalogError(f"Only HTTPS addresses are allowed ({url}).")


def fetch(url: str, limit: int) -> bytes:
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Veyra module catalog"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
            _check_url(resp.geturl())  # redirects must stay on HTTPS
            data: bytes = resp.read(limit + 1)
    except OSError as e:
        raise CatalogError(f"Could not download {url}: {e}") from e
    if len(data) > limit:
        raise CatalogError(f"{url} is larger than {limit // (1024 * 1024)} MB.")
    return data


def fetch_index(url: str, keyring: Keyring) -> tuple[CatalogIndex, str]:
    data = fetch(url, MAX_INDEX_BYTES)
    sig = fetch(url + ".sig", 64 * 1024).decode("utf-8", "replace")
    return parse_index(data, sig, keyring)


def download_package(v: CatalogVersion) -> bytes:
    import hashlib

    data = fetch(v.url, MAX_PACKAGE_BYTES)
    if len(data) != v.size or hashlib.sha256(data).hexdigest() != v.sha256:
        raise CatalogError("The download does not match the catalog's size and checksum.")
    return data


# ------------------------------------------------------------------ store


def _manifest_or_none(d: Path) -> Manifest | None:
    """The manifest of a store entry, or None for a broken or foreign one."""
    if not (d / "module.toml").is_file():
        return None
    try:
        return load_manifest(d)
    except (ManifestError, OSError):
        return None


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active = root / "active"
        self.versions = root / "versions"
        self.staging = root / "staging"

    def ensure(self) -> None:
        for d in (self.active, self.versions, self.staging):
            d.mkdir(parents=True, exist_ok=True)

    def active_dir(self, module_id: str) -> Path | None:
        if not self.active.is_dir():
            return None
        for d in self.active.iterdir():
            m = _manifest_or_none(d)
            if m is not None and m.id == module_id:
                return d
        return None

    def previous(self, module_id: str) -> tuple[Path, Manifest] | None:
        best: tuple[Path, Manifest] | None = None
        if not self.versions.is_dir():
            return None
        for d in self.versions.iterdir():
            m = _manifest_or_none(d)
            if (
                m is not None
                and m.id == module_id
                and (
                    best is None
                    or Version.parse(m.module.version) > Version.parse(best[1].module.version)
                )
            ):
                best = (d, m)
        return best

    def add(
        self, package: bytes, keyring: Keyring, allow_unsigned: bool = False
    ) -> tuple[Manifest, Any]:
        """Extract into staging and verify; returns the manifest and the
        verification (trust level). Nothing becomes active yet."""
        self.ensure()
        tmp = Path(tempfile.mkdtemp(dir=self.staging))
        try:
            path = extract_package(package, tmp)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise CatalogError(f"The package cannot be opened: {e}") from e
        try:
            manifest = load_manifest(path)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise CatalogError(f"The package's manifest is not valid: {e}") from e
        verification = verify_directory(path, keyring)
        if not verification.verified and not allow_unsigned:
            shutil.rmtree(tmp, ignore_errors=True)
            raise CatalogError(f"The package's signature is not valid: {verification.error}")
        target = self.versions / f"{manifest.id}-{manifest.module.version}"
        if target.exists():
            shutil.rmtree(target)
        path.rename(target)
        shutil.rmtree(tmp, ignore_errors=True)
        return manifest, verification

    def activate(self, module_id: str, version: str) -> Path:
        """Make ``versions/<id>-<version>`` the active copy; the current one
        becomes the previous version (older ones are removed)."""
        self.ensure()
        new = self.versions / f"{module_id}-{version}"
        if not new.is_dir():
            raise CatalogError(f"{module_id} {version} is not in the store.")
        current = self.active_dir(module_id)
        dirname = module_id.replace(".", "-")
        if current is not None:
            cur_version = load_manifest(current).module.version
            current.rename(self.versions / f"{module_id}-{cur_version}")
        dest = self.active / dirname
        new.rename(dest)
        self._prune(module_id, keep_version=None if current is None else cur_version)
        return dest

    def _prune(self, module_id: str, keep_version: str | None) -> None:
        if not self.versions.is_dir():
            return
        for d in list(self.versions.iterdir()):
            m = _manifest_or_none(d)
            if m is not None and m.id == module_id and m.module.version != keep_version:
                shutil.rmtree(d, ignore_errors=True)

    def remove(self, module_id: str) -> None:
        current = self.active_dir(module_id)
        if current is not None:
            shutil.rmtree(current, ignore_errors=True)
        self._prune(module_id, keep_version=None)


def migration_files(module_dir: Path) -> set[str]:
    d = module_dir / "migrations" / "versions"
    return {p.name for p in d.glob("*.py")} if d.is_dir() else set()


# ------------------------------------------------------------- worker side

REFRESH_HOURS = 24
RESTART_KEY = "services.restart"
RESTART_RESULT_KEY = "services.restart_result"
VEYRA_UNITS = ("veyra-api", "veyra-deployer", "veyra-pager", "veyra-firewall", "veyra-worker")


def refresh_source(source: Any, trust_dir: Path) -> None:
    """Fetch and verify a catalog source; keeps the last verified index when
    this attempt fails."""
    from veyra.core.models.base import utcnow

    source.last_fetched_at = utcnow()
    try:
        index, key_id = fetch_index(source.url, catalog_keyring(trust_dir))
    except CatalogError as e:
        source.last_status, source.last_error = "failed", str(e)[:500]
        return
    source.index = index.model_dump(mode="json")
    source.signed_by = key_id
    source.last_status, source.last_error = "ok", None


def refresh_due(db: Any, trust_dir: Path) -> int:
    from datetime import timedelta

    from sqlalchemy import or_, select

    from veyra.core.models import CatalogSource
    from veyra.core.models.base import utcnow

    due = db.scalars(
        select(CatalogSource).where(
            CatalogSource.is_enabled.is_(True),
            or_(
                CatalogSource.last_fetched_at.is_(None),
                CatalogSource.last_fetched_at < utcnow() - timedelta(hours=REFRESH_HOURS),
            ),
        )
    ).all()
    for s in due:
        refresh_source(s, trust_dir)
    return len(due)


def run_restart_request(db: Any, run: Any = None) -> bool:
    """Restart Veyra's units when an administrator asked for it
    (docs/MODULE_CATALOG.md §4). The polkit rule lets the service account
    restart exactly these units; Asterisk is not touched.

    The request is removed and committed *before* systemctl runs: the worker
    is one of the units, systemd stops it right away, and an uncommitted
    removal would make every new worker restart everything again."""
    import subprocess

    from veyra.core.models import SystemSetting
    from veyra.core.models.base import utcnow

    row = db.get(SystemSetting, RESTART_KEY)
    if row is None:
        return False
    db.delete(row)
    _restart_result(db, {"at": utcnow().isoformat(), "ok": None, "error": None, "state": "started"})
    db.commit()
    cmd = ["systemctl", "restart", "--no-block", *VEYRA_UNITS]
    if run is None:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    else:
        res = run(cmd)
    ok = getattr(res, "returncode", 1) == 0
    # Usually not reached when it worked: systemd stops this worker first.
    _restart_result(
        db,
        {
            "at": utcnow().isoformat(),
            "ok": ok,
            "error": None
            if ok
            else (getattr(res, "stderr", "") or "systemctl failed").strip()[:500],
            "state": "done" if ok else "failed",
        },
    )
    db.commit()
    return ok


def _restart_result(db: Any, value: dict[str, Any]) -> None:
    from veyra.core.models import SystemSetting

    result = db.get(SystemSetting, RESTART_RESULT_KEY)
    if result is None:
        db.add(SystemSetting(key=RESTART_RESULT_KEY, value=value))
    else:
        result.value = value


def confirm_restart(db: Any) -> None:
    """At worker start: a restart that was "started" has finished."""
    from veyra.core.models import SystemSetting
    from veyra.core.models.base import utcnow

    row = db.get(SystemSetting, RESTART_RESULT_KEY)
    if row is not None and isinstance(row.value, dict) and row.value.get("state") == "started":
        row.value = {**row.value, "state": "done", "ok": True, "finished_at": utcnow().isoformat()}
