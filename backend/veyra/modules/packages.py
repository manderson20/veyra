"""Module package format, integrity verification and safe extraction.

A module package (``<id>-<version>.vmod``) is a gzip-compressed tar archive:

    module.toml          manifest
    SHA256SUMS           "<sha256>  <relative path>" for every other file
    SIGNATURE            detached Ed25519 signature over SHA256SUMS
    ...                  module files

The same SHA256SUMS/SIGNATURE pair is kept in the installed module directory,
so integrity is re-verified every time the module is loaded.
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from veyra.core.signing import (
    Keyring,
    SignatureError,
    TrustLevel,
    sha256_file,
    sign,
    verify,
)
from veyra.modules.manifest import MANIFEST_FILENAME, Manifest, load_manifest

SUMS_FILENAME = "SHA256SUMS"
SIGNATURE_FILENAME = "SIGNATURE"
PACKAGE_SUFFIX = ".vmod"
MAX_PACKAGE_FILES = 5000
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
_IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class Verification:
    verified: bool
    trust_level: TrustLevel
    key_id: str | None
    error: str | None = None


def _iter_files(root: Path) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if rel in (SUMS_FILENAME, SIGNATURE_FILENAME) or name.endswith(".pyc"):
                continue
            if full.is_symlink():
                raise PackageError(f"Symbolic links are not allowed in modules: {rel}")
            files.append(rel)
    return files


def compute_sums(root: Path) -> str:
    return "".join(f"{sha256_file(root / rel)}  {rel}\n" for rel in _iter_files(root))


def sign_directory(root: Path, private_key_b64: str, key_id: str) -> None:
    """Write SHA256SUMS and SIGNATURE into a module directory (packaging tool)."""
    load_manifest(root)  # refuse to sign an invalid module
    sums = compute_sums(root)
    (root / SUMS_FILENAME).write_text(sums)
    (root / SIGNATURE_FILENAME).write_text(sign(sums.encode(), private_key_b64, key_id))


def verify_directory(root: Path, keyring: Keyring) -> Verification:
    sums_path, sig_path = root / SUMS_FILENAME, root / SIGNATURE_FILENAME
    if not sums_path.is_file() or not sig_path.is_file():
        return Verification(False, TrustLevel.UNSIGNED, None, "Module is not signed")
    sums = sums_path.read_bytes()
    try:
        key = verify(sums, sig_path.read_text(), keyring)
    except SignatureError as e:
        return Verification(False, TrustLevel.UNSIGNED, None, str(e))
    expected: dict[str, str] = {}
    for line in sums.decode().splitlines():
        digest, _, rel = line.partition("  ")
        if not rel or len(digest) != 64:
            return Verification(False, TrustLevel.UNSIGNED, key.key_id, "Malformed SHA256SUMS")
        expected[rel] = digest
    try:
        actual_files = _iter_files(root)
    except PackageError as e:
        return Verification(False, TrustLevel.UNSIGNED, key.key_id, str(e))
    if set(actual_files) != set(expected):
        extra = sorted(set(actual_files) - set(expected))
        missing = sorted(set(expected) - set(actual_files))
        return Verification(
            False,
            TrustLevel.UNSIGNED,
            key.key_id,
            f"File list mismatch (unexpected: {extra[:5]}, missing: {missing[:5]})",
        )
    for rel, digest in expected.items():
        if sha256_file(root / rel) != digest:
            return Verification(
                False, TrustLevel.UNSIGNED, key.key_id, f"Integrity check failed for {rel}"
            )
    return Verification(True, key.trust_level, key.key_id)


def build_package(root: Path, output_dir: Path) -> Path:
    """Create a .vmod from a signed module directory."""
    manifest = load_manifest(root)
    if not (root / SIGNATURE_FILENAME).is_file():
        raise PackageError("Sign the module directory before packaging")
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{manifest.id}-{manifest.module.version}{PACKAGE_SUFFIX}"
    with tarfile.open(out, "w:gz") as tar:
        for rel in [*_iter_files(root), SUMS_FILENAME, SIGNATURE_FILENAME]:
            info = tar.gettarinfo(str(root / rel), arcname=rel)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o644
            with (root / rel).open("rb") as f:
                tar.addfile(info, f)
    return out


def _safe_member(member: tarfile.TarInfo) -> str:
    name = member.name
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or name.startswith(("/", "\\")) or "\\" in name:
        raise PackageError(f"Unsafe path in package: {name!r}")
    if not (member.isfile() or member.isdir()):
        raise PackageError(f"Unsupported entry type in package: {name!r}")
    return p.as_posix()


def extract_package(package: Path | bytes, dest_parent: Path) -> Path:
    """Safely extract a package into a new temporary directory under dest_parent.

    Rejects absolute paths, parent-directory references, links, devices,
    oversized archives and archives with too many files. Returns the
    extraction directory; the caller verifies it and moves it into place.
    """
    dest_parent.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix=".extract-", dir=dest_parent))
    fileobj = io.BytesIO(package) if isinstance(package, bytes) else None
    try:
        with tarfile.open(
            name=None if fileobj else str(package), fileobj=fileobj, mode="r:gz"
        ) as tar:
            members = tar.getmembers()
            if len(members) > MAX_PACKAGE_FILES:
                raise PackageError("Package contains too many files")
            total = 0
            for m in members:
                rel = _safe_member(m)
                total += m.size
                if total > MAX_UNPACKED_BYTES:
                    raise PackageError("Package is too large")
                out = target / rel
                if m.isdir():
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                if src is None:
                    raise PackageError(f"Cannot read {rel}")
                with out.open("wb") as f:
                    shutil.copyfileobj(src, f)
                out.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    except (tarfile.TarError, OSError, PackageError) as e:
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(e, PackageError):
            raise
        raise PackageError(f"Cannot read package: {e}") from e
    return target


def inspect_package(
    package: Path, keyring: Keyring, scratch: Path
) -> tuple[Manifest, Verification]:
    """Extract to scratch, verify and parse the manifest, then clean up."""
    d = extract_package(package, scratch)
    try:
        if not (d / MANIFEST_FILENAME).is_file():
            raise PackageError("Package has no module.toml")
        return load_manifest(d), verify_directory(d, keyring)
    finally:
        shutil.rmtree(d, ignore_errors=True)
