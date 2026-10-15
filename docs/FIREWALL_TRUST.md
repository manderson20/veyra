# Firewall and Phone Trust (Milestone 9d)

Design for Milestone 9d (roadmap row 9d, 0.14.0). Owner requests of
2026-10-14:

1. "Something better than fail2ban": block and allow addresses and
   networks from the interface, automatic timed bans for attackers.
2. A **permanent allow list** (local networks, trunks) that bans never
   override, so a misconfigured phone on the LAN cannot lock itself out
   while remote attackers are blocked.
3. A page showing bans and the events behind them; optional CrowdSec.
4. Phone trust through provisioning: the phones should trust the server
   without anyone installing a certificate by hand.

Sections marked *(spike)* need a measurement on dev1 or the owner's
phones before the code is final; the rest can be built from this document.

## 1. What Veyra protects today, and the gap

NGINX rate-limits sign-in, second factor, password reset and provisioning;
accounts lock after repeated failures; the API, ARI and PostgreSQL listen
on loopback only and AMI is off. **Nothing blocks at the network level**:
a SIP scanner can try passwords against 5060 indefinitely, and every
attempt costs Asterisk work and fills the log. The installer does not
touch the firewall (NETWORKING.md); dev1 has ufw inactive and LXD's own
nftables table (`inet lxd`).

## 2. Objects

| Object | Table | Purpose |
|---|---|---|
| **Firewall settings** | `firewall_settings` (one row) | On/off, mode (§3.2), ban thresholds and durations, the services policy, HTTP-bootstrap networks (§6) |
| **Address rule** | `firewall_rules` | `action` ∈ allow, block; `cidr` (IPv4 or IPv6, host or network); `services[]` (empty = all); `comment`; `expires_at` (null = permanent); `origin` ∈ manual, trunk, sip_local_net, server, feed; `created_by` |
| **Ban** | `firewall_bans` | Automatic, timed: `address`, `reason`, `source` (asterisk, auth, provisioning, nginx, feed), `event_count`, `banned_at`, `expires_at`, `offence` (repeat count), `lifted_at/by` |
| **Event** | `firewall_events` | One suspicious event: `time`, `address`, `source`, `kind` (e.g. `sip_bad_password`, `sip_unknown_account`, `login_failed`, `prov_unauthorized`, `rate_limited`), `detail` (endpoint or user name tried, user agent); kept 30 days |
| **Blocklist feed** | `firewall_feeds` | An external list of addresses to block: CrowdSec local API or a plain list URL (§5) |

All of these are **system-wide** (the firewall belongs to the server, not
to an organization): permissions `firewall.read` and `firewall.write`,
granted to the system administrator role only.

## 3. Enforcement

### 3.1 One table of our own

Veyra manages exactly one nftables table, `inet veyra`, and never touches
any other table or flushes the ruleset. That keeps it out of the way of
LXD, Docker, ufw or anything the administrator runs. In nftables a packet
passes every base chain on the same hook; an `accept` in one table does not
override a `drop` in another, so Veyra's table can only **remove** traffic,
never open what another firewall closes.

```
table inet veyra {
  set allow4   { type ipv4_addr; flags interval; }          # permanent allow list
  set allow6   { type ipv6_addr; flags interval; }
  set block4   { type ipv4_addr; flags interval, timeout; } # manual blocks (optionally timed)
  set block6   { type ipv6_addr; flags interval, timeout; }
  set ban4     { type ipv4_addr; flags timeout; }           # automatic bans, kernel expires them
  set ban6     { type ipv6_addr; flags timeout; }
  set feed4    { type ipv4_addr; flags interval; }          # CrowdSec / list feeds
  set feed6    { type ipv6_addr; flags interval; }

  chain input {
    type filter hook input priority filter - 5; policy accept;
    iif lo return
    ip saddr @allow4 return
    ip6 saddr @allow6 return
    ip saddr @block4 drop
    ip6 saddr @block6 drop
    ip saddr @ban4 drop
    ip6 saddr @ban6 drop
    ip saddr @feed4 drop
    ip6 saddr @feed6 drop
    # policy mode only (§3.2): per-service rules follow here
  }
}
```

The allow list is checked first, so **nothing Veyra does can drop an
allowed address**, whatever the bans say. Bans carry their own kernel
timeout, so they expire even if the Veyra services are stopped.

Per-service block rules (`services[]` set) render as
`ip saddr <cidr> udp dport { 5060 } drop` style lines inside the chain;
services map to ports read from the deployed configuration: `sip`
(transports from the SIP settings), `rtp` (the RTP range), `web` (443/80),
`provisioning` (443/80 path-level is not possible in nftables, so a
provisioning-only block is enforced by NGINX `deny` instead), `ssh` (22 or
the port sshd listens on, read with `ss`).

### 3.2 Modes

* **Block mode** (default when the firewall is turned on): everything not
  blocked or banned passes, as today. The firewall only removes attackers.
  Safe on any network.
* **Policy mode** (opt-in, per service): a service can be limited to the
  allow list ("SIP only from the local networks and the trunks", "web
  interface only from the staff networks"). Each service has
  `anywhere | allow_list_only`. SSH defaults to `anywhere` and the
  interface warns before restricting it.

### 3.3 Who applies the rules

A new service **`veyra-firewall`** runs as user `veyra` with only
`CAP_NET_ADMIN` (`AmbientCapabilities=CAP_NET_ADMIN`, no other
privileges, same systemd hardening as the other units). It:

1. renders the table from the database and applies it **atomically** with
   `nft -f` (a single transaction that creates, deletes and recreates
   `inet veyra`, so there is no moment without rules);
2. adds and removes ban elements incrementally (`add element ... timeout
   1h`) instead of re-rendering for every ban;
3. writes the last applied ruleset to `/var/lib/veyra/firewall/veyra.nft`
   and re-applies that file at boot if the database is not reachable yet;
4. watches the event sources (§4) and decides bans (§4.2).

The API never runs `nft`; it writes the desired state and bumps a
revision, as the deployer does for Asterisk.

### 3.4 Not locking yourself out

* The **server's own addresses**, loopback, the SIP settings' local
  networks and every trunk's address are allow-list entries with an
  `origin` other than `manual`. The local-network entries are proposed when
  the firewall is first turned on and the administrator confirms them
  (owner: "local networks" are permanently allowed). Trunk entries follow
  the trunk configuration; host names are resolved at each apply.
* The API **refuses** a block, a ban or a policy change that would drop
  the address of the administrator making the request (`409
  firewall_self_block`) unless that address is on the allow list.
* **Confirm or revert**: a policy-mode change is applied, then reverted
  automatically after 60 seconds unless the browser that made it confirms
  ("Keep these settings?"), like a router's confirm dialog. Blocks and
  bans do not need this; they cannot hit allowed addresses.
* **Console recovery**: `sudo veyra firewall off` deletes the table and
  turns the firewall off in the database; `sudo nft delete table inet
  veyra` works even without Veyra. Both are in INSTALLATION.md
  (Account recovery section).

## 4. Detection

### 4.1 Event sources

| Source | How Veyra reads it | Events |
|---|---|---|
| **Asterisk** | Security log channel: a Veyra-managed `logger.conf` stub adds `security.log => security` (file `/var/log/asterisk/security.log`, group `asterisk`, read by `veyra`); `veyra-firewall` follows the file | `InvalidAccountID` (unknown endpoint: scanners), `ChallengeResponseFailed`/`InvalidPassword` (wrong SIP password), `FailedACL`, `RequestBadFormat` |
| **Veyra sign-in** | Written directly by the API where it already records "Sign-in failed" (real client address via `core.deps.client_address`) | `login_failed`, `mfa_failed`, `reset_invalid` |
| **Provisioning** | Written by `provisioning/serve.py` on 401 | `prov_unauthorized` |
| **NGINX** | Error log lines `limiting requests` (limit_req rejections); `veyra` reads `/var/log/nginx/error.log` via group `adm` | `rate_limited` |

Asterisk security events are reliable and cheap; the log file is the only
channel available while AMI stays off. *(spike: confirm the exact line
format of Asterisk 22's security log on dev1 and the remote address field
for PJSIP over UDP and TCP.)*

### 4.2 Ban rules

Per address, a sliding window of weighted events; defaults (editable):

| Kind | Weight | Notes |
|---|---|---|
| `sip_unknown_account` | 2 | scanners try many names quickly |
| `sip_bad_password` | 1 | a phone with a stale password produces these too |
| `login_failed`, `mfa_failed` | 1 | account lockout still applies separately |
| `prov_unauthorized` | 1 | |
| `rate_limited` | 1 | |

* Ban when the score reaches **10 within 10 minutes**.
* First ban **1 hour**; each repeat within 7 days doubles it (2 h, 4 h …)
  up to **7 days**. A third ban within 24 hours offers "Block permanently"
  on the Bans page (it does not happen automatically).
* **Allowed addresses are never banned**; their events are still recorded
  and shown, with a "would have been banned" marker, which is how a
  misconfigured phone on the LAN is found instead of locked out.

## 5. CrowdSec and blocklist feeds

Feeds fill the `feed4/feed6` sets, refreshed every 10 minutes (atomic set
replacement). Two kinds:

* **CrowdSec local API** (optional): if the administrator runs CrowdSec,
  Veyra acts as a bouncer: `GET /v1/decisions/stream` with a bouncer key
  (`cscli bouncers add veyra`), stored encrypted. Veyra does not install
  CrowdSec; INSTALLATION.md gives the steps. Sending Veyra's own bans to
  CrowdSec as signals is *(later)*.
* **Plain list URL**: one address or network per line (for example
  Spamhaus DROP). Size-limited (100 000 entries) and HTTPS only.

The allow list beats feeds as it beats bans.

## 6. Phone trust

### 6.1 The problem

Poly phones (and Yealink, Grandstream) trust the public certificate
authorities only. dev1's certificate is self-signed, so phones cannot use
HTTPS provisioning until someone installs the certificate on each phone by
hand, which is why 0.11.0 added opt-in HTTP provisioning. With HTTP, SIP
passwords cross the LAN unencrypted.

### 6.2 A Veyra certificate authority

* The installer creates a **Veyra CA** (`/etc/veyra/tls/ca.key`, `ca.crt`,
  EC P-256, 10 years, `O=Veyra local CA`, with a name constraint limiting
  it to the server's own names and addresses *(spike: Poly firmware
  handling of name constraints; drop the constraint if the phone rejects
  it)*). The key is root-only and used only by the installer.
* The server certificate is **issued by the CA** instead of self-signed
  (same names and addresses as today, 825 days). An existing certificate
  is replaced only if it is Veyra's own self-signed one (subject
  `O=Veyra (self-signed)`); a certificate the administrator installed is
  never touched.
* Browsers: the CA certificate is downloadable at
  `/downloads/veyra-ca.crt`; installing it once (or pushing it through
  Google Admin, as for the Companion extension) removes the browser
  warning on every Veyra page. With a public certificate later, phones
  and browsers trust the server directly and the CA is simply unused.

### 6.3 Bootstrap over HTTP, everything else over HTTPS

The 0.11.0 HTTP server block changes meaning: **HTTP provisioning serves
the bootstrap only**.

1. A new or factory-reset phone on the staging (or voice) VLAN gets the
   provisioning address from DHCP option 66/160:
   `http://<host>/provisioning/` (no credential needed for the bootstrap).
2. Over HTTP Veyra answers `<MAC>.cfg` with a **bootstrap master file**
   that contains no secret: the CA certificate
   (`device.sec.TLS.customCaCert1` + `.set`), the HTTPS server address
   (`device.prov.serverType=HTTPS`, `device.prov.serverName`), and the
   organization enrollment credential only if the administrator chose to
   include it (§6.4). Other files requested over HTTP return 404.
3. The phone reboots, now trusts the CA and provisions over **HTTPS**; it
   gets its full configuration including the SIP password and its own
   device credential (DEVICE_PROVISIONING.md §3.2), as today.
4. Once a device has fetched over HTTPS, Veyra refuses HTTP for that MAC
   (downgrade protection; the device page shows "Trusted, HTTPS" and the
   date). A reset phone needs "Allow bootstrap again" on its device page.

HTTP bootstrap is accepted only from the **bootstrap networks** in the
firewall settings (default: the SIP local networks), enforced by NGINX
`allow/deny` in the HTTP block.

Poly parameter names are from the UC Software administrator guide
*(spike: confirm on the owner's VVX firmware that a custom CA delivered in
the master file is used for the provisioning connection after the
reboot)*. Yealink (`static.trusted_certificates.url`) and Grandstream
(P8463 custom certificate) get the same bootstrap in their templates later.

### 6.4 How the phone gets its credential

The bootstrap is public data, but the phone still has to authenticate
over HTTPS. Two choices per organization:

* **Credential in DHCP / typed** (default, safest): the enrollment
  credential stays in DHCP option 66 or is typed on the phone as today; the
  bootstrap only changes the scheme and adds the CA. Over HTTP the
  credential is not needed, so it is never sent in clear.
* **Credential in the bootstrap** (convenient, for a staging VLAN): the
  bootstrap also sets `device.prov.user/password` to the enrollment
  credential, so nothing is typed. Anyone who can read the staging VLAN
  sees it; the organization page recommends rotating the enrollment
  credential after a staging batch. Phones already provisioned keep
  working because they use their own device credentials.

### 6.5 Steps for the technician (to go in the user guide)

1. One time: set DHCP option 66 on the staging or voice VLAN to
   `http://<server>/provisioning/` (and option 160 for Poly).
2. Add the phone in Veyra (or let it appear under "unregistered phones
   seen" and add it with one click).
3. Plug the phone in. It reboots once after the bootstrap and registers.
   The device page shows "Trusted, HTTPS".

## 7. Permissions, API, interface

```
GET/PUT    /firewall/settings
GET/POST   /firewall/rules, PATCH/DELETE /firewall/rules/{id}
GET        /firewall/bans?active=, POST /firewall/bans/{id}/lift, POST /firewall/bans/{id}/block
GET        /firewall/events?address=&source=&since=
GET/POST   /firewall/feeds, PATCH/DELETE /firewall/feeds/{id}, POST /firewall/feeds/{id}/refresh
POST       /firewall/confirm            (keep a policy-mode change, §3.4)
GET        /firewall/status             (service state, applied revision, set sizes)
GET        /provisioning/trust          (CA fingerprint, bootstrap networks, HTTP on/off)
POST       /devices/{id}/allow-bootstrap
```

Interface: **System → Firewall** with Overview (on/off, mode, bans now,
events in 24 h, top attacking addresses), Bans (lift, extend, block
permanently), Allow and Block list (origin badges: manual, trunk, local
network, server; automatic ones are read-only), Events (filter by address
and source; "would have been banned" marker), Settings (thresholds, policy
per service, bootstrap networks, feeds). The dashboard gains a "Firewall"
item (bans in 24 h). The device page shows the trust state (§6.3), the
organization's provisioning card the bootstrap choice (§6.4).

## 8. Installer

* `nftables` package (Ubuntu ships it); the `veyra-firewall` unit with
  `CAP_NET_ADMIN`; `veyra` added to group `adm` (NGINX error log).
* Managed `logger.conf` stub (security channel), keeping the existing
  channels; `logger reload`.
* CA and CA-signed server certificate (§6.2); `/downloads/veyra-ca.crt`.
* The HTTP provisioning block (`VEYRA_PROVISIONING_HTTP=1`) serves the
  bootstrap with `allow/deny` from the bootstrap networks.
* The firewall is **off after installation and upgrade**; the
  administrator turns it on from the interface after confirming the allow
  list. `verify.sh`: `firewall-service`, `firewall-table` (table present
  when on), `security-log` (Asterisk security channel active),
  `tls-ca` (server certificate chains to the CA, or is a custom one).

## 9. Testing

Unit: ruleset rendering (golden files, IPv4 and IPv6, per-service rules),
ban scoring and escalation, allow-list precedence, self-block refusal,
confirm-or-revert timer, Asterisk security log parsing (samples from
dev1), feed parsing and limits, bootstrap file content (no secrets) and
downgrade protection. Live on dev1: turn the firewall on alongside LXD's
table; from an LXD container (a second source address) register with
`tools/fakephone.py` using a wrong password until banned, confirm the
packets are dropped, lift the ban; put the container's address on the
allow list and confirm it is never banned; curl the bootstrap over HTTP
and the full configuration over HTTPS with only the CA certificate
trusted. Owner hardware: a VVX phone on the staging VLAN goes from factory
reset to registered over HTTPS without anything typed.

## 10. Out of scope

Outbound filtering, NAT or routing; replacing ufw (it can stay; Veyra only
adds drops); intrusion detection beyond the listed sources; SIP over TLS
for phones with the Veyra CA (a natural follow-up: same CA, port 5061);
firewall state across HA nodes (M16 replicates the database, each node
applies its own table); sending signals to CrowdSec.

## 11. Open questions for the owner

1. Which networks are "local" and permanently allowed: the voice VLANs,
   the staff network, all private ranges? (Default proposal: the SIP
   settings' local networks, shown for confirmation.)
2. Is SSH reachable from the internet, and should Veyra be able to limit
   it to the allow list (policy mode), or leave SSH alone entirely?
3. Is CrowdSec already in use anywhere in the district?
4. Are the ban defaults (score 10 in 10 minutes, 1 hour doubling to
   7 days) acceptable?
5. Bootstrap credential: DHCP/typed (safer) or in the bootstrap (no
   typing, needs a staging VLAN)?
6. Is a public certificate and domain name planned? It does not change
   this design, but it would let browsers trust Veyra without the CA.

## 12. Decisions

* 2026-10-14: scope from the owner's messages (above); Veyra-native
  blocker with optional CrowdSec rather than fail2ban.
