# Security

Veyra is in early development (Milestone 0) and is **not yet suitable for
production use**.

## Reporting a vulnerability

The repository is private during development. Report suspected
vulnerabilities privately to the project owner (GitHub: `manderson20`)
rather than in a public issue. A public disclosure policy and contact
address will be published before the first public release (Milestone 18).

## Security model summary

The full description is in [docs/ARCHITECTURE.md §6](docs/ARCHITECTURE.md#6-security-architecture).

| Area | Control |
|---|---|
| Passwords | Argon2id; minimum 12 characters; constant-time handling of unknown users |
| Sessions | Server-side, token hashes only; HttpOnly + Secure + SameSite=Strict cookies; 12 h absolute / 60 min idle |
| CSRF | Double-submit token checked against a per-session hash |
| Brute force | NGINX + API rate limits; account lockout |
| First run | One-time console-issued setup token; setup possible only while no user exists |
| Authorization | Scoped RBAC (platform / organization / site) enforced in the backend; platform-only permissions; last-admin protection |
| Tenant isolation | Scoped queries, with 404 for out-of-scope objects; telephony isolation validated before multi-tenancy is enabled (M14) |
| Audit | Append-only audit log enforced by a database trigger; secrets redacted; denied and failed attempts recorded |
| Secrets | No database password (peer authentication); generated ARI credential (0640); nothing secret in the repository or config files |
| Exposure | API, ARI and PostgreSQL on loopback only; AMI disabled; UI only on private addresses by default; checked by `verify.sh` |
| Services | Dedicated `veyra` account; systemd sandboxing; code is root-owned and read-only |
| Modules | Ed25519-signed packages; trust set by the local keyring; only official modules run in-process; integrity re-verified at load |
| Templates | Jinja2 sandbox with no globals; validated variables and filenames; XML auto-escaping; secrets masked and never exported |
| Updates | Signed metadata with expiry and rollback protection; HTTPS only; no remote scripts executed; no unattended installs by default |
| Supply chain | Pinned dependencies at least two weeks old; actions pinned by SHA; pip-audit, npm audit and gitleaks in CI |

## Known gaps (tracked)

* SIP credential encryption at rest arrives with extensions (M4).
* Multi-factor authentication and SSO (OIDC, Entra ID, Google) are not yet implemented.
* The isolated service runtime for community and third-party modules is not yet implemented, so such modules are refused.
* The rate limiter is per process. A shared limiter will come with HA.
* The CSP allows `'unsafe-inline'` scripts because Next.js static export inlines its bootstrap. Moving to hashed inline scripts is planned.
* No official release signing key or update server exists yet.
* Emergency calling is not configured and must not be relied on (see [docs/EMERGENCY_CALLING.md](docs/EMERGENCY_CALLING.md)).
