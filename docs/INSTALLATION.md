# Installation

> **Status (Milestone 0):** the installer scripts are written, pass
> ShellCheck and their unit tests, and `preflight.sh` and
> `install.sh --dry-run` have been run on `veyra-dev1`. A full installation
> has **not** been run end to end yet. That is the first task of
> Milestone 1, and this page will be updated with verified results then.

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

**Ubuntu 24.04 note:** the Ubuntu-packaged Node.js on 24.04 is too old to
build the web interface. Use a release bundle with a prebuilt
`frontend/out/`, or install Node.js 20.9 or newer first. Python and
PostgreSQL versions on 24.04 have not yet been verified for Veyra (M1).

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
`--role standalone`.

The installer then:

1. Runs preflight and stops on blocking problems before changing anything.
2. Installs packages: Python 3, venv, build tools, PostgreSQL, NGINX, OpenSSL, Node.js/npm (only if the frontend must be built), and Asterisk with its modules and English sounds.
3. Creates the `veyra` system account (no login shell) and directories:

   | Path | Owner / mode | Contents |
   |---|---|---|
   | `/opt/veyra/releases/<version>-<rev>/` | root, read-only | Application code, venv, built UI |
   | `/opt/veyra/current` | symlink | Active release |
   | `/etc/veyra/veyra.env` | root:veyra 0640 | Settings (no secrets) |
   | `/etc/veyra/secrets/` | root:veyra 0750 | Generated credentials |
   | `/etc/veyra/trust/{official,community,third_party}/` | root 0755 | Trusted signing keys |
   | `/etc/veyra/tls/` | root 0700 | HTTPS certificate and key |
   | `/var/lib/veyra/` | veyra 0750 | Data |
   | `/var/log/veyra/` | veyra 0750 | Installer and upgrade logs |
   | `/var/backups/veyra/` | root 0700 | Backups |

4. Generates credentials. The ARI password is random, and **PostgreSQL uses peer authentication** over the local socket, so no database password exists.
5. Creates the PostgreSQL role and database `veyra` (no superuser).
6. Copies the release, creates its virtualenv, builds the web interface, and makes the code root-owned and read-only.
7. Activates the release atomically and writes `/etc/veyra/veyra.env`.
8. Applies database migrations.
9. Creates a self-signed TLS certificate for the hostname and addresses (see §4).
10. Configures Asterisk: ARI on `127.0.0.1:8088` only, AMI disabled, originals backed up as `*.veyra-backup-<timestamp>`.
11. Installs and starts `veyra-api` (127.0.0.1:8100) and `veyra-worker`, both with systemd hardening.
12. Configures NGINX: HTTPS with an HTTP→HTTPS redirect, the default site disabled (its file is kept), and security headers.
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
organization, the installation name and the time zone. Steps marked
"coming later" arrive in later milestones.

## 4. TLS

The self-signed certificate is in `/etc/veyra/tls/veyra.crt` and
`veyra.key`. To use your own certificate, replace both files (key mode 0600)
and run `sudo systemctl reload nginx`. The installer never overwrites
existing certificate files.

## 5. Verify and operate

```
sudo installer/verify.sh             # services, HTTPS, schema, exposure, permissions
sudo veyra status                    # quick health summary
journalctl -u veyra-api -u veyra-worker
```

`verify.sh` checks that the API, ARI and PostgreSQL are not reachable from
the network, that AMI is off, that secret files are 0640/0600, and that the
application code cannot be written by the service account.

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
| ARI not answering | `sudo asterisk -rx "http show status"`; check `/etc/asterisk/http.conf` |
| Browser certificate warning | Expected with the self-signed certificate; see §4 |
| Install stopped half-way | Fix the reported problem and run `install.sh` again; it resumes |
