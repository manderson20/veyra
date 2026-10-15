# Centralized Instance Management (Milestone 15)

Design for Milestone 15 (roadmap row 15, 0.21.0). It lets one Veyra
installation, the **central console**, see and steer many Veyra
installations (**instances**). Examples are the servers of several districts
run by one team, or a district with a server per region. ARCHITECTURE.md §3
fixes the ground rules:
* the mode is data, never a different build;
* `installation.instance_id` is the permanent identity;
* **an instance keeps working when the central console is unreachable.**

## 1. Principles

1. **Same build.** Any installation can turn on the central console under
   System → Central console. Any installation can enroll as an instance.
   One installation can be both (the console can manage itself).
2. **Instances call out; the console never calls in.** An instance sends
   a signed check-in every minute, and the answer carries what the console
   wants. Instances can sit behind NAT and firewalls with no inbound port.
3. **No remote shell, no secrets.** The console cannot run arbitrary
   commands, read SIP secrets, PINs, recordings or call records. It cannot
   create extensions or change the dialplan. Everything it can do is a
   fixed list of settings and actions (§4, §5), each of which the local
   administrator can refuse.
4. **Signed both ways.** Each instance has its own Ed25519 key and so does
   the console:
   * every check-in is signed by the instance;
   * every answer is signed by the console;
   * timestamps and nonces stop replays.
5. **Offline is normal.** An instance that cannot reach the console keeps
   its last applied settings and simply reports later. The console shows
   it as "not seen since …" and alerts after a threshold.

## 2. Enrollment

1. On the console, *Add instance* creates an **enrollment token**:
   * single use, valid 24 hours;
   * shown once, with the console's address and the fingerprint of the
     console's signing key;
   * optionally gets a label ("North district") and a policy (§4).
2. On the instance, System → Central management → *Enroll* takes the
   console address, the token and the fingerprint. The instance creates its
   Ed25519 key pair (private key stored encrypted with the installation key)
   and sends:
   * its `instance_id`, name, version and public key;
   * a proof that it holds the token.
3. The console checks the token and stores the instance, then answers with
   its own public key. The instance pins that key: if it does not match the
   fingerprint typed in step 2, enrollment stops.
4. Both sides audit the enrollment. The token is spent.

**Leaving:**
* The instance can **leave** at any time: it deletes its key and the
  console's key and stops checking in.
* The console can **revoke** an instance: its next check-in is refused and
  it shows "Revoked by the central console".

Re-enrolling needs a new token.

## 3. Check-in (every 60 seconds, by the worker)

`POST <console>/api/v1/central/check-in`, with headers
`Veyra-Instance: <instance_id>`, `Veyra-Timestamp`, `Veyra-Nonce` and
`Veyra-Signature: ed25519(<method> <path>\n<timestamp>\n<nonce>\n<sha256(body)>)`.
The body is a **report**:

| Section | Content |
|---|---|
| identity | name, version, revision, deployment mode, multi-tenancy on/off, uptime |
| health | overall status and each component's status and message (as System → Health) |
| telephony | engine state; counts of organizations, extensions, phones registered, active calls, trunks up/down |
| alerts | open monitoring alerts (rule, subject, since) |
| updates | installed version, available updates with category, last check, state of a running install |
| security | firewall on/off, active bans, failed sign-ins in the last hour |
| modules | installed modules, versions and states |
| policy | version of the last applied policy, per-section result |
| commands | results of the commands received since the last check-in |

Nothing in the report is a secret or a call record. Counts are numbers,
not lists of people. The console keeps the latest report per instance and
a sample of the counts every 5 minutes for 30 days (for its graphs).

The console's answer is signed and carries:
* `policy`: the instance's current policy document, only when its version
  changed;
* `commands`: pending commands (§5);
* `next_check_in`: the interval.

Requests older than 5 minutes, or with a nonce the console has already
seen, are refused.

## 4. Policies

A **policy** is a named document on the console assigned to instances. One
policy per instance; new instances get the default policy. Version 1 can
carry these sections. Each is optional, and an absent section means "leave
local":

| Section | What it sets on the instance |
|---|---|
| `updates` | Veyra update policy (mode, channel, categories, maintenance window) and update source (URL, recipients; never the token, which stays local) |
| `firewall_allow` | Allow-list entries the firewall never bans (e.g. the console's own address, a management network), tagged "central" |
| `alert_recipients` | E-mail recipients for monitoring alerts |
| `notice` | A text banner shown to administrators on the instance ("Maintenance Saturday 6–8") |

**The local administrator decides.** System → Central management has a
switch per section, "Accept from the console", all on by default. A setting
from the console is shown read-only with "Managed by <console name>". When a
section is switched off, the instance keeps its own value and reports
"refused" for that section.

The instance applies a policy all at once per section, audits it (actor
"Central console <name>"), and reports the result.

## 5. Commands

One-shot actions queued on the console and delivered with the next answer.
Each has an id and a 24-hour expiry. The instance reports the result once.

| Command | Effect |
|---|---|
| `check_updates` | Run the update check now |
| `download_update` | Download a given version (signed release, as System → Updates) |
| `approve_update` | Approve a downloaded version: `now` or `window`. The instance's own rules still apply: no calls in progress for "window", and the signed release and its checks |
| `refresh_catalogs` | Refresh the module catalogs |

Each command can also be switched off locally ("Accept commands"). The
instance refuses unknown command names. There is deliberately no
"run", "restart", "deploy" or "change configuration".

## 6. The console

* **Instances**: one row per instance:
  * label and name, version, status (online, not seen since, revoked);
  * health, open alerts, phones registered and active calls;
  * update available, policy state.
  * Filters: label, status, version.
* **Instance page**:
  * the last report in full;
  * graphs of registrations and calls (30 days);
  * the policy and its per-section result;
  * commands with their results;
  * "Open instance" (a link to its web interface; sign-in stays per
    instance, and SSO makes it seamless);
  * revoke.
* **Policies**: create and edit, see which instances use each, set the
  default.
* **Enrollment tokens**: create (shown once), list unused ones, cancel.
* **Alerts**:
  * an instance not seen for 10 minutes (configurable);
  * an instance whose health is failed;
  * an instance whose update failed.
  They go to the console's monitoring alerts, so its e-mail recipients get
  them.
* **Actions on several instances**: "Check for updates", "Approve update
  0.x in their window".

Permissions: `central.read` and `central.write` (platform administrators
of the console installation).

## 7. Data

* **Console:**
  * `central_instances`: instance_id, label, name, public key, policy_id,
    status, enrolled_at, last_seen_at, last_report (JSONB), revoked_at;
  * `central_samples`: instance, time, counts;
  * `central_policies`: name, document (JSONB), version, is_default;
  * `central_commands`: instance, kind, arguments, created_by,
    expires_at, delivered_at, result;
  * `central_enrollment_tokens`: hash, label, policy, expires_at, used_at;
  * `central_nonces`: pruned after 10 minutes.
* **Instance:** a `system_settings` entry `central.membership`:
  * the console URL;
  * the console's public key;
  * our encrypted private key;
  * accepted sections and commands;
  * the last policy and its version;
  * last contact and last error.
* Installation flag `central_management_enabled` (exists, unused so far):
  true while enrolled.

## 8. Security notes

* The console cannot reach anything the policy and command lists do not
  name, and the instance checks every value as if a local administrator
  had typed it (same validators).
* A stolen console key could push the four sections and the four commands
  to the instances that accept them. It still could not change dialplans,
  read data or run code; firewall entries from the console only *allow*.
  Rotating the console key re-signs future answers; the instances learn
  the new key through an answer signed by the old one.
* A stolen instance key lets someone report false data for that instance
  only. Revoke it, then re-enroll.
* The console is an ordinary Veyra installation. Its own exposure rules
  (NGINX on private addresses unless `--allow-public-admin`) apply. To
  manage instances across the internet, the console's `/api/v1/central/`
  path must be reachable; it is rate-limited and needs a valid signature
  before doing any work.

## 9. Interface on the instance

System → Central management:
* the state (not enrolled, enrolled with <console> since …, last contact,
  last error);
* *Enroll* (address, token, fingerprint) and *Leave*;
* the accepted sections and commands;
* the applied policy;
* the log of commands received.

## 10. Testing

* **Unit:** request and answer signatures, replay refusal, policy
  validation, each section's apply, refused sections, unknown commands.
* **API:** a console and an instance as two apps in one test (the
  instance's HTTP client routed to the console app):
  * enrollment with a wrong token, an expired token, a wrong fingerprint,
    and success;
  * check-in, report stored, policy delivered and applied;
  * a section refused locally;
  * commands delivered once, with results;
  * revoke, leave;
  * the console offline (the instance keeps its settings);
  * permission checks.
* **Live on dev1:** dev1 as console and as its own instance:
  1. enroll;
  2. check-ins every minute;
  3. a policy with a notice and an alert recipient;
  4. `check_updates`;
  5. revoke;
  6. leave.

  Afterwards the console is switched off again.

## 11. Open questions for the owner

1. **Do you have, or expect, more than one Veyra server?** Which one would
   be the console: a separate small server, or one of the phone servers?
2. **Which settings should the console manage first?** The proposal: the
   update policy and window, firewall allow-list, alert recipients, and a
   notice.
3. **Should approving updates from the console be allowed**, or only
   checking and downloading?
4. **The default for new instances:** accept every section (proposed), or
   accept nothing until the local administrator opts in?

## 12. Out of scope

Pushing configuration such as extensions, routes or templates between
instances; copying users; a single sign-on bridge from the console into
instances; central call history or recordings; backups (Milestone 17);
high availability (Milestone 16); a console that is not itself a Veyra
installation.
