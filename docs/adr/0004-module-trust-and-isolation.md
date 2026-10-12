# 0004: Module trust and isolation

**Status:** Accepted

**Context:** Third parties must be able to extend Veyra, but arbitrary code
in the core process could read every secret and tenant's data.

**Decision:** Packages are signed with Ed25519 over a SHA256SUMS manifest.
The trust level comes from the local keyring directory holding the signer's
key. Only `official` modules run in-process. `community` and `third_party`
modules must use an isolated `service` runtime (planned); until it exists
they are refused. Unsigned modules load only in non-production environments
with an explicit setting. Module UI is declarative (manifest-described
views), with no JavaScript injection. The module API is versioned
(`MODULE_API_VERSION`), and each module has its own migration history.

**Consequences:** Strong integrity and isolation guarantees. Community
modules have to wait for the service runtime (M11), and rich custom UIs need
new declarative view types.
