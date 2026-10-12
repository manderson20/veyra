# Milestone 3: Completion Report

**Milestone:** 3 — Telephony engine integration (deployer service, configuration generation, ARI status, reload, rollback)
**Date:** 2026-10-12
**Branch:** `milestone-3` (pushed to `manderson20/veyra`; not merged to `main`)
**Status:** Complete. Awaiting the project owner's review.

## 1. Scope (approved 2026-10-12)

Per the roadmap: a deployer service, configuration generation from the
database, engine status over ARI, targeted reloads and rollback, against
Asterisk 22 on veyra-dev1 (and the Asterisk 20 feature set per ADR 0010).

## 2. Results

| Task | Result | Where |
|---|---|---|
| Configuration generation | Done. A pure function from a database snapshot to four files (PJSIP transports, endpoint templates and per-extension endpoints, dialplan with `*43`/`*60` feature codes and the internal and from-trunk contexts, RTP settings). Every value is validated against an allow-list; secrets mark a file sensitive. Deterministic, so "no change" is detected by hash. | `backend/veyra/telephony/asterisk/generator.py`, `snapshot.py` |
| SIP and media settings | Done. Validated settings document (`telephony.sip`) with an API and a form on the engine page; cross-field rules (RTP range, NAT addresses, local networks). | `backend/veyra/telephony/settings.py`, `/telephony/settings` |
| Revisions | Done. Generate → validated or failed; deploy request → deploying; discard; diffs with sensitive files masked; files and diffs for platform administrators only. | `backend/veyra/configmgmt/service.py`, `/telephony/revisions` |
| Deployer service | Done. `veyra-deployer` systemd unit (user `veyra`, sandboxed, one writable path): atomic 0640 writes into `/etc/asterisk/veyra`, removal of files no longer generated, targeted module reloads over ARI, post-reload verification, automatic restore of the previous files on any failure, audit of every outcome. | `veyra/cli/main.py` (`deployer`), `installer/templates/systemd/veyra-deployer.service.in` |
| Rollback | Done. Deploying a superseded revision again restores it; the newer one becomes `rolled_back`. | API, `veyra config deploy <n>` |
| ARI status | Done. Engine health, version, start and reload times, watched module status, endpoint and channel counts; `/system/health` reports real `registrations` and `active_calls`; the setup wizard shows the engine state. | `backend/veyra/telephony/asterisk/adapter.py`, `ari.py`, `/telephony/engine` |
| Engine page | Done. System → Telephony Engine: live status, configuration card (generate, preview diff, deploy, roll back, discard, deployment polling), revision history, SIP settings form. | `frontend/src/app/(app)/system/telephony/` |
| Installer | Done. Veyra-managed stub `pjsip.conf`, `extensions.conf`, `rtp.conf` (samples backed up), include directory `2750 veyra:asterisk`, deployer unit, verification checks; upgrades reload Asterisk only when managed files changed and never restart it. | `installer/lib/steps.sh`, `verify.sh`, `upgrade.sh` |
| Documentation | `docs/TELEPHONY_ENGINE.md` (new); architecture, networking, API, schema, installation, security, changelog updated. | `docs/` |

Also in this branch (not Milestone 3 scope): the AGPL-3.0-or-later license
decision (ADR 0013) with SPDX headers, and the record of the owner's
Milestone 2 decisions.

## 3. Testing (veyra-dev1, 2026-10-12, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (78 files) |
| Backend pytest against PostgreSQL 18.6 | **154 passed** (23 new: generator, settings, revision service and deployer, telephony API, CLI) |
| Frontend lint / typecheck / vitest | Clean / clean / **21 passed** |
| Frontend `npm run build` | Passed; `/system/telephony` exported |
| ShellCheck; installer helper tests | Clean; **29 passed** |
| `install.sh --dry-run --yes` on dev1 | Shows the stub installation, backups and directory ownership; no changes made |
| **Live against Asterisk 22.5.2 on dev1 (ARI):** adapter health, info, eight watched modules, targeted reload of `pbx_config.so` with the engine's last-reload time advancing, verification | Passed |
| **Live cycle with the real ARI and a scratch include directory:** `veyra config generate --deploy`, `veyra deployer --once` → deployed (four files, 0640); RTP settings change → revision with only `rtp.conf` changed → deployed with one reload; `veyra config deploy 2` → rolled back, file content restored | Passed (see §4 for what this does not prove) |
| Deployer failure path (no ARI credential) | Revision marked failed with the reason, files restored, audited |

What the new tests cover: deterministic and complete generation; NAT and
TLS rendering; endpoints and dialplan from extensions with the sensitive
flag; rejection of unsafe names, numbers, secrets and duplicates; static
validation of malformed files; minimal ordered reload scopes; settings
validators and cross-field problems; generate → deploy → supersede →
rollback with file modes and reload lists; failed verification restores
the previous files and the failed revision can never be queued; reload
failure and a missing directory; generation problems produce a failed
revision; one deployment at a time; engine status with and without an
engine; health counts; setup status; settings round trip, validation and
audit; the API flow including 409s for queued, engine-down and wrong-state
cases; organization administrators see metadata only; CLI commands.

## 4. Not verified

* **The deployer has not written to the real `/etc/asterisk/veyra` yet.**
  The installed instance runs the Milestone 2 release; the Asterisk stubs,
  the directory ownership and the deployer unit are installed by the next
  `upgrade.sh` run, which the owner performs. After that, the first
  deployment from the UI is the real end-to-end test and will be added to
  this report.
* No phone has registered (no extensions exist until Milestone 4), so
  `registrations` has only been observed as 0 and the generated endpoint
  templates have not carried real traffic.
* Asterisk 20 (Ubuntu 24.04 container) has not been exercised with the
  generated files; nothing generated uses syntax newer than Asterisk 20.
* The UI was not driven in a browser (no browser on the server).

## 5. Known limitations

* Dialplan contexts cannot be listed through ARI, so post-reload
  verification checks module status and ARI reachability; `sudo asterisk
  -rx "dialplan show veyra-internal"` is the manual check.
* Revision artifacts (including SIP secrets once extensions exist) are
  stored in clear in the database; Milestone 4 adds the installation key
  and will encrypt them.
* The deployer polls every two seconds rather than using LISTEN/NOTIFY.
* Channel durations are reported as 0 (ARI creation time is not yet
  converted); counts are correct.
* TLS transports reference the installer's self-signed certificate; a
  trusted certificate is Milestone 17.

## 6. Open items

* veyra-dev2 is not provisioned (deferred).
* First real deployment on dev1 after the owner's upgrade (§4).

## 7. Proposed Milestone 4 (for approval)

Extension management: the installation key and SIP secret encryption at
rest (also used to encrypt revision artifacts and, later, MFA secrets), the
numbering plan, extension CRUD with tenant scoping, generated endpoints and
dialplan from real extensions, and the Extensions UI. Milestone 4b (MFA)
follows it.
