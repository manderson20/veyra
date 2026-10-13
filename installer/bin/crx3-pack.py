#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Package a built browser extension directory as a signed CRX3 file.

    crx3-pack.py --key KEYFILE --src DIST_DIR --out FILE.crx [--info FILE.json]

The key is an RSA private key in PEM form; it is created when the file does
not exist (2048 bits), because the extension ID is derived from the public
key and must stay the same across releases (docs/COMPANION.md §5). Written
for the release's Python environment (needs the ``cryptography`` package).

CRX3 layout: "Cr24", version 3, header length, header (protobuf
CrxFileHeader: repeated AsymmetricKeyProof sha256_with_rsa {public_key,
signature} and signed_header_data {crx_id}), then the ZIP archive. The
signature covers "CRX3 SignedData\\x00" + len(signed_header_data) +
signed_header_data + zip.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    """A length-delimited protobuf field (wire type 2)."""
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def load_or_create_key(path: Path) -> rsa.RSAPrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise SystemExit(f"{path}: not an RSA private key")
        return key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return key


def extension_id(spki_der: bytes) -> str:
    digest = hashlib.sha256(spki_der).digest()[:16]
    return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0x0F)) for b in digest)


def zip_directory(src: Path, manifest_override: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src):
            for name in sorted(files):
                path = Path(root) / name
                rel = path.relative_to(src).as_posix()
                if rel == "manifest.json" and manifest_override is not None:
                    z.writestr("manifest.json", manifest_override)
                else:
                    z.write(path, rel)
    return buf.getvalue()


def with_host_permissions(manifest: dict, patterns: list[str]) -> dict:
    """A policy-installed extension gets its *required* host permissions without
    asking, so the packaged copy declares the server as a required host while
    the loose build keeps it optional (docs/COMPANION.md §5)."""
    out = dict(manifest)
    required = list(out.get("host_permissions") or [])
    for pat in patterns:
        if pat and pat not in required:
            required.append(pat)
    if required:
        out["host_permissions"] = required
    return out


def pack(key: rsa.RSAPrivateKey, zip_bytes: bytes) -> tuple[bytes, str]:
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    crx_id = hashlib.sha256(spki).digest()[:16]
    signed_header_data = _field(1, crx_id)  # SignedData { bytes crx_id = 1; }
    to_sign = (
        b"CRX3 SignedData\x00"
        + struct.pack("<I", len(signed_header_data))
        + signed_header_data
        + zip_bytes
    )
    signature = key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
    proof = _field(1, spki) + _field(2, signature)  # AsymmetricKeyProof
    header = _field(2, proof) + _field(10000, signed_header_data)  # CrxFileHeader
    crx = b"Cr24" + struct.pack("<I", 3) + struct.pack("<I", len(header)) + header + zip_bytes
    return crx, extension_id(spki)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--key", required=True, type=Path)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--info", type=Path, help="write {id, version, name} as JSON here")
    ap.add_argument(
        "--host-permission",
        action="append",
        default=[],
        help="match pattern added as a required host permission in the packaged copy",
    )
    args = ap.parse_args()
    manifest = json.loads((args.src / "manifest.json").read_text())
    override = None
    if args.host_permission:
        manifest = with_host_permissions(manifest, args.host_permission)
        override = (json.dumps(manifest, indent=2) + "\n").encode()
    key = load_or_create_key(args.key)
    crx, ext_id = pack(key, zip_directory(args.src, override))
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    tmp.write_bytes(crx)
    os.replace(tmp, args.out)
    info = {
        "id": ext_id,
        "version": manifest.get("version"),
        "name": manifest.get("name"),
        "host_permissions": manifest.get("host_permissions", []),
    }
    if args.info:
        args.info.write_text(json.dumps(info, indent=2) + "\n")
    print(f"{args.out}: {len(crx)} bytes, extension id {ext_id}, version {info['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
