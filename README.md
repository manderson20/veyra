# Veyra update feed

Signed update metadata read by every Veyra server (System → Updates).
This branch holds only the feed; the code lives on `main`.

| File | Purpose |
|---|---|
| `stable.json` | Releases on the stable channel: version, notes, service impact, and the download address, size and SHA-256 of each `veyra-<version>.tar.gz` (a GitHub release asset). |
| `stable.json.sig` | Detached Ed25519 signature by the official release key `veyra-official`. Servers accept the feed only when a key in `/etc/veyra/trust/official/` verifies it; the installer ships that public key. |

Servers fetch `https://raw.githubusercontent.com/manderson20/veyra/updates/stable.json`
and `…/stable.json.sig`. The metadata carries a sequence number (rollback
protection) and an expiry; `veyra release refresh` re-stamps and re-signs it
without a release. How a release is added: docs/SOFTWARE_UPDATES.md §1 on `main`.
