# 0007: Signed update metadata; no unattended installs by default

**Status:** Accepted

**Context:** Self-updating software is a prime supply-chain target, and
unattended updates can interrupt service.

**Decision:** Update metadata is signed by official keys and carries an
expiry (freeze protection) and a monotonic sequence (rollback protection).
It is fetched only over HTTPS. Artifacts are pinned by SHA-256. No remote
scripts are executed. Policies exist per component class. The defaults are
notify for Veyra, modules and templates, and manual for the engine and OS.
Download and unattended install modes are refused until the executor is
tested (M12). Upgrades take a backup, run migrations in one transaction and
roll back to the previous release if a migration fails.

**Consequences:** Strong integrity, at the cost of more release-engineering
work (key management, metadata publishing).
