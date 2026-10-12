# Security

Veyra is in early development (Milestone 2) and is **not yet suitable for
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
| Passwords | Argon2id; 12+ characters with weak-word and personal-information checks; constant-time handling of unknown users; administrator-set passwords are temporary |
| Password reset | One-time links (hashed, 24 h, single use) issued by an administrator or the server console; generic failures; rate limited; signs the account out everywhere |
| Sessions | Server-side, token hashes only; HttpOnly + Secure + SameSite=Strict cookies; 12 h absolute / 60 min idle; users and administrators can list and end sessions; expired rows purged after 30 days |
| CSRF | Double-submit token checked against a per-session hash, plus rejection of mutations the browser labels cross-site (fetch metadata) |
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
* Multi-factor authentication is designed ([docs/MFA_DESIGN.md](docs/MFA_DESIGN.md)) but not implemented; SSO (OIDC, Entra ID, Google) is not yet implemented.
* Self-service "forgot password" needs email delivery (Milestone 7); until then a reset link comes from an administrator or the server console.
* The isolated service runtime for community and third-party modules is not yet implemented, so such modules are refused.
* The rate limiter is per process. A shared limiter will come with HA.
* The CSP allows `'unsafe-inline'` scripts because Next.js static export inlines its bootstrap. Moving to hashed inline scripts is planned.
* No official release signing key or update server exists yet.
* Asterisk comes from Ubuntu's `universe` component (ADR 0010), which is maintained by the community and by Ubuntu Pro `esm-apps`, not by Ubuntu's main security team. Production hosts should enable `esm-apps` or track Asterisk advisories; the production hardening milestone (M17) covers this.
* Emergency calling is not configured and must not be relied on (see [docs/EMERGENCY_CALLING.md](docs/EMERGENCY_CALLING.md)).
