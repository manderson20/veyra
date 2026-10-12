# Telephony Engine Evaluation: Asterisk vs FreeSWITCH

**Status:** Decided. **Recommendation:** Asterisk (22 LTS initially). See [ADR 0001](adr/0001-telephony-engine-asterisk.md).
**Date:** 2026-10-12. **Author:** Veyra core team (Milestone 0).

Veyra does not implement SIP signaling or media. It manages an established
open-source engine through an adapter (`backend/veyra/telephony/`). This
document compares the two candidates against Veyra's requirements and
records why Asterisk was selected. Only one engine is implemented initially.
The adapter boundary keeps a second engine possible later, but full support
for both is out of scope.

## How this evaluation was done

* Package availability was checked directly on `veyra-dev1` (Ubuntu
  26.04.1 LTS) with `apt-cache policy` and by listing the files in the
  `asterisk-modules` package. These results were observed, not assumed.
* Release and support dates come from the Asterisk project's published
  version table (docs.asterisk.org, "Asterisk Versions"), read on 2026-10-12.
* FreeSWITCH packaging and support terms come from SignalWire's installation
  documentation. The pages found were not dated 2026, so the terms should
  be re-checked before relying on them.
* Capability statements come from the projects' documentation and long-standing
  behaviour. Anything that has not been tested on Veyra hardware is marked as
  such.

## Observed on Ubuntu 26.04 (veyra-dev1)

| Item | Asterisk | FreeSWITCH |
|---|---|---|
| In the Ubuntu archive | **Yes**: `asterisk 1:22.5.2~dfsg…-1` (universe) | **No**: no `freeswitch` package in the archive |
| Modules Veyra needs | Present in `asterisk-modules`: `chan_pjsip`, `res_pjsip`, `res_pjsip_outbound_registration`, `res_ari`, `res_stasis`, `app_queue`, `app_voicemail`, `app_page`, `app_confbridge`, `app_mixmonitor`, `cdr_pgsql`, `cel_pgsql`, `res_config_pgsql`, `res_odbc`, `res_prometheus` | Upstream packages need a SignalWire Personal Access Token, or a build from source |
| Ubuntu 24.04 | Ubuntu archive ships an older Asterisk series. **Not yet verified for Veyra**; to be checked in Milestone 1 | Same token requirement |

"universe" means the package is maintained by the community, not Canonical.
Security fixes reach universe less predictably than they reach `main`, so this
is tracked as a risk below.

## Comparison

| Criterion | Asterisk | FreeSWITCH |
|---|---|---|
| **Licensing** | GPLv2 (Sangoma also offers commercial licenses). Veyra controls Asterisk over network APIs and generated configuration files and does not link to it, so Veyra's own license choice is unconstrained (see [LICENSING.md](LICENSING.md)). | MPL 1.1. Equally unconstraining for an API-driven manager. |
| **Support lifecycle** | Published and predictable: an LTS release every two years, with four years of full support plus one year of security fixes. 22 LTS: released 2024-10-16, fully supported to 2028-10-16, end of life 2029-10-16. 24 LTS is scheduled for 2026-10-15 and is supported to 2031. | No comparable published LTS schedule for the community edition. SignalWire describes the community edition as free but unsupported, with updates arriving more slowly than in its commercial editions. |
| **Active development** | Active, with monthly point releases and regular security advisories (Sangoma, open GitHub). | Active, with stewardship centred on SignalWire's commercial products. |
| **Packaging** | In the Ubuntu archive (universe). Upstream does not publish .debs. Source builds are well documented. | Prebuilt packages need a SignalWire account token; otherwise build from source. This is an unattended-install and supply-chain burden for a self-hosted product that must not depend on an external service. |
| **SIP** | PJSIP stack: registrations, outbound registration to carriers, TLS/SRTP, NAT handling, multiple transports. | Sofia-SIP: very capable, especially at carrier scale. |
| **PBX features** | Mature built-ins: queues (`app_queue`), voicemail with IMAP/ODBC options, paging (`app_page`), conferencing (ConfBridge), recording (MixMonitor), parking, pickup, BLF/hints, MWI. | Most features exist (mod_callcenter, mod_voicemail, mod_conference) but are often assembled from dialplan/XML. |
| **Configuration management** | Plain config files with `#include`, plus optional Realtime from PostgreSQL. Generated files are easy to diff, validate and roll back. | XML configuration that can be served dynamically (mod_xml_curl). Powerful, but ties call processing to the management service's availability unless cached carefully. |
| **APIs / events** | **ARI** (REST + WebSocket), designed for external control and status. AMI (legacy TCP) is not needed and is disabled. | ESL (event socket): powerful, but a bespoke TCP protocol. |
| **Multi-tenancy** | No native tenant concept. Isolation is achieved by generated contexts, endpoint naming and dialplan, which Veyra must generate and test carefully. | "Domains" give a natural multi-tenant model (used by FusionPBX). **This is FreeSWITCH's strongest advantage.** |
| **High availability** | No built-in clustering. Active/passive with replicated configuration and a database is the established pattern; calls in progress are lost on failover. | Same in practice. Call recovery (`mod_sofia` recovery) can preserve some calls but needs shared state and careful testing. |
| **Queues / IVR / voicemail / paging / recording** | All built in and widely deployed. | All available. Queues via mod_callcenter. |
| **Debugging** | `asterisk -r`, `pjsip set logger`, well known to administrators, large community. | `fs_cli`, sofia tracing: good tools, smaller administrator pool. |
| **Upgrade complexity** | LTS-to-LTS upgrades require configuration review. Generated configuration reduces the risk. | Upgrades largely depend on the commercial channel for timely builds. |
| **Security maintenance** | Public advisories (GHSA), regular fix releases. Ubuntu universe lag is a risk (see below). | Fixes reach the community edition more slowly by SignalWire's own description. |
| **Audience fit** | Familiar to the target audience (schools, municipalities, small and medium businesses, MSPs), including people coming from FreePBX. | Familiar to FusionPBX and carrier users. |

## Decision

**Asterisk**, starting with the 22 LTS series shipped by Ubuntu 26.04.

The deciding factors:

1. **No external dependency to install it.** It is in the Ubuntu archive. FreeSWITCH packages require a vendor account token, which conflicts with "no mandatory external service" and makes unattended installation fragile.
2. **A predictable, published support lifecycle.** This matters for schools and municipalities that plan multi-year deployments.
3. **ARI** is a clean, documented interface for status and control, and maps directly onto the adapter interface.
4. **Generated configuration files** fit the "database is authoritative, deploy via a controlled service" design. Telephone service keeps running when the Veyra web application is down, because Asterisk does not depend on Veyra or PostgreSQL at call time.
5. **Built-in PBX features** cover the module list (queues, voicemail, IVR, paging, recording, conferencing).

The main cost is multi-tenancy. Asterisk has no native tenant boundary, so
Veyra must generate isolated contexts and endpoints and prove the isolation
with tests before multi-tenancy is enabled (Milestone 14).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Ubuntu universe security updates may lag upstream | Milestone 1 evaluates building a Veyra-maintained Asterisk package from upstream LTS source, with the Ubuntu package as the default. Security advisories will be tracked. The update policy for the telephony engine is managed separately (see UPDATE_MANAGEMENT.md). |
| Asterisk 24 LTS releases on 2026-10-15; Ubuntu 26.04 stays on 22 | 22 is fully supported to 2028-10-16. Migrating to 24 will be scheduled once the adapter has integration tests. |
| Tenant isolation is not native | Generated per-tenant contexts, unique endpoint names (enforced globally in the schema), and isolation tests before activation (Milestone 14). |
| Active calls are lost on HA failover | Documented (HA_ARCHITECTURE.md). No zero-downtime claims. |

## Capability differences to keep isolated in the adapter

* Endpoint status: Asterisk ARI `/endpoints` versus FreeSWITCH `sofia status`.
* Configuration: Asterisk generates files under `/etc/asterisk/veyra/` and reloads modules. FreeSWITCH would serve XML.
* Tenancy: Asterisk uses contexts and naming conventions. FreeSWITCH would use domains.

The adapter interface (`TelephonyAdapter`) reports a `Capability` set, so
the UI and services never assume a feature exists.

## Sources

* Asterisk Versions (release and support table): https://docs.asterisk.org/About-the-Project/Asterisk-Versions/
* SignalWire, Installing FreeSWITCH (token requirement and editions): https://developer.signalwire.com/guides/installing-freeswitch-or-freeswitch-advantage
* SignalWire, Personal Access Token for FreeSWITCH packages: https://developer.signalwire.com/freeswitch/FreeSWITCH-Explained/Installation/HOWTO-Create-a-SignalWire-Personal-Access-Token_67240087
* Local observation: `apt-cache policy asterisk freeswitch` and `dpkg -c asterisk-modules_*.deb` on veyra-dev1, 2026-10-12.
