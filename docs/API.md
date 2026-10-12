# API

The management API is versioned under `/api/v1`. The authoritative reference
is the generated OpenAPI document:

* `https://<server>/api/openapi.json`
* `https://<server>/api/docs` (interactive)

Conventions:

* **Authentication:** session cookie from `POST /api/v1/auth/login`. Mutations must send `X-CSRF-Token` with the value of the `veyra_csrf` cookie.
* **Errors:** RFC 9457 `application/problem+json`, with `code`, `detail`, `errors[] {field, message}` and `request_id` (also in the `X-Request-ID` header).
* **Lists:** `?limit=` (≤ 200) and `?offset=`, returning `{items, total, limit, offset}`; `?q=` search where supported.
* **Authorization:** enforced on every endpoint. Objects outside the caller's scope return 404.
* **Audit:** every mutation is recorded, including denied and failed attempts.
* **Forced password change:** while `must_change_password` is true in the session document, every route outside `/auth/` answers `403 password_change_required`.
* **Fetch metadata:** a mutation whose `Sec-Fetch-Site` header says `cross-site` or `same-site` is refused with `403 cross_site_request` before any handler runs; requests without the header fall through to the CSRF token check.

| Area | Paths |
|---|---|
| Auth | `/auth/login`, `/auth/logout`, `/auth/session`, `/auth/password`, `/auth/sessions[/{id}]`, `/auth/sessions/revoke-others`, `/auth/password-reset/check`, `/auth/password-reset` (the last two are public and rate limited) |
| Setup | `/setup/status`, `/setup/initialize` |
| Directory | `/organizations[/{id}]`, `/users[/{id}]`, `/users/{id}/roles[/{assignment}]`, `/users/{id}/unlock`, `/users/{id}/password-reset-link`, `/users/{id}/sessions`, `/roles`, `/search` |
| System | `/system/ping` (public), `/system/health`, `/system/info`, `/ha/status`, `/audit` |
| Modules | `/modules`, `/modules/ui-extensions`, `/modules/{id}`, `/modules/{id}/{install,enable,disable,update,uninstall}`, module routes under `/api/v1/ext/<prefix>/` |
| Updates | `/updates/policies[/{component}]`, `/updates/check`, `/updates/checks/latest`, `/updates/available`, `/updates/history` |
| Provisioning | `/provisioning/variables`, `/provisioning/templates[/{key}[/preview,/export]]`, `/provisioning/templates/{validate,import}` |
| Telephony | `/telephony/engine`, `/telephony/settings`, `/telephony/revisions[/{id}]`, `/telephony/revisions/{id}/{deploy,discard}` (see [TELEPHONY_ENGINE.md](TELEPHONY_ENGINE.md)) |

Planned (later milestones): `/extensions`, `/devices`, `/trunks`, `/routes`, and others.
