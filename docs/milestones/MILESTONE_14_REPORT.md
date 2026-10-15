# Milestone 14 Report — Multi-Tenancy

Branch `milestone-14` (from `milestone-13` at 0.19.0). Design:
[MULTI_TENANCY.md](../MULTI_TENANCY.md). Status: **approved 2026-10-15, released as 0.20.0.**

## 1. Scope (roadmap row 14)

Telephony isolation between organizations, the tests that prove it, and
activation only after they pass.

## 2. Results

* **Engine namespaces** (migration `0027`):
  * Every organization has `engine_namespace`. The organization that existed before keeps the empty namespace, which means today's names.
  * Other organizations get `veyra_<ns>-…` names for:
    * contexts: phone, features, paging, page playback, outbound, IVR, ring group, queue;
    * the voicemail context (`veyra_<ns>`) and queue names;
    * hold music classes and folders (`<moh>/<ns>_<slug>`), and pickup group names (`<ns>_<slug>`).
  * No name of one organization can equal another's: today's names never contain `_`, and a namespace never contains `-`.
  * All names come from one place, `telephony/asterisk/names.py`.
* **Generator:**
  * Each section is generated per namespace, in the same order as before.
  * Endpoints of other namespaces get their own `context=`.
  * `voicemail.conf` has one section per voicemail context, and `queues.conf` takes only the queue's own organization's phones.
  * Inbound DIDs go to the route's organization's contexts. Outbound route contexts stay shared; each organization's outbound context includes only the routes that apply to it.
* **Isolation verifier** (`telephony/asterisk/isolation.py`):
  * Reads the generated `extensions.conf`, `pjsip.endpoints.conf` and `queues.conf`.
  * Checks: phone contexts, mailbox lamps, pickup groups; every include, `Goto`, `Dial(PJSIP/…)`, `VoiceMail`, `Queue` and context name from an organization's contexts; outbound route contexts reach no organization; each DID reaches one organization; queue members belong to the queue's organization.
  * Runs inside `generate()` whenever more than one namespace exists, or the switch is on. A failure stops the revision.
* **Numbers per organization:**
  * Unique keys moved from the installation to (`organization_id`, `number`) for ring groups, queues, paging zones, pages and shared inboxes.
  * The advisory lock and `number_owner` work per organization, and `/extensions/next-number` takes `organization_id`.
  * Slugs stay unique across the installation, so a second organization's "Office" gets `office-2`. That is harmless, because the namespaces keep the engine names apart.
* **Activation** (`/system/multi-tenancy`, System → Settings card):
  * Turning it on runs two checks. *namespaces*: every organization has its own. *isolation*: the current configuration plus a twin of the first organization, with the same numbers, generated and verified.
  * Turning it off needs one active organization.
  * While it is off, a second active organization answers `409 multi_tenancy_disabled`, both when creating one and when reactivating one.
* **Shared parts:**
  * Outbound routes have an optional organization ("Used by"); without one they serve every organization.
  * Trunks, DIDs (one organization each), the numbering plan, SMTP, the firewall, updates, modules and sign-in stay installation-wide. The card lists them.
* **Call data:** while multi-tenancy is on, the dashboard graphs and the active-call and registration counts are for platform administrators only.
* **Paging:** a zone that shares its multicast group with another organization's zone is flagged.
* **Reporting:** the call history and queue reports recognise queue and ring group names in any namespace. Queue log rows of a namespaced queue are keyed `<ns>_<slug>`.
* **Interface:**
  * Multi-tenancy card with the checks and the shared list.
  * An "Engine names" column and the right warning on Organizations.
  * "Used by" on outbound routes; numbers are suggested per organization.
  * Settings no longer lists single sign-on under "Coming later".

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (180 files) |
| Backend pytest | **409 passed**. M14 added 18 tests: name builders and parsers; namespace derivation; one organization unchanged; two organizations with identical numbers, slugs and names isolated; 8 hand-made leaks caught (include, `Goto`, `Dial`, `VoiceMail`, `Queue`, phone context, mailbox lamp, queue member); outbound route leak and strict mode; outbound routes per organization and inbound DID destinations; the switch (refusal, checks, turning off, reactivation); numbers and `next-number` per organization; the outbound route field; an organization administrator seeing only their own organization and no installation-wide graphs; migration defaults. 13 existing tests turn the switch on before creating a second organization, and one rewritten test now expects the same number in two organizations |
| `alembic check` | No drift (migration `0027`, down and up again) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **43 passed** / passed |
| Installer library tests | **52 passed** |
| **Owner's `upgrade.sh` on dev1** | 0.19.0-203f47f524 → **0.19.0-782ee5d919** (15:40 UTC: schema `0027`, all checks OK) |

### Checks on dev1 (read-only, 15:42 UTC)

| Check | Result |
|---|---|
| Old and new generator on dev1's data, before the upgrade | All 10 files byte-identical |
| Migration | dev1's organization has the empty namespace; multi-tenancy off |
| Activation checks with dev1's configuration and its twin | *namespaces* passed; *isolation* passed. The twin got its own `veyra_zzcheck-internal`, `-features`, `-paging`, `-page-play`, `-outbound` and `-ivr-m7-test-menu` |
| Generated against deployed files | 9 identical. `voicemail.conf` differs only by M13's `externnotify` line, which dev1 gets with its next deployment |

## 4. Not verified

* **Calls between two real organizations on dev1:** turning the switch on, a temporary second organization, ARI Local channels in both directions. This waits for your agreement (it changes dev1 for a few minutes); the generated configuration and the verifier are covered by the tests and the twin check above.
* Browser checks: the Multi-tenancy card, Organizations, and "Used by" on outbound routes.

## 5. Known limitations

* **Calls in progress:** turning an existing organization's names into a namespace is not possible (by design, §8 of the design). Calls in progress in a context removed by a deployment fail at their next step; deploy "when idle" avoids this.
* Organizations administrators see installation-wide data only where it is
  marked shared; per-organization dashboard graphs, SMTP, numbering plans,
  firewall rules and sign-in providers are later steps.
* PostgreSQL row-level security is proposed for M17 (§10 question 2).

## 6. Open items

* MULTI_TENANCY.md §10:
  1. What is multi-tenancy for in your case: other districts on one server, or buildings (which sites already cover)?
  2. Can row-level security wait until M17?
  3. Should outbound routes be shared by default, with an optional organization?
  4. Should trunks stay installation-wide?
* Agreement for the live two-organization test on dev1 (§4).
* Earlier open items are unchanged; see the M13 report §6.

## 7. Next milestone

Roadmap row 15: centralized instance management (0.21.0).

## 8. Owner decisions

* 2026-10-15: milestone started ("go ahead with M14"); built with the
  proposed defaults while the §10 questions are open.
* 2026-10-15: approved ("M14 approved, go ahead with 0.20.0"); the §10
  questions and the live two-organization test remain open.

## Addendum (2026-10-15 15:46 UTC): 0.20.0 on dev1

The owner upgraded dev1 from the M14 test build (0.19.0-782ee5d919) to the
release build **0.20.0-80aec092b7** from `~/veyra-release` (dry run first,
then the real run): backups taken, schema current (`0027`), all verify
checks OK (`catalog-trust` warns, as expected without a catalog key).
Multi-tenancy stays off.

The owner also confirmed the intended behaviour: organizations never dial
each other's extensions; one organization reaches another only through its
external number, like any outside call (out through a trunk and back in on
the other organization's DID). A future on-net shortcut for such calls was
offered, not requested.
