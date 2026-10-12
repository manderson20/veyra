# Roadmap

Each milestone delivers scope, acceptance criteria, implementation, tests,
documentation, a completion report and a list of known limitations.
Milestones are not skipped, and each needs the project owner's approval
before the next begins.

| # | Milestone | Status |
|---|---|---|
| 0 | Architecture, repository foundation, modular framework | **Complete, approved 2026-10-12** ([report](milestones/MILESTONE_0_REPORT.md)) |
| 1 | Automated Ubuntu installation (run and harden the installer on veyra-dev1/dev2; 24.04 verification; Asterisk packaging decision) | **Complete, approved 2026-10-12**; veyra-dev2 installation deferred until the host is reachable ([report](milestones/MILESTONE_1_REPORT.md)) |
| 2 | Backend, frontend, database and authentication (hardening, password reset, sessions UI, MFA design) | **In progress** (started 2026-10-12) |
| 3 | Telephony engine integration (deployer service, config generation, ARI status, reload, rollback) | |
| 4 | Extension management (SIP secret encryption, numbering plan) | |
| 5 | SIP registration and internal calling (live registrations, active calls) | |
| 6 | SIP trunks and routing (inbound/outbound, DIDs, time conditions, loop detection) | |
| 7 | Voicemail and IVR (voicemail-to-email, MWI, prompts) | |
| 8 | Ring groups and queues | |
| 9 | Device provisioning and custom templates (HTTPS delivery, hardware validation on Poly VVX 411/450) | |
| 10 | Reporting and monitoring (CDR, dashboards, metrics) | |
| 11 | Module management and independent updates (service runtime, package install, module settings UI) | |
| 12 | Software update management (download/approve/apply, maintenance windows, release signing) | |
| 13 | Integrations | |
| 14 | Multi-tenancy (telephony isolation and tests before activation) | |
| 15 | Centralized instance management | |
| 16 | High availability implementation and testing | |
| 17 | Production hardening (backups, encryption, retention, security review, emergency calling validation) | |
| 18 | Public release preparation (license decision, disclosure policy, packaging) | |

Planned UI areas (shown in navigation as "coming later" with their
milestone): Extensions (M4), Devices (M9), SIP Trunks (M6), Inbound and
Outbound Routing (M6), IVR (M7), Ring Groups (M8), Call Queues (M8),
Voicemail (M7), Paging (M8), Call History (M10), Call Recording (M10).
