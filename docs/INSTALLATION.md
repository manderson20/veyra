# Installation

> **Status (Milestone 1, 2026-10-12):** `install.sh`, `verify.sh` and
> `upgrade.sh` have been run end to end on `veyra-dev1` (Ubuntu 26.04) and
> `install.sh`, `verify.sh`, `uninstall.sh` and a reinstall on an Ubuntu
> 24.04 container. Reports: [veyra-dev1](installations/veyra-dev1-2026-10-12.md),
> [Ubuntu 24.04](installations/ubuntu-24.04-container-2026-10-12.md).
> `veyra-dev2` is not installed yet (host not reachable).

## 1. Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu Server 26.04 LTS (primary) or 24.04 LTS (secondary) | 26.04 LTS, no desktop |
| CPU | 2 vCPU | 4+ vCPU |
| RAM | 2 GB | 4–8 GB |
| Disk | 5 GB free on `/` | 20 GB+ on `/var` (voicemail, recordings, backups) |
| Network | Static address recommended, working DNS, NTP | Private (RFC 1918) address |

On Proxmox, use VirtIO network and VirtIO SCSI, enable the QEMU guest agent,
and use bridged networking.

**Ubuntu 24.04 note:** verified on 2026-10-12 with Python 3.12.3,
PostgreSQL 16.15, Asterisk 20.6.0 and NGINX 1.24.0. The Ubuntu-packaged
Node.js (18.19) is too old to build the web interface, and the installer
stops with a clear message if it would have to. Use a release bundle with a
prebuilt `frontend/out/`, or build the web interface on a machine with
Node.js 20.9 or newer and copy `frontend/out/` into the source tree first.
Asterisk versions differ between releases by design (ADR 0010).

### Extending the default LVM volume

Ubuntu Server's installer often uses only part of the disk. `preflight.sh`
warns when 10 GB or more of the volume group is unallocated. To use all of
it:

```
sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
```

## 2. Install

```
git clone git@github.com:manderson20/veyra.git
cd veyra
sudo installer/preflight.sh          # read-only checks (exit 0 ok, 2 warnings, 1 blocking)
sudo installer/install.sh            # add --dry-run to see every action first
```

Options: `--yes` (non-interactive), `--dry-run`, `--skip-telephony`,
`--listen <address>` (repeatable), `--allow-public-admin`, and
`--role standalone` (default) or `--role secondary --join https://<primary>
--token <join token>` to join a high availability pair (see §5, High
availability).

The installer then:

1. Runs preflight and stops on blocking problems before changing anything.
2. Installs packages: Python 3, venv, build tools, PostgreSQL, NGINX, OpenSSL, Node.js/npm (only if the frontend must be built), and Asterisk with its modules and English sounds.
3. Creates the `veyra` system account (no login shell) and directories:

   | Path | Owner / mode | Contents |
   |---|---|---|
   | `/opt/veyra/releases/<version>-<rev>/` | root, read-only | Application code, venv, built UI |
   | `/opt/veyra/current` | symlink | Active release |
   | `/etc/veyra/veyra.env` | root:veyra 0640 | Settings (no secrets) |
   | `/etc/veyra/secrets/` | root:veyra 0750 | Generated credentials: `ari_password`, `installation.key` (encrypts SIP secrets at rest; **back it up**, see [EXTENSIONS.md](EXTENSIONS.md) §5), `bundled-modules.key` (root 0600: signs the modules shipped with the release; recreated if lost) |
   | `/etc/veyra/trust/{official,community,third_party}/` | root 0755 | Trusted signing keys (`official/bundled-modules.pub` is the server's own module key, [MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md) §6) |
   | `/etc/veyra/tls/` | root 0700 | HTTPS certificate and key |
   | `/var/lib/veyra/` | veyra:asterisk 0750 | Data; `prompts/` (IVR prompts, recordings from phones) and `mailqueue/` (outgoing email handed over by Asterisk) are `2770 veyra:asterisk` so Asterisk can write there; the `veyra` account is in group `asterisk` to read those files |
   | `/var/log/veyra/` | veyra 0750 | Installer and upgrade logs |
   | `/var/backups/veyra/` | root 0700 | Backups |

4. Generates credentials. The ARI password is random, the installation key is 256 random bits, and **PostgreSQL uses peer authentication** over the local socket, so no database password exists. Existing credentials are never replaced, on install or upgrade.
5. Creates the PostgreSQL role and database `veyra` (no superuser).
6. Copies the release, creates its virtualenv, builds the web interface, and makes the code root-owned and read-only.
7. Activates the release atomically and writes `/etc/veyra/veyra.env`.
8. Applies database migrations.
9. Creates a self-signed TLS certificate for the hostname and addresses (see §4).
10. Configures Asterisk: ARI on `127.0.0.1:8088` only, AMI disabled, originals backed up as `*.veyra-backup-<timestamp>`; the control socket is opened to group `asterisk` (`astctlpermissions = 0660` in `asterisk.conf`) so the Veyra service account can send NOTIFY requests to phones (one Asterisk restart the first time).
11. Installs and starts `veyra-api` (127.0.0.1:8100), `veyra-worker` and the root `veyra-ha-agent` (its socket `/run/veyra/ha.sock` is how HA is enabled later), all with systemd hardening.
12. Configures NGINX: HTTPS with an HTTP→HTTPS redirect, the default site disabled (its file is kept), security headers, and the phone provisioning locations (`/provisioning/`, rate-limited, and `/provisioning/firmware/` from `/var/lib/veyra/firmware`; see §4a). NGINX is **restarted** (not reloaded) when the Veyra site is first installed or its addresses change, because its address-specific listeners cannot be bound while the default site's wildcard sockets are open; upgrades with an unchanged site only reload.
13. Runs `verify.sh`.
14. Prints a **one-time setup token** and the URL of the setup wizard.

Logs are written to `/var/log/veyra/install-<timestamp>.log`. State is kept
in `/etc/veyra/install-state.json`.

**Re-running is safe.** Every step checks what already exists. Credentials,
the database and certificates are kept. A configuration file that Veyra did
not write is backed up before it is replaced. An interrupted installation
resumes when you run the installer again.

**What the installer never does:** change SSH settings, change firewall
rules, remove packages, overwrite data, or listen on public addresses
without `--allow-public-admin`.

## 3. First-run setup

Open `https://<server-address>/setup/` and enter the setup token. If you
lose it, run:

```
sudo veyra setup-token
```

The token is valid for 24 hours and for one use. Generating a new token
invalidates the old one. The wizard creates the first platform
administrator (also the local recovery administrator), the first
organization, the installation name and the time zone, and the extension
numbering plan (length and range; it can be changed later). Steps marked
"coming later" arrive in later milestones.

## 4. TLS

The installer creates a **Veyra certificate authority** (`/etc/veyra/tls/ca.crt`,
key `ca.key` readable by root only, 10 years, limited to this server's host
names) and an HTTPS certificate issued by it (`/etc/veyra/tls/veyra.crt` and
`veyra.key`, 825 days, renewed by the installer within 30 days of expiry).
Installations from before 0.14.0 have their self-signed certificate replaced
by one from the CA at the next upgrade.

* **Browsers** trust Veyra once the CA certificate is installed: download it
  from `https://<host>/downloads/veyra-ca.crt` and import it as a trusted
  root (or push it to managed Chromebooks and Chrome with Google Admin:
  Devices → Networks → Certificates). Until then browsers warn, as with the
  self-signed certificate; the Companion extension needs the CA installed.
* **Phones** get the CA through provisioning (§4a).
* **Your own certificate**: replace `veyra.crt` and `veyra.key` (key mode
  0600) and run `sudo systemctl reload nginx`. The installer never replaces
  a certificate it did not issue; phones then need that certificate's CA
  (a public CA is already trusted).

### 4a. Phone provisioning

Phones fetch their configuration from `https://<host>/provisioning/` with
HTTP Basic authentication ([DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md)
§3). The host name phones use is `VEYRA_PUBLIC_HOST`, set in
`/etc/veyra/installer.conf` (default: the server's fully qualified name)
and written to `veyra.env` by the installer. Poly phones do not trust the
server's certificate (issued by the Veyra CA, §4) until they have the CA. The recommended way to give it to them is
the **trust bootstrap** ([FIREWALL_TRUST.md](FIREWALL_TRUST.md) §6): set
`VEYRA_PROVISIONING_HTTP=1` in `installer.conf` and re-run the installer;
plain HTTP then serves only the Veyra CA and the HTTPS address (no
secrets), to the bootstrap networks only (System → Firewall → Settings;
default: the SIP local networks). Point DHCP option 66 (and 160 for Poly)
on the staging or voice VLAN at `http://<host>/provisioning/`; a new phone
fetches the bootstrap, reboots, and provisions over HTTPS. The device page
shows "Trusted, HTTPS" afterwards; a factory-reset phone needs "Allow
bootstrap again". `VEYRA_PROVISIONING_HTTP_MODE=full` serves every file over
HTTP as before 0.14.0 (SIP secrets unencrypted; `verify.sh` warns). Firmware images uploaded through the interface are served by
NGINX from `/var/lib/veyra/firmware`.

## 5. Verify and operate

```
sudo installer/verify.sh             # services, HTTPS, schema, exposure, permissions
sudo veyra status                    # quick health summary
journalctl -u veyra-api -u veyra-worker
```

`verify.sh` checks that the API, ARI and PostgreSQL are not reachable from
the network, that AMI is off, that secret files are 0640/0600, that the
installation key is present and well formed, and that the application code
cannot be written by the service account. `sudo veyra installation-key
check` prints the key's fingerprint.

### Account recovery from the server console

Two-factor authentication: `sudo veyra users mfa-reset <email>` removes a
user's authenticator devices and recovery codes and signs them out; they set
up a new authenticator at the next sign-in. This is the only way back in for
the recovery administrator, who is not exempt from the policy.

When no administrator can sign in (forgotten password, lockout), whoever
has shell access can recover an account; these commands are audited with
the actor `cli`:

```
sudo veyra users reset-password admin@example.org --base-url https://pbx.example.org
sudo veyra users reset-password admin@example.org --unlock   # also clears a lockout
sudo veyra users unlock someone@example.org
sudo veyra sessions revoke someone@example.org                # sign out everywhere
```

The reset link is valid for 24 hours and can be used once; the account is
signed out everywhere when it is used. Administrators can do the same from
a user's page in the UI.

### Modules from a catalog

A module catalog is used only when its index is signed by a key in
`/etc/veyra/trust/catalog/` (one `<key-id>.pub` per catalog key, readable by
all). Packages must also be signed by a publisher key in
`/etc/veyra/trust/official/` (or `community`/`third_party`). Installed and
updated modules live in `/var/lib/veyra/module-store`. The installer adds a
polkit rule (`/etc/polkit-1/rules.d/50-veyra-services.rules`) that lets the
`veyra` account restart Veyra's own units, so new module code can be loaded
from the Module Manager; Asterisk is never restarted by it.

### Single sign-on

System → Sign-in adds Google Workspace, Microsoft Entra ID or any OpenID
Connect provider ([INTEGRATIONS.md](INTEGRATIONS.md) §1). The provider needs
one redirect address, shown in the *Add provider* dialog:
`https://<server>/api/v1/auth/sso/callback` (built from `VEYRA_PUBLIC_HOST`
when it is set, otherwise from the address the browser used). For Google:

1. Google Cloud console → APIs & Services → Credentials → *Create OAuth
   client ID*, type *Web application*; add the redirect address under
   *Authorized redirect URIs*. On the consent screen choose *Internal*.
2. Enter the client ID, the secret and your e-mail domain in Veyra, then
   *Test*.
3. For silent Companion sign-in on managed Chromebooks: Admin console →
   Security → API controls → App access control → *Trusted* for this OAuth
   client, and add `"ssoProvider": "<provider id>"` to the extension policy
   (Settings → Companion deployment shows the JSON).

The recovery administrator always signs in with a password; with *Require
single sign-on* on, linked accounts cannot.

### Central management

Optional ([CENTRAL_MANAGEMENT.md](CENTRAL_MANAGEMENT.md)). On the server
that should be the console, turn on System → Central console and create an
enrollment token. On each other server, open System → Central management
and enter the console address, the token and the fingerprint shown with
the token. The instance connects out to the console over HTTPS; nothing
connects in to the instance. The console's `/api/v1/central/` path must be
reachable from the instances: NGINX listens on private addresses only
unless the console was installed with `--allow-public-admin`. If the
console uses a self-signed certificate, paste its CA certificate into the
enrollment form. An instance that loses the console keeps working; the
console shows it as offline and can raise an alert.

### Rotating the installation key

The installation key (`/etc/veyra/secrets/installation.key`) encrypts
every stored secret ([PRODUCTION_HARDENING.md](PRODUCTION_HARDENING.md)
§3.1). To replace it:

```
sudo veyra installation-key rotate
sudo veyra installation-key check --ciphertexts
```

A new key is generated, every ciphertext is re-encrypted in one
transaction (nothing changes if any of them cannot be read), the new key
is installed, the previous one is kept as `installation.key.previous`
(root-only) and the services restart. Take a backup afterwards, then
remove the previous key. On an HA pair, rotate on the primary; the key
reaches the standby through the file sync.

### Backups and restore

System → **Backups** ([PRODUCTION_HARDENING.md](PRODUCTION_HARDENING.md)
§2). A backup is a directory under `/var/backups/veyra` (root-only) with
the database dump, `/etc/veyra` (secrets, keys, certificates),
`/etc/asterisk`, the data directories, the voicemail spool and optionally
the recordings, plus a manifest; it is restored into a scratch database
and checked before it counts. Set **recipients** (age public keys made
with `age-keygen` on another machine) and backups leave the server as one
encrypted `.tar.age` file; a copy directory (a mounted NAS share) receives
each one. `sudo veyra backup run` takes one from the console.

Restore on a server with the same (or a newer) Veyra release installed:

```
sudo veyra backup restore /path/to/veyra-<stamp>.tar.age --identity ~/veyra-backup-identity.txt
sudo installer/verify.sh
```

Services stop, the database is recreated from the dump, the files come
back with their owners and modes, migrations run when the backup is older,
and the services start. The instance identity, keys and certificates are
part of the backup, so phones and a central console keep recognising the
server. A backup taken on an HA node is restored to a standalone first.

### High availability

Optional ([HIGH_AVAILABILITY.md](HIGH_AVAILABILITY.md)). Two servers on
the same network segment, the same Ubuntu release and the same Veyra
release. On the server that has the data, open System → High availability
and **Enable high availability**: give the service name (what phones and
browsers will use; it must resolve to the service address), a free address
on the segment with its prefix length, and the interface. PostgreSQL is
reconfigured for replication and restarted once; the HTTPS certificate is
reissued for the service name and both node names (if the Veyra CA had to
be widened to permit the new names, phones and browsers must trust the new
`veyra-ca.crt`). Then **Add node** gives a join token and the exact command
for the second server:

```
sudo installer/install.sh --role secondary --join https://veyra-dev1 --token vyj_…
```

The second server's installer checks that the primary answers, installs
the packages, then asks the primary for the join bundle (credentials, the
CA and certificates, trust keys, the replication credential; encrypted with
a key derived from the token), replaces its PostgreSQL data directory with
a base backup of the primary and starts as a streaming standby; Asterisk is
installed and configured but stays stopped, `veyra-deployer` and
`veyra-pager` stay stopped, the file sync pulls prompts, hold music,
firmware, templates, modules, downloaded releases, recordings (optional)
and voicemail every 30 s. No migrations and no setup token on a standby:
users and settings arrive through replication.

The standby serves its own interface at `https://<its name>/` for platform
administrators, read-only, with the HA page: that is where a **failover**
is started when the primary is down (after fencing through Proxmox when
configured, or the operator's confirmation that the primary is off). A
planned **switchover** starts from either node's HA page while both are
up. The engine units (`asterisk`, `veyra-deployer`, `veyra-pager`) are not
enabled at boot on an HA node: the agent starts them with the primary role,
and a primary that boots without reaching its peer waits as *isolated*
until the operator resumes it or the peer answers.

`verify.sh` adds `ha-role`, `ha-replication`, `ha-sync` and `ha-peer`;
`sudo veyra ha status` prints the node's view. Updates on a pair follow
[UPDATE_MANAGEMENT.md](UPDATE_MANAGEMENT.md) §8: standby first, switch
over, then the old primary; `upgrade.sh` on a standby skips migrations.

### Firewall recovery from the server console

If a firewall setting locks you out, from the console (or any SSH session
that still works) run `sudo veyra firewall off`: it turns the firewall off
in the database and deletes the table `inet veyra` at once. Without Veyra,
`sudo nft delete table inet veyra` removes it too. Veyra never touches other
nftables tables (LXD, Docker, ufw). `sudo veyra firewall status` shows the
settings, the service state and the active bans.

### Services

| Unit | Runs as | Purpose |
|---|---|---|
| `veyra-api` | veyra | Management API behind NGINX |
| `veyra-worker` | veyra | Heartbeat, update checks, session purge, outgoing mail queue (voicemail notifications), prompt folders |
| `veyra-deployer` | veyra | Writes generated telephony configuration to `/etc/asterisk/veyra` and reloads Asterisk (only with a telephony engine) |
| `veyra-pager` | veyra | Page sender: speakers' multicast and Poly group pages from one stream ([PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §2.2) |
| `veyra-firewall` | veyra (+ CAP_NET_ADMIN) | Applies the nftables table `inet veyra` and bans attackers ([FIREWALL_TRUST.md](FIREWALL_TRUST.md) §3); off until turned on under System → Firewall |
| `veyra-ha-agent` | root | High availability agent ([HIGH_AVAILABILITY.md](HIGH_AVAILABILITY.md) §3): holds the service address, drives PostgreSQL replication, runs switchover, failover and rejoin; fixed verbs over `/run/veyra/ha.sock`. Idle on a standalone |
| `asterisk` | asterisk | Telephony engine; its `pjsip.conf`, `extensions.conf`, `rtp.conf`, `voicemail.conf`, `queues.conf`, `pjsip_notify.conf`, `musiconhold.conf`, `logger.conf` (with the security log the firewall reads), `cdr.conf` and `cdr_custom.conf` (call history) are Veyra-managed stubs that include the generated files. `asterisk-moh-opsound-wav` provides the built-in hold music; Veyra's hold music sets live in `<data>/moh/`, call recordings in `<data>/recordings/` |

`journalctl -u veyra-deployer` shows deployments; `sudo veyra config status`
summarises the engine and recent revisions.

## 6. Upgrade and uninstall

```
sudo installer/upgrade.sh            # see docs/UPDATE_MANAGEMENT.md
sudo installer/uninstall.sh          # keeps database, configuration and data
sudo installer/uninstall.sh --purge  # also deletes them (type the hostname to confirm)
```

Backups in `/var/backups/veyra` are never deleted by these scripts, and
system packages are never removed.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| Preflight: "public IP address" warning | The UI will not listen on public addresses. Use `--listen` or put the server behind a firewall or VPN. |
| `veyra-api did not become ready` | `journalctl -u veyra-api -n 100`; `sudo veyra status` |
| `NGINX is running but https://127.0.0.1/ does not answer` | `/var/log/nginx/error.log`; `bind() ... Address already in use` means another server holds port 80 or 443 |
| Asterisk logs `radcli: rc_read_config ... radiusclient.conf` at start | Harmless: Ubuntu's module set loads `cdr_radius`/`cel_radius`; Veyra's managed `modules.conf` (since 0.9.0) keeps them from loading |
| Calls to voicemail fail with `No application 'VoiceMail'` | `app_voicemail_odbc.so` loaded beside `app_voicemail.so` and unregistered the applications; Veyra's `modules.conf` prevents it, `sudo systemctl restart asterisk` recovers, `sudo installer/verify.sh` checks (`engine-voicemail-app`) |
| ARI not answering | `sudo asterisk -rx "http show status"`; check `/etc/asterisk/http.conf` |
| Browser certificate warning | Expected with the self-signed certificate; see §4 |
| Install stopped half-way | Fix the reported problem and run `install.sh` again; it resumes |
