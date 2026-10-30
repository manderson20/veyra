# Public HTTPS certificates (Let's Encrypt / ACME)

Status: built in 0.27.41 (issue #43); the HA part (§8) is not finished.
Builds on the phone trust design in
[FIREWALL_TRUST.md](FIREWALL_TRUST.md) §6.

## 1. Goal

An administrator types the server's public host name on one page and Veyra
gets a certificate that every browser trusts from an ACME authority (Let's
Encrypt by default), keeps it renewed, and raises an alert when renewal
fails. Nothing changes for closed networks: the Veyra CA stays the default
and keeps serving phones.

Why it matters: passkeys (#107), the Companion and a browser without
`veyra-ca.crt` installed all need a certificate the browser already trusts.

## 2. Two certificates side by side

| | Veyra CA certificate (today) | Public certificate (new) |
|---|---|---|
| Issued by | the installation's own CA | Let's Encrypt or another ACME CA |
| Names | host name, FQDN, IP addresses | the public host name(s) the administrator enters |
| Served when | any other name or an IP address (default server) | the browser asks for that name (SNI) |
| Used by | phones (provisioning, SIP TLS), internal names | browsers, the Companion, passkeys |

NGINX gets a second HTTPS `server` block for the public name, with the
same locations (moved into one shared include). Phones keep using the
address or internal name they were bootstrapped with, so they never see a
certificate they may not trust: some Poly and Yealink firmware lacks the
ISRG roots. When no public certificate exists, the second block answers
only to the reserved name `public-certificate.invalid`, so it can never
match a request.

## 3. How the certificate is obtained

**Client.** `certbot` from the Ubuntu archive, run as root by
`veyra-acme@<mode>.service` (modes `issue`, `renew`, `remove`). Polkit lets
the `veyra` service account start these units, as it does for backups and
OS packages. Certbot's state lives under Veyra's own directories (config
`/etc/veyra/acme/certbot`, work `/var/lib/veyra-acme/work`, logs
`/var/log/veyra-acme`), so it never mixes with a certbot the administrator
runs for something else. Ubuntu's `certbot.timer` does not renew it;
Veyra's worker does (§5).

**Challenges.**
- **HTTP-01**: certbot writes the token to `/var/lib/veyra-acme/webroot`,
  which the port-80 server serves at `/.well-known/acme-challenge/` (before
  the redirect to HTTPS). Needs the name to resolve publicly to an address
  whose port 80 reaches this server, usually through a port forward.
- **DNS-01**: for servers that are not reachable from the internet (most
  schools). Providers from the Ubuntu archive: Cloudflare, Amazon Route 53,
  Google Cloud DNS, DigitalOcean, Linode, DNSimple, OVH, and RFC 2136 (any
  DNS server that accepts signed dynamic updates: BIND, Windows DNS with
  TSIG). The provider's plugin package is installed the first time it is
  used. DNS-01 can also issue a wildcard.

**Authority.** Let's Encrypt (production), Let's Encrypt staging (to test
the setup without the production rate limits), or any ACME directory URL
with optional External Account Binding (ZeroSSL, Sectigo, an internal
step-ca).

**Key.** ECDSA P-256, as the Veyra CA's certificates use.

## 4. Data flow and privileges

1. **Settings.** The page saves the settings in `system_settings` under
   `tls.public_certificate`: names, email, challenge, provider, authority,
   staging, and whether SIP TLS uses it. Provider credentials (API tokens,
   TSIG secret) are encrypted with the installation key, write-only, and
   never returned.
2. **Request.** *Get the certificate* requires *Confirm it is you*. The
   API writes `/var/lib/veyra-acme/request.json` (directory
   `root:veyra 0770`) with the decrypted credentials, then starts
   `veyra-acme@issue`.
3. **Run.** The root helper `installer/bin/veyra-acme` (Python, standard
   library only) moves the credentials into
   `/etc/veyra/acme/credentials.ini` (root, 0600) and deletes the request
   file. It installs the plugin if it is missing, runs certbot, and on
   success deploys:
   - `/etc/veyra/tls/public.crt` (full chain) and `public.key`
   - `/etc/veyra/nginx-public-name.conf` (`server_name …;`), then
     `nginx -t` and a reload. If the test fails, the previous files are
     restored.
   - Asterisk-readable copies in `/etc/asterisk/veyra-tls/` (§6)
   - `/var/lib/veyra-acme/certificate.json` (names, issuer, validity,
     fingerprint) for the page
4. **Status.** The status files `started`, `mode`, `exit`, `finished` and
   `last.log` sit in the same directory and work as they do for OS
   packages.

`remove` deletes the public certificate and the name file, reloads NGINX
and keeps the certbot account. After it, every request gets the Veyra CA
certificate again.

## 5. Renewal and alerts

- The worker checks once a day. When the public certificate has 30 days or
  less left (certbot's own rule), it starts `veyra-acme@renew`. A renewal
  that fails is retried the next day.
- A failed run raises the new alert rule `certificate_renewal` with
  certbot's last error. The existing `certificate` alert ("expires in N
  days") now checks the public name too, connecting with that name as SNI.
- An email goes to the alert recipients, like every alert.

## 6. Firewall and SIP TLS

- **Firewall.** When the web service is "allow list only", Let's Encrypt
  cannot reach port 80. For an HTTP-01 run, the API (or the worker on
  renewal) records `tls.acme_challenge_until` = now + 10 minutes. While
  that time is in the future, the firewall service renders
  `tcp dport 80 return` ahead of the allow-list drops. Bans and blocks
  still apply. DNS-01 needs no opening.
- **SIP TLS.** Today the generated transport points Asterisk at
  `/etc/veyra/tls/veyra.key`, which Asterisk cannot read: the directory is
  root-only, so SIP TLS cannot work. Fix: the installer and the helper keep
  copies in `/etc/asterisk/veyra-tls/` (`root:asterisk`, 0640), and the
  generator points there. A setting on the SIP settings page chooses which
  certificate the TLS transport presents:
  - the Veyra CA one (default: phones trust it)
  - the public one (for softphones and remote phones that connect by the
    public name)

  Asterisk reads a transport's certificate only when the transport is
  created, so a renewed certificate reaches SIP TLS at the next Asterisk
  restart. The page says so. If the certificate in use has 7 days or less
  left, the alert names the restart.

## 7. Interface and API

**Page: System → Settings → HTTPS certificate.** It shows:
- the certificate in use for each name, with issuer and expiry
- the settings form
- *Get the certificate*, *Renew now*, and *Stop using the public
  certificate*
- the last run's progress and output, which can be folded away

**Permissions.** Platform administrators only: `system.settings.read` and
`system.settings.write`. Every change and run goes in the audit log.

**API.**
- `GET /system/certificate`
- `PUT /system/certificate/settings`
- `POST /system/certificate/request`
- `POST /system/certificate/renew`
- `POST /system/certificate/remove`

**Console.** `sudo veyra certificate status|renew|remove`.

**Checks.** `verify.sh` gains `acme-unit`. When a public certificate is
configured it also gains `public-cert`: valid for 14 days or more, and
served for its name.

## 8. High availability, backups

- **Backups.** `/etc/veyra` is already backed up, so the certbot account,
  the certificate and the encrypted settings come back on restore.
- **High availability.** The public name should be the HA service name.
  Renewal runs only on the primary. The HA file sync copies `/etc/veyra/tls`
  and `/etc/veyra/acme` (the request and credentials), but not certbot's own
  tree under `acme/certbot`, which relies on symlinks the sync skips. After
  each sync the standby's agent works out the rest from the certificate
  (`veyra/ha/public_cert.py`): the name file, the NGINX reload, Asterisk's
  copies and `certificate.json`. So after a switchover the new primary serves
  the public certificate and its worker renews it. That first renewal has no
  certbot history on this node, so it requests a new certificate and registers
  a new account, rather than renewing the old one. A former primary keeps its
  older certbot tree; if it becomes primary again, certbot may report "not due"
  from it, and the certificate synced from the peer stays in service until the
  renewal date.

## 9. Out of scope

- Certificates for IP addresses.
- A public certificate on phones' provisioning URL. Phones stay on the
  Veyra CA.
- WebRTC: Veyra has no browser phone yet.

## 10. Testing

**Unit tests.**
- Settings validation (names, wildcard only with DNS-01).
- Credentials never returned.
- Request file content.
- Firewall rendering with the challenge window.
- Status reading.
- Alert findings.
- Generator paths.
- The helper's certbot command line for each challenge and provider (run
  with a fake certbot).

**Live test.** A test-plan issue: DNS-01 with the district's DNS provider
on the staging authority first, then production. Check that a browser
without `veyra-ca.crt` shows no warning, that phones keep provisioning,
and that renewal and the alert work (forced with a short-lived staging
certificate).
