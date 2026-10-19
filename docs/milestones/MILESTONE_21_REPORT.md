# Milestone 21 Report — Provisioning breadth

Branch `milestone-21` (from `main` at 0.26.7). Design:
[PROVISIONING_BREADTH.md](../PROVISIONING_BREADTH.md). Status: **released as
0.27.0 on 2026-10-20, templates experimental until the hardware checks**.
Issues #76, #40, #35, #38, #39 under "M21 — Provisioning breadth"; #34
(hardware checks), #36 (Grandstream) and #37 (ATA) stay open; tracking #61.

## 1. Scope (roadmap row 21)

Official templates beyond the Poly VVX, more line-key types, a phone
directory, vendor redirect services, and a variable control plane that
templates reference so nothing shared is hard-coded (owner requirement
2026-10-18). Owner direction 2026-10-20: cover every model the vendors sell
today; end-of-life models still in production are added when named.

## 2. Results

| Slice | What an administrator gets | Where | Issue |
|---|---|---|---|
| A | Provisioning variables at installation, organization, site or profile scope, nearest wins; `{{ vars.name }}` in templates, `$name` on keys (one profile, each building's own all-call zone); same-named template settings filled; a change re-provisions the phones it reaches; resolved view per phone; preview warnings | Provisioning → Variables; device → Configuration | #76 |
| B | Key types Voicemail, Intercom, Do Not Disturb, Park (lot or slot), Toggle (call flow, time condition, queue log-in), Transfer, with lamps | Key editor on profiles and devices | #40 |
| C | Yealink: every current SIP model (T3x, T4x, T5x, T7x, T8x, CP conference phones); phone directory in Yealink, Poly, Grandstream and CSV formats | Templates; `/provisioning/directory/…` | #35 |
| E | Algo: every current SIP endpoint, with the checksum file Algo requires; multicast listen zones in RTP, Poly group paging or both | Templates | #38 |
| F | Poly Edge E (E100–E550) and CCX (350–700); Poly phones receive the directory; redirect services with per-vendor MAC export; hardware checklist | Templates; Provisioning page; docs/PROVISIONING_HARDWARE_CHECKS.md | #39, #34 |

Slice D (Grandstream and the ATA) was not built: neither is in the owner's
fleet; both stay on request (#36, #37). CyberData likewise (#38 comment).

### Platform pieces

* Table `provisioning_variables` (migration `0054`) and
  `veyra/provisioning/variables.py`; the `vars` fact; key values `$name`.
* Template spec: `checksum_of` files (MD5 of another rendered file);
  `ResolvedTemplate.features`; facts `server.directory_url`, `server.host`,
  `server.provisioning_path`; page keys carry the zone's multicast address.
* Generator: dialable DND and queue log-in lamp numbers on the owner's
  phone, `parkinghints=yes` on parking lots.
* Template "Customize" copies single-file and checksum families correctly.

## 3. Testing

Backend: `test_provisioning_variables.py` (scopes, precedence, key
references, re-provision, in-use refusal, key types),
`test_provisioning_yealink.py` (render, lineup, conference phone, Edge E,
CCX, directories, export), `test_provisioning_algo.py` (render and the
served checksum matching the served file); full suite 587 passed; ruff,
format, mypy clean. Frontend: typecheck, lint, vitest.

### Not verified

No new template has run on a device: lamp behaviour of the new key types,
Yealink and Algo parameter acceptance, Poly Edge E and CCX, the directory on
phones, Asterisk loading the new dialplan lines and parking hints. The
checklist in docs/PROVISIONING_HARDWARE_CHECKS.md is the way to verify; a
passed run moves a family to `stable`.

## 4. Known limitations

Edge V (format not published), Grandstream, the ATA, CyberData, DECT and
Wi-Fi Yealink models, AND clocks (not SIP-provisioned), zone addresses as
variables and the Companion export of variables, per-queue log-in toggles,
the Algo web admin password (parameter undocumented), expansion modules and
hot desking (P2).

## 5. Next

The owner's end-of-life models added to their families; the hardware runs;
Milestone 22 — adoption and operations.
