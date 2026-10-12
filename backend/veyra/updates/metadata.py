"""Signed update metadata.

The update source publishes ``<url>`` (JSON) and ``<url>.sig`` (detached
Ed25519 signature document, see ``veyra.core.signing``). Only keys in the
*official* trust directory may sign update metadata.

Protections:
* authenticity — signature by an official key
* freshness — ``expires_at`` must be in the future (prevents freeze attacks)
* rollback — ``sequence`` must not go backwards (prevents replay of old metadata)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from veyra.core.models.base import utcnow
from veyra.core.semver import Version
from veyra.core.signing import Keyring, SignatureError, TrustLevel, verify
from veyra.updates.policy import Channel, Component


class MetadataError(ValueError):
    pass


class Artifact(BaseModel):
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0)


class Release(BaseModel):
    component: Component
    target: str = Field(description="'veyra' for core, otherwise a module or template id")
    version: str
    channel: Channel
    category: Literal["security", "bugfix", "feature"]
    release_notes: str = ""
    service_impact: str = Field("", description="Expected service impact shown before approval")
    min_from_version: str | None = None
    artifact: Artifact | None = None

    @field_validator("version", "min_from_version")
    @classmethod
    def _semver(cls, v: str | None) -> str | None:
        if v is not None:
            Version.parse(v)
        return v


class UpdateMetadata(BaseModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    generated_at: datetime
    expires_at: datetime
    releases: list[Release] = Field(default_factory=list)


def verify_metadata(
    body: bytes,
    signature_doc: str,
    keyring: Keyring,
    *,
    last_sequence: int = 0,
    now: datetime | None = None,
) -> UpdateMetadata:
    try:
        key = verify(body, signature_doc, keyring)
    except SignatureError as e:
        raise MetadataError(f"Update metadata signature invalid: {e}") from e
    if key.trust_level != TrustLevel.OFFICIAL:
        raise MetadataError("Update metadata must be signed by an official key")
    try:
        meta = UpdateMetadata.model_validate_json(body)
    except ValidationError as e:
        raise MetadataError(f"Update metadata is malformed: {e.error_count()} error(s)") from e
    if meta.expires_at <= (now or utcnow()):
        raise MetadataError("Update metadata has expired")
    if meta.sequence < last_sequence:
        raise MetadataError(
            f"Update metadata sequence {meta.sequence} is older than "
            f"the last seen ({last_sequence})"
        )
    return meta
