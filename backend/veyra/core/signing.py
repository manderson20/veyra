"""Ed25519 signing and verification shared by module packages, provisioning
template packages and update metadata.

Trust keyring layout (installed by the installer, root-owned, read-only):

    /etc/veyra/trust/official/<key_id>.pub
    /etc/veyra/trust/community/<key_id>.pub
    /etc/veyra/trust/third_party/<key_id>.pub

Each ``.pub`` file holds a base64-encoded raw 32-byte Ed25519 public key. The
directory a key is in determines the trust level of anything it signs; a
publisher cannot claim a trust level for itself.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

KEY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")


class TrustLevel(StrEnum):
    OFFICIAL = "official"
    COMMUNITY = "community"
    THIRD_PARTY = "third_party"
    # Never stored for production use: unsigned content loaded in development.
    UNSIGNED = "unsigned"


class SignatureError(ValueError):
    pass


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    trust_level: TrustLevel
    public_key: Ed25519PublicKey


class Keyring:
    def __init__(self, keys: list[TrustedKey] | None = None) -> None:
        self._keys = {k.key_id: k for k in keys or []}

    @classmethod
    def load(cls, trust_dir: Path) -> Keyring:
        keys: list[TrustedKey] = []
        for level in (TrustLevel.OFFICIAL, TrustLevel.COMMUNITY, TrustLevel.THIRD_PARTY):
            d = trust_dir / level.value
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.pub")):
                if KEY_ID_RE.match(f.stem):
                    keys.append(TrustedKey(f.stem, level, load_public_key(f.read_text())))
        return cls(keys)

    def get(self, key_id: str) -> TrustedKey | None:
        return self._keys.get(key_id)

    def __len__(self) -> int:
        return len(self._keys)


def load_public_key(text: str) -> Ed25519PublicKey:
    try:
        raw = base64.b64decode(text.strip(), validate=True)
        return Ed25519PublicKey.from_public_bytes(raw)
    except (binascii.Error, ValueError) as e:
        raise SignatureError("Invalid Ed25519 public key") from e


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_b64, public_key_b64) — for packaging tools and tests."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()


def load_private_key(text: str) -> Ed25519PrivateKey:
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(text.strip(), validate=True))
    except (binascii.Error, ValueError) as e:
        raise SignatureError("Invalid Ed25519 private key") from e


def sign(data: bytes, private_key_b64: str, key_id: str) -> str:
    """Returns a detached signature document (JSON)."""
    if not KEY_ID_RE.match(key_id):
        raise SignatureError("Invalid key id")
    sig = load_private_key(private_key_b64).sign(data)
    return (
        json.dumps(
            {"algorithm": "ed25519", "key_id": key_id, "signature": base64.b64encode(sig).decode()},
            indent=2,
        )
        + "\n"
    )


def verify(data: bytes, signature_doc: str, keyring: Keyring) -> TrustedKey:
    """Verify a detached signature; returns the key that signed it."""
    try:
        doc = json.loads(signature_doc)
        algorithm, key_id, sig_b64 = doc["algorithm"], doc["key_id"], doc["signature"]
    except (ValueError, KeyError, TypeError) as e:
        raise SignatureError("Malformed signature document") from e
    if algorithm != "ed25519":
        raise SignatureError(f"Unsupported signature algorithm {algorithm!r}")
    key = keyring.get(str(key_id))
    if key is None:
        raise SignatureError(f"Signing key {key_id!r} is not trusted on this installation")
    try:
        key.public_key.verify(base64.b64decode(sig_b64, validate=True), data)
    except (InvalidSignature, binascii.Error, ValueError) as e:
        raise SignatureError("Signature verification failed") from e
    return key


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
