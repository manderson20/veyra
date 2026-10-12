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

## NAT

When phones or trunks are on the other side of NAT, PJSIP needs
`external_media_address`, `external_signaling_address` and `local_net`.
These are the external addresses and local networks in the SIP settings (M3); the generated transports carry them. Avoid SIP ALG on routers.

## Firewall

The installer **does not change firewall rules** (it reports whether ufw is
active). A recommended ufw profile will be generated from the active
configuration in M5/M17. Never expose the admin interface, ARI, AMI or
PostgreSQL to the internet.
