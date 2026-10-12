# Architecture Decision Records

| # | Decision | Status |
|---|---|---|
| [0001](0001-telephony-engine-asterisk.md) | Asterisk as the initial telephony engine | Accepted |
| [0002](0002-static-frontend.md) | Static Next.js export served by NGINX | Accepted |
| [0003](0003-database-authoritative-config.md) | Database-authoritative configuration with generated engine files and a separate deployer | Accepted |
| [0004](0004-module-trust-and-isolation.md) | Signed modules; only official modules in-process; declarative UI extensions | Accepted |
| [0005](0005-server-side-sessions.md) | Server-side sessions with cookies and CSRF tokens instead of JWT | Accepted |
| [0006](0006-ha-active-passive-manual.md) | Active/passive HA with manual failover until fencing/quorum are tested | Accepted |
| [0007](0007-signed-update-metadata.md) | Signed, expiring, sequence-numbered update metadata; no unattended installs by default | Accepted |
| [0008](0008-sync-sqlalchemy-psycopg.md) | Synchronous SQLAlchemy with psycopg 3 and peer authentication | Accepted |
| [0009](0009-license-pending.md) | License choice deferred to the project owner | Proposed |
| [0010](0010-asterisk-ubuntu-packages.md) | Asterisk from the Ubuntu archive, not a Veyra-built package | Accepted |
| [0011](0011-password-reset-links.md) | Password reset by administrator- and console-issued one-time links; administrator-set passwords are temporary | Accepted |
| [0012](0012-mfa-approach.md) | MFA: TOTP with recovery codes first, passkeys second, pre-auth session at sign-in | Accepted design |

Format: Context, Decision, Consequences. Records are not edited once they
are accepted; a later ADR supersedes them instead.
