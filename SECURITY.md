# Security

Veyra is in development (Milestone 17, production hardening); the latest
review is [docs/SECURITY_REVIEW_2026.md](docs/SECURITY_REVIEW_2026.md).

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
| Sessions | Server-side, token hashes only; `__Host-` HttpOnly + Secure + SameSite=Strict cookies; 12 h absolute / 60 min idle; users and administrators can list and end sessions; expired rows purged after 30 days |
| Two-factor authentication | TOTP (RFC 6238) with single-use Argon2id-hashed recovery codes; per-role policy with an enrolment grace window (administrators required by default); a 5-minute pre-authentication session that can reach only the MFA routes; replay protection; lockout after five wrong codes; secrets encrypted with the installation key; administrator and console resets, all audited |
| CSRF | Double-submit token checked against a per-session hash, plus rejection of mutations the browser labels cross-site (fetch metadata) |
| Brute force | NGINX + API rate limits per address and per account; account lockout |
| First run | One-time console-issued setup token; setup possible only while no user exists |
| Authorization | Scoped RBAC (platform / organization / site) enforced in the backend; platform-only permissions; last-admin protection |
| Tenant isolation | Scoped queries, with 404 for out-of-scope objects; telephony isolation validated before multi-tenancy is enabled (M14) |
| Audit | Append-only audit log enforced by a database trigger; secrets redacted; denied and failed attempts recorded |
| Secrets | No database password (peer authentication); generated ARI credential (0640); nothing secret in the repository or config files; SIP secrets, MFA secrets, trunk and provisioning credentials, integration secrets and sensitive revision files encrypted at rest with the installation key (AES-256-GCM, purpose-bound, key outside the database, ADR 0014); `sudo veyra installation-key rotate` re-encrypts everything to a new key in one transaction (M17); secrets generated server-side, revealed only through audited endpoints, rotatable |
| Exposure | API, ARI and PostgreSQL on loopback only; AMI disabled; UI only on private addresses by default; checked by `verify.sh` |
| Services | Dedicated `veyra` account; systemd sandboxing; code is root-owned and read-only; only the deployer unit may write under `/etc/asterisk/veyra` |
| Engine configuration | Generated from the database by a pure function with allow-list validation of every value; targeted reloads over loopback ARI; failed deployments restore the previous files; rollback by redeploying |
| Modules | Ed25519-signed packages; trust set by the local keyring; only official modules run in-process; integrity re-verified at load |
| Templates | Jinja2 sandbox with no globals; validated variables and filenames; XML auto-escaping; secrets masked and never exported |
| Updates | Signed metadata with expiry and rollback protection; HTTPS only; no remote scripts executed; no unattended installs by default |
| Supply chain | Pinned dependencies at least two weeks old; actions pinned by SHA; pip-audit, npm audit and gitleaks in CI |

## Known gaps (tracked)

* Passkeys (WebAuthn) and "remember this browser" are not implemented ([docs/MFA_DESIGN.md](docs/MFA_DESIGN.md)); SSO (OIDC, Entra ID, Google) is not yet implemented.
* Self-service "forgot password" needs email delivery (Milestone 7); until then a reset link comes from an administrator or the server console.
* The isolated service runtime for community and third-party modules is not yet implemented, so such modules are refused.
* The rate limiter is per process (one API process per node; an HA standby answers reads only).
* The CSP allows `'unsafe-inline'` styles (scripts are allowed by hash since Milestone 17; see [docs/SECURITY_REVIEW_2026.md](docs/SECURITY_REVIEW_2026.md)).
* No official release signing key or update server exists yet.
* Asterisk comes from Ubuntu's `universe` component (ADR 0010), maintained by the community and by Ubuntu Pro `esm-apps`; `preflight.sh` and `verify.sh` warn when `esm-apps` is not attached.
* Emergency calling: Veyra reports readiness per site against its own checks; the operator validates with the carrier (see [docs/EMERGENCY_CALLING.md](docs/EMERGENCY_CALLING.md)).

## Dependency audit exceptions

| Since | Finding | Why it is accepted | Review |
|---|---|---|---|
| 2026-10-18 | `braces` ≤ 3.0.3 ([GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), stack exhaustion on deeply nested brace patterns; no fixed release exists, 3.0.3 is the latest). Reached only through `eslint-config-next → @next/eslint-plugin-next → fast-glob → micromatch` in `frontend/package-lock.json` | Development-only: the linter expands patterns from this repository's own configuration on a developer's machine or in CI. The package is not in the built web interface and the server runs no Node.js. `npm audit --omit=dev` in CI does not report it | When a fixed `braces` or a `fast-glob` without it is published, or with the next `eslint-config-next` update |
