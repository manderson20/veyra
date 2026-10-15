# Milestone 9d Report — Firewall and Phone Trust

Branch `milestone-9d` (from `main` at 0.13.0, with 0.13.1 merged). Design:
[FIREWALL_TRUST.md](../FIREWALL_TRUST.md). Status: **built and checked
live on dev1, awaiting the owner's approval** (to be released as 0.14.0).

## 1. Scope (owner requests of 2026-10-14)

* Something better than fail2ban: block and allow addresses and networks
  from the interface, automatic timed bans for attackers.
* A **permanent allow list** (local networks, trunks) that bans never
  override, so a misconfigured phone on the LAN cannot lock itself out
  while remote attackers are blocked.
* A page showing bans and the events behind them; optional CrowdSec.
* Phones that trust the server through provisioning, without anyone
  installing a certificate by hand.

## 2. Results

* **Firewall** (System → Security → Firewall): Veyra's own nftables table
  `inet veyra`, applied atomically by the new `veyra-firewall` service,
  which runs as the service account with `CAP_NET_ADMIN` only and never
  touches other tables (dev1's LXD table is untouched). It only drops
  traffic; the allow list is checked first.
  * **Automatic bans** from the Asterisk security log (unknown accounts,
    wrong SIP passwords), failed sign-ins and second factors, refused
    provisioning and NGINX rate limiting: weighted points per address in a
    window (default 10 points in 10 minutes), first ban 1 hour, doubling on
    repeats up to 7 days. Bans carry a kernel timeout, so they end even if
    Veyra is stopped.
  * **Allow list**: this server's addresses, the SIP local networks and
    trunk addresses are added and kept current automatically; your own
    entries on top. Allowed addresses are never banned; their events are
    marked "would have been banned", which is how a misconfigured phone
    shows up.
  * **Block list** for every service or chosen ones (SIP, call audio, web
    and provisioning, SSH), optionally expiring.
  * **Per-service policy** "only the allow list", applied and undone
    automatically after 60 seconds unless confirmed in the browser.
  * **Blocklist feeds**: CrowdSec's local API (Veyra as a bouncer) or HTTPS
    address lists such as Spamhaus DROP.
  * The API refuses a change that would cut off the administrator making it
    (`firewall_self_block`). The firewall is **off** after the upgrade.
  * Console recovery: `sudo veyra firewall off`.
* **Phone trust**: the installer creates a **Veyra certificate authority**
  (limited to the server's host names) that issues the HTTPS certificate.
  Plain-HTTP provisioning now serves only a **bootstrap**, the CA and the
  HTTPS address, no secrets, to the bootstrap networks; a new Poly phone
  installs the CA, reboots and provisions over HTTPS, where it gets its SIP
  password and its own credential. Once a phone has used HTTPS, plain HTTP
  is refused for it ("Allow bootstrap again" after a factory reset). Per
  organization, the bootstrap may also carry the enrollment credential
  (nothing typed on a staging VLAN). Browsers trust Veyra once
  `https://<host>/downloads/veyra-ca.crt` is installed.
* Migration `0018`; 0.13.1's column flyouts are included.

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (146 files) |
| Backend pytest | **342 passed** (9d added 20: ruleset rendering incl. IPv6, overlap merging and per-service rules; Asterisk security log lines captured on dev1; scoring with counts; ban doubling; feed parsing; log rotation; the service pass against a fake nft: ban, lift, allow-list precedence, automatic entries, confirm-or-revert, off; API guards; bootstrap content, networks, downgrade protection, credential choice) |
| `alembic check` | No drift (migration `0018`, upgrade and downgrade) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **36 passed** / passed |
| Installer library tests | **46 passed** |
| Rendered ruleset | Accepted by `nft -c` |
| Service sandbox | Transient unit with the same restrictions: `nft` works with `CAP_NET_ADMIN`, refused without |
| **Owner's `upgrade.sh` on dev1** | 0.13.1-065968866c → **0.13.1-cfee0d76f7** (2026-10-15 01:56 UTC): migration `0018`, Veyra CA created and the self-signed certificate replaced, `logger.conf` managed (original backed up, Asterisk reloaded), `veyra-firewall` running, all verify checks OK incl. `security-log`, `tls-ca`, `tls-ca-key`, `tls-ca-public`, `firewall-dir`, `firewall-table` (off) |

### Live checks on dev1 (2026-10-15 01:58–02:05 UTC)

| Check | Result |
|---|---|
| Security log format | Measured before the build (temporary logger channel, removed afterwards): unknown account → `InvalidAccountID` plus `ChallengeResponseFailed` with `<unknown>` per attempt; a looping client wrote 62 000 lines in 6 s → events counted per pass |
| Firewall on | Table `inet veyra` applied next to LXD's; allow list filled with the server's five addresses |
| Attack from an LXD container (10.227.92.10, unknown account, 6 s) | Banned in the first pass for 1 hour (score 5502); 3404 attempts stored as 2 rows; `ban4` element with kernel timeout |
| While banned | 0 new security log lines from the container; its TCP connection to 443 dropped; dev1 itself unaffected |
| Lift | Element removed within one pass; container reaches 443 again |
| Allow list wins | Container on the allow list: about 20 000 attempts, no ban, every event marked "would have been banned" |
| Bootstrap without networks (dev1 has no SIP local networks) | 403 |
| Bootstrap with 172.16.0.0/21 | Master 200 naming `veyra-bootstrap-<MAC>.cfg`; config 1196 bytes with the CA, `serverType=3`, `serverName=veyra-dev1/provisioning/`, no password, no line settings; the CA in it is byte-identical to the installed one; dev1's HTTPS verifies with that CA alone (`Verify return code: 0`) |
| Other file over HTTP / address outside the networks | 404 / 403 |
| `sudo veyra firewall off` | **Bug found and fixed** (764cdac): the database part worked but the table removal ran as the service account and was refused (the running service removed the table on its next pass). The wrapper now removes the table as root; checked with the service stopped: table removed |
| Cleanup | Firewall off, test rule, ban and events deleted, bootstrap networks reset, container stopped |

## 4. Not verified

* **With a real phone**: a factory-reset Poly VVX taking the bootstrap,
  accepting a CA with a name constraint, and registering over HTTPS. The
  Poly parameter names come from the UC Software administrator guide.
* CrowdSec against a real CrowdSec installation (the decision stream
  format is covered by tests).

## 5. Known limitations

* The bootstrap is Poly only; other brands get 404 over plain HTTP until
  their templates add it.
* Bans are per server; with high availability (M16) each node will apply
  its own table from the shared database.
* The CA's name constraint lists today's host names; a new host name
  needs a new CA (a public certificate makes that moot).
* SIP over TLS with the Veyra CA is a natural follow-up, not in this
  milestone.

## 6. Open items

* **Owner: install the CA in your browser** (`https://veyra-dev1/downloads/veyra-ca.crt`,
  import as a trusted root), or push it with Google Admin; the Companion
  extension needs it since the certificate changed.
* **Owner: the six questions of [FIREWALL_TRUST.md](../FIREWALL_TRUST.md) §11**
  (local networks, SSH, CrowdSec, ban defaults, bootstrap credential,
  public certificate). dev1 has **no SIP local networks** set, so the
  automatic allow list holds only the server and the bootstrap is refused
  until networks are entered (System → Telephony Engine, or the
  bootstrap networks under System → Firewall → Settings).
* **Owner: phone check**: `VEYRA_PROVISIONING_HTTP=1` in
  `/etc/veyra/installer.conf`, re-run the upgrade, set the bootstrap
  networks, point DHCP option 66/160 on the voice VLAN at
  `http://veyra-dev1/provisioning/`, factory-reset a VVX.
* From 9c and earlier: the AND clock and Poly paging captures, the
  hardware checks of Milestones 5, 7, 8 and 9.

## 7. Next milestone

Milestone 10 — Reporting and monitoring: call detail records (the Call
History and Call Recording pages now marked "coming later"), dashboards
and metrics (0.15.0), per the roadmap.

## 8. Owner decisions

* 2026-10-14: scope from the owner's messages (§1); Veyra-native blocker
  with optional CrowdSec rather than fail2ban; phone trust through
  provisioning.
* 2026-10-15: flyouts split into columns by group (released as 0.13.1
  before this milestone).
* Approval: *pending*.

## Addendum (2026-10-15 02:09 UTC): 0.13.2 and the recovery fix on dev1

The owner reported that the Overview page scrolled past its end and took
the menu with it. Cause: the charts' hidden data tables (for screen
readers) kept their full height because tables ignore the clipping that
hides them. Fixed on branch `chart-scroll-fix` from `main` as **0.13.2**
(2890c02) and merged here. The owner upgraded dev1 from this branch to
**0.13.2-19227668b8**: CA and certificate kept, all verify checks OK.
`sudo veyra firewall off` now reports "Firewall turned off in the
database. Table inet veyra was not present." (exit 0) with the new wrapper.
