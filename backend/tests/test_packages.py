import io
import shutil
import tarfile
from pathlib import Path

import pytest
from conftest import REPO

from veyra.core.signing import (
    Keyring,
    SignatureError,
    TrustedKey,
    TrustLevel,
    generate_keypair,
    load_public_key,
    sign,
    verify,
)
from veyra.modules.packages import (
    PackageError,
    build_package,
    extract_package,
    inspect_package,
    sign_directory,
    verify_directory,
)

EXAMPLE = REPO / "modules" / "veyra-example-notes"


def keyring_with(level: TrustLevel, key_id: str = "test-key") -> tuple[Keyring, str]:
    priv, pub = generate_keypair()
    return Keyring([TrustedKey(key_id, level, load_public_key(pub))]), priv


@pytest.fixture
def module_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "mod"
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def test_sign_and_verify(module_copy):
    keyring, priv = keyring_with(TrustLevel.OFFICIAL)
    sign_directory(module_copy, priv, "test-key")
    v = verify_directory(module_copy, keyring)
    assert v.verified and v.trust_level == TrustLevel.OFFICIAL and v.key_id == "test-key"


def test_trust_level_comes_from_keyring(module_copy):
    keyring, priv = keyring_with(TrustLevel.COMMUNITY)
    sign_directory(module_copy, priv, "test-key")
    assert verify_directory(module_copy, keyring).trust_level == TrustLevel.COMMUNITY


def test_unsigned_and_untrusted(module_copy):
    keyring, _ = keyring_with(TrustLevel.OFFICIAL)
    assert not verify_directory(module_copy, keyring).verified
    _, other_priv = keyring_with(TrustLevel.OFFICIAL, "other-key")
    sign_directory(module_copy, other_priv, "other-key")
    v = verify_directory(module_copy, keyring)
    assert not v.verified and "not trusted" in (v.error or "")


@pytest.mark.parametrize("tamper", ["modify", "add", "remove"])
def test_tampering_detected(module_copy, tamper):
    keyring, priv = keyring_with(TrustLevel.OFFICIAL)
    sign_directory(module_copy, priv, "test-key")
    target = module_copy / "backend" / "api.py"
    if tamper == "modify":
        target.write_text(target.read_text() + "\n# injected\n")
    elif tamper == "add":
        (module_copy / "backend" / "evil.py").write_text("import os\n")
    else:
        target.unlink()
    v = verify_directory(module_copy, keyring)
    assert not v.verified


def test_symlinks_rejected(module_copy):
    _, priv = keyring_with(TrustLevel.OFFICIAL)
    (module_copy / "link").symlink_to("/etc/passwd")
    with pytest.raises(PackageError):
        sign_directory(module_copy, priv, "test-key")


def test_package_roundtrip(module_copy, tmp_path):
    keyring, priv = keyring_with(TrustLevel.OFFICIAL)
    sign_directory(module_copy, priv, "test-key")
    pkg = build_package(module_copy, tmp_path / "out")
    assert pkg.name == "veyra.example-notes-0.1.0.vmod"
    manifest, v = inspect_package(pkg, keyring, tmp_path / "scratch")
    assert manifest.id == "veyra.example-notes" and v.verified


def _tar(entries: list[tarfile.TarInfo]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for info in entries:
            data = b"x" * info.size if info.isfile() else None
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


@pytest.mark.parametrize("name", ["../escape.py", "/etc/cron.d/evil", "a/../../b"])
def test_path_traversal_rejected(tmp_path, name):
    info = tarfile.TarInfo(name)
    info.size = 1
    with pytest.raises(PackageError):
        extract_package(_tar([info]), tmp_path)
    assert not (tmp_path.parent / "escape.py").exists()


def test_links_in_archive_rejected(tmp_path):
    info = tarfile.TarInfo("link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    with pytest.raises(PackageError):
        extract_package(_tar([info]), tmp_path)


def test_detached_signature_errors():
    keyring, priv = keyring_with(TrustLevel.OFFICIAL)
    doc = sign(b"data", priv, "test-key")
    assert verify(b"data", doc, keyring).key_id == "test-key"
    with pytest.raises(SignatureError):
        verify(b"other", doc, keyring)
    with pytest.raises(SignatureError):
        verify(b"data", "{not json", keyring)
