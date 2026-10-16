# 0013: Veyra is licensed under AGPL-3.0-or-later

**Status:** Accepted (2026-10-12). Supersedes [ADR 0009](0009-license-pending.md).

**Context:** The owner delegated the choice between the candidates in
[LICENSING.md](../LICENSING.md) (AGPL-3.0, Apache-2.0, or the GPL-3.0 file
the repository was created with). Veyra's stated goal is an open platform
that needs no cloud service or subscription, with MSPs and future hosted
deployments among its users.

**Decision:** AGPL-3.0-or-later. Its network clause keeps improvements
open when someone hosts a modified Veyra for others, which is the one case
GPL-3.0 does not cover and the one most likely for a telephony platform.
Apache-2.0 would allow closed hosted forks, which does not fit the goal.
All dependencies are compatible; Asterisk (GPLv2) is a separate program
controlled over ARI and generated files. Third-party modules in the
service runtime talk to the core over HTTP and may be proprietary.

**Consequences:** `LICENSE` holds the AGPL-3.0 text and sources carry SPDX
headers. Some organizations avoid AGPL software; the owner can revisit the
choice before the public release (Milestone 23) while the repository is
private, and a later ADR would supersede this one.
