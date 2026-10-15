# Networking

Network requirements are derived from the actual configuration. This page
lists what Veyra configures **today** and what later milestones will add.
Always confirm with `ss -ltnup` on the server.

## Listeners after installation (Milestone 0/1 configuration)

| Service | Port | Bound to | Exposed? |
|---|---|---|---|
| NGINX HTTPS (admin UI and API) | 443/TCP | private addresses + 127.0.0.1 (configurable: `--listen`, `--allow-public-admin`) | LAN only by default |
| NGINX HTTP (redirect to HTTPS) | 80/TCP | same as above | LAN only by default |
| veyra-api | 8100/TCP | 127.0.0.1 | No |
| PostgreSQL | 5432/TCP + local socket | localhost (Ubuntu default) | No |
| Asterisk ARI (HTTP) | 8088/TCP | 127.0.0.1 | No |
| Asterisk AMI | 5038/TCP | disabled | No |
| SSH | 22/TCP | unchanged by Veyra | Administrator's choice |

## Added in later milestones (to be derived from configuration)

| Purpose | Default (Asterisk) | Milestone | Notes |
|---|---|---|---|
| SIP signaling | 5060/UDP+TCP, 5061/TCP (TLS, off by default) | **M3** (transports are generated now; phones register from M5) | Generated PJSIP transports from the SIP settings (System → Telephony Engine); read the deployed revision, do not assume |
| RTP media | 10000–20000/UDP (`rtp.conf`) | **M3** | Range set in the SIP settings; firewall rules must follow it |
| Phone provisioning | HTTPS 443 (dedicated path or port) | M9 | HTTP only if explicitly enabled for phones that need it |
| HA replication and control | 5432/TCP between nodes, VRRP (IP proto 112) | M16 | Peer addresses only |

The Companion browser extension uses the same HTTPS port: REST with bearer
tokens and one WebSocket per signed-in browser at `/api/v1/events/calls`
(NGINX passes the `Upgrade` headers for that path only). The browser must
trust the server certificate; an extension cannot click through a warning.

## NAT

When phones or trunks are on the other side of NAT, PJSIP needs
`external_media_address`, `external_signaling_address` and `local_net`.
These are the external addresses and local networks in the SIP settings (M3); the generated transports carry them. Avoid SIP ALG on routers.

## Firewall

Since 0.14.0 Veyra has its own firewall (System → Firewall,
[FIREWALL_TRUST.md](FIREWALL_TRUST.md)): one nftables table, `inet veyra`,
that only **drops** traffic (banned, blocked and blocklist-feed addresses,
and, per service, anything not on the allow list when a service is limited
to it). It is off after installation. The allow list (this server, the SIP
local networks, trunk addresses, and your own entries) is checked first and
is never banned. Other firewalls (ufw, LXD, Docker) keep working; an
`accept` elsewhere cannot override Veyra's drops. The ports it uses for each
service come from the deployed SIP settings (`sip`, `rtp`), 80/443 (`web`,
including provisioning) and the SSH ports in the firewall settings. Never
expose ARI, AMI or PostgreSQL to the internet.
