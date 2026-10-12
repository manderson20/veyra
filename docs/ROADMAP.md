# Roadmap

Each milestone delivers scope, acceptance criteria, implementation, tests,
documentation, a completion report and a list of known limitations.
Milestones are not skipped, and each needs the project owner's approval
before the next begins.

Versions: completing a milestone releases `0.<n>.0`, where n counts
completed milestones in the order below (see
[DEVELOPMENT.md](DEVELOPMENT.md) §Versioning); Milestones 0 to 3 shipped as
`0.1.0-dev.0` before the scheme existed.

| # | Milestone | Version | Status |
|---|---|---|---|
| 0 | Architecture, repository foundation, modular framework | 0.1.0-dev.0 | **Complete, approved 2026-10-12** ([report](milestones/MILESTONE_0_REPORT.md)) |
| 1 | Automated Ubuntu installation (run and harden the installer on veyra-dev1/dev2; 24.04 verification; Asterisk packaging decision) | 0.1.0-dev.0 | **Complete, approved 2026-10-12**; veyra-dev2 installation deferred until that VM is provisioned ([report](milestones/MILESTONE_1_REPORT.md)) |
| 2 | Backend, frontend, database and authentication (hardening, password reset, sessions UI, MFA design) | 0.1.0-dev.0 | **Complete, approved 2026-10-12** ([report](milestones/MILESTONE_2_REPORT.md)) |
| 3 | Telephony engine integration (deployer service, config generation, ARI status, reload, rollback) | 0.1.0-dev.0 | **Complete, approved 2026-10-12** ([report](milestones/MILESTONE_3_REPORT.md)) |
| 4 | Extension management (installation key and SIP secret encryption, numbering plan, extension CRUD, Extensions UI) | 0.4.0 | **Complete, approved 2026-10-12** ([report](milestones/MILESTONE_4_REPORT.md)) |
| 4b | Multi-factor authentication: TOTP, recovery codes, per-role policy ([design](MFA_DESIGN.md), [ADR 0012](adr/0012-mfa-approach.md)); passkeys in M17 | 0.5.0 | **Complete, approved 2026-10-12** ([report](milestones/MILESTONE_4B_REPORT.md)) |
| 5 | SIP registration and internal calling (live registrations, active calls, **click-to-dial API**: originate a call from a user's extension over ARI); deploy-mode drop-down on the Deploy changes button: deploy now (default) or wait until no calls are active (timeout, visible waiting state; suggested for SIP transport changes) | 0.6.0 | **In progress** (started 2026-10-12); owner requests: deploy mode, click-to-dial |
| 6 | SIP trunks and routing (inbound/outbound, DIDs, time conditions, loop detection) | 0.7.0 | |
| 6b | **Veyra Companion** browser extension (Chrome/Edge first; macOS desktop later if needed): sign in with Veyra credentials (MFA included), click-to-dial any number (desk phone rings, then the call is placed), directory lookup, incoming caller ID pop-up, personal speed dials and quick buttons stored in the user's Veyra profile | 0.8.0 | Owner request 2026-10-12 (replaces a Metaswitch desktop dialler) |
| 7 | Voicemail and IVR (voicemail-to-email, MWI, prompts) | 0.9.0 | |
| 8 | Ring groups and queues | 0.10.0 | |
| 9 | Device provisioning and custom templates (HTTPS delivery, hardware validation on Poly VVX 411/450) | 0.11.0 | |
| 10 | Reporting and monitoring (CDR, dashboards, metrics) | 0.12.0 | |
| 11 | Module management and independent updates (service runtime, package install, module settings UI) | 0.13.0 | |
| 12 | Software update management (download/approve/apply, maintenance windows, release signing) | 0.14.0 | |
| 13 | Integrations | 0.15.0 | |
| 14 | Multi-tenancy (telephony isolation and tests before activation) | 0.16.0 | |
| 15 | Centralized instance management | 0.17.0 | |
| 16 | High availability implementation and testing | 0.18.0 | |
| 17 | Production hardening (backups, encryption, retention, security review, emergency calling validation) | 0.19.0 | |
| 18 | Public release preparation (license decision, disclosure policy, packaging) | 1.0.0 | |

Planned UI areas (shown in navigation as "coming later" with their
milestone): Extensions (M4), Devices (M9), SIP Trunks (M6), Inbound and
Outbound Routing (M6), IVR (M7), Ring Groups (M8), Call Queues (M8),
Voicemail (M7), Paging (M8), Call History (M10), Call Recording (M10).
