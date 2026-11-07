# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where capability packs come from (docs/CONFIG_VERIFICATION.md §2.0): the
built-in ones in the repository, those enabled modules ship, and those an
administrator imported. Also the tools a pack author uses: a skeleton, the
check of a pack against the templates it is for, and archive import."""

from __future__ import annotations

import io
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.models import CapabilityPack
from veyra.provisioning.capabilities import (
    PACK_FILENAME,
    CapabilityCatalog,
    CapabilityError,
    Pack,
    load_pack,
)
from veyra.provisioning.precheck import PrecheckResult, precheck
from veyra.provisioning.renderer import TemplateCatalog
from veyra.provisioning.spec import TemplateError
from veyra.provisioning.verify import Target

MAX_FILES = 500
MAX_BYTES = 4 * 1024 * 1024


# ------------------------------------------------------------------ assembling


def _materialize(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = root / PurePosixPath(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def build(
    builtin: list[Path],
    modules: list[tuple[str, Path]],
    local: list[CapabilityPack],
) -> CapabilityCatalog:
    """The catalog in priority order: built-in, then modules, then imported.
    A later pack with an id already loaded is refused and listed in
    ``load_errors``."""
    catalog = CapabilityCatalog.from_paths(builtin)
    for module_id, path in modules:
        catalog.extend([path], f"module:{module_id}")
    for row in local:
        with tempfile.TemporaryDirectory(prefix="veyra-pack-") as tmp:
            d = _materialize(Path(tmp) / "pack", dict(row.files))
            try:
                pack = load_pack(d, "local")
                pack.path = f"imported:{row.pack_id}"
                catalog.add(pack)
            except CapabilityError as e:
                catalog.load_errors[f"imported:{row.pack_id}"] = e.errors
    return catalog


def stamp(db: Session) -> tuple[int, Any]:
    """What the imported packs look like now: their number and the last import."""
    row = db.execute(
        select(func.count(CapabilityPack.id), func.max(CapabilityPack.updated_at))
    ).one()
    return int(row[0]), row[1]


def rebuild(app: Any, db: Session) -> CapabilityCatalog:
    """Assemble the catalog for this app and keep it in ``app.state``."""
    modules = getattr(app.state, "modules", None)
    dirs = modules.capability_dirs() if modules is not None else []
    local = list(db.scalars(select(CapabilityPack).order_by(CapabilityPack.pack_id)))
    catalog = build(list(app.state.settings.capability_paths), dirs, local)
    app.state.capabilities = catalog
    app.state.capability_stamp = stamp(db)
    return catalog


def current(app: Any, db: Session) -> CapabilityCatalog:
    """The app's catalog, reloaded when packs were imported or removed
    elsewhere: by the console command, or on the other HA node."""
    if stamp(db) != getattr(app.state, "capability_stamp", (0, None)):
        return rebuild(app, db)
    catalog: CapabilityCatalog = app.state.capabilities
    return catalog


# ------------------------------------------------------------------ import


class PackImportError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


def read_archive(data: bytes) -> dict[str, str]:
    """The files of a pack from a ZIP archive: either at its top or in one
    folder. Only text files under the size limits; no absolute paths or
    ``..``."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise PackImportError("The file is not a ZIP archive.") from e
    names = [i for i in zf.infolist() if not i.is_dir()]
    if len(names) > MAX_FILES:
        raise PackImportError(f"The archive has more than {MAX_FILES} files.")
    if sum(i.file_size for i in names) > MAX_BYTES:
        raise PackImportError("The archive is larger than 4 MB unpacked.")
    files: dict[str, str] = {}
    for info in names:
        p = PurePosixPath(info.filename)
        if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
            raise PackImportError(f"{info.filename}: paths must stay inside the pack.")
        if p.name.startswith(".") or p.parts[0] == "__MACOSX":
            continue
        if p.suffix not in (".toml", ".md", ".txt"):
            raise PackImportError(f"{info.filename}: a pack holds only .toml and text files.")
        try:
            files[str(p)] = zf.read(info).decode("utf-8")
        except UnicodeDecodeError as e:
            raise PackImportError(f"{info.filename}: not UTF-8 text.") from e
    if PACK_FILENAME not in files:
        tops = {PurePosixPath(n).parts[0] for n in files}
        if len(tops) == 1 and f"{next(iter(tops))}/{PACK_FILENAME}" in files:
            prefix = next(iter(tops)) + "/"
            files = {n[len(prefix) :]: t for n, t in files.items()}
        else:
            raise PackImportError(f"The archive has no {PACK_FILENAME} at its top.")
    return files


def validate_files(files: dict[str, str]) -> Pack:
    """Load the files as a pack; raises ``CapabilityError`` with every problem."""
    with tempfile.TemporaryDirectory(prefix="veyra-pack-") as tmp:
        return load_pack(_materialize(Path(tmp) / "pack", files), "local")


# ------------------------------------------------------------------ authoring


PACK_SKELETON = """# Capability pack (docs/CAPABILITY_CATALOG.md).
schema = 1

[pack]
id = "{pack_id}"
name = "{name}"
vendor = "{vendor}"
version = "0.1.0"
author = ""
license = ""

# The devices this pack checks, as the vendor's documentation lists them.
[[supports]]
family = "{family}"
models = []
firmware = ""
source = {{ title = "", section = "Supported models", page = "" }}
"""
FAMILY_SKELETON = """schema = 1

[family]
vendor = "{vendor}"
family = "{family}"
name = "{name}"
models = []
format = "cfg"                 # xml | cfg | grandstream-p | algo-conf
version_scheme = "dotted"      # dotted | yealink
firmware_packaging = "family"  # family | model
files = ["{{mac}}.cfg"]         # filename patterns as in template.toml
templates = []                 # template keys that use this family
"""
RELEASE_SKELETON = """# The first release of the family: the full parameter list.
schema = 1

[release]
version = "{version}"
revision = 1

[release.sources.guide]
title = ""
version = "{version}"
"""


def new_pack(directory: Path, vendor: str, family: str, version: str = "1.0") -> list[Path]:
    """Write a pack skeleton; refuses to write over anything."""
    root = directory
    if root.exists() and any(root.iterdir()):
        raise PackImportError(f"{root} is not empty.")
    files = {
        root / PACK_FILENAME: PACK_SKELETON.format(
            pack_id=f"community.{vendor}", name=vendor.title(), vendor=vendor, family=family
        ),
        root / family / "family.toml": FAMILY_SKELETON.format(
            vendor=vendor, family=family, name=f"{vendor.title()} {family}"
        ),
        root / family / f"{version}.toml": RELEASE_SKELETON.format(version=version),
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return list(files)


@dataclass
class PackCheck:
    template_key: str
    model: str
    release: str
    result: PrecheckResult | None = None
    error: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)


def check_pack(pack: Pack, templates: TemplateCatalog) -> list[PackCheck]:
    """Precheck every template the pack's families list, for every model,
    on every release (the oldest version of each): what a release would
    newly refuse shows here before the pack is published."""
    catalog = CapabilityCatalog()
    catalog.add(pack)
    out: list[PackCheck] = []
    for family in pack.families.values():
        for key in family.info.templates:
            rec = templates.records.get(key)
            if rec is None:
                out.append(PackCheck(key, "", "", error="no such template"))
                continue
            for model in rec.manifest.template.models:
                if model not in family.info.models:
                    continue
                for release in family.releases:
                    if release.models and model not in release.models:
                        continue
                    check = PackCheck(key, model, release.version)
                    try:
                        check.result = precheck(
                            catalog,
                            templates.resolve(key),
                            Target(pack.info.vendor, model, release.version, "pack-check"),
                        )
                        check.findings = [
                            f.as_dict() for f in check.result.findings if f.severity != "info"
                        ]
                    except TemplateError as e:
                        check.error = "; ".join(e.errors)
                    out.append(check)
    return out
