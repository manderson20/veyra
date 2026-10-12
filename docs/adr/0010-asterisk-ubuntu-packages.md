# 0010: Asterisk from the Ubuntu archive, not a Veyra-built package

**Status:** Accepted (2026-10-12)

**Context:** Milestone 1 had to decide whether Veyra installs the Ubuntu
`asterisk` package or ships its own build. Verified on 2026-10-12:

| Ubuntu | Archive component | Asterisk | Installed and verified by `install.sh` |
|---|---|---|---|
| 26.04 LTS (primary) | universe | 22.5.2 | veyra-dev1 |
| 24.04 LTS (secondary) | universe | 20.6.0 | LXD container `veyra-noble` |

Upstream 22.x was at 22.12.0 (release candidates) on the same date. Both
archive versions start, bind ARI to loopback with Veyra's configuration,
authenticate the Veyra ARI user and pass `verify.sh`. Veyra needs only
ARI, PJSIP, the dialplan and the standard applications in Milestones 3 to 8;
nothing planned depends on a feature newer than Asterisk 20.

A Veyra-built package would give one version everywhere and faster access to
upstream fixes, at the price of owning a C build, a package repository,
signing keys, security tracking and rebuilds for every Ubuntu release, with
the installer no longer working from a plain archive mirror. That is a large
permanent cost for a benefit Veyra does not need yet.

**Decision:** Install Asterisk from the Ubuntu archive. The installer
requires `asterisk`, `asterisk-modules` and `asterisk-core-sounds-en` and
accepts the version the release provides. Veyra's engine integration
(Milestone 3) targets the Asterisk 20 feature set so that both supported
Ubuntu releases work, and records the engine version it finds.

**Consequences:**

* No build infrastructure. Security updates arrive with `apt`, and the
  update manager (Milestone 12) treats Asterisk as a system component.
* `universe` packages are maintained by the community and Ubuntu Pro's
  `esm-apps`, not Ubuntu's main security team. `docs/SECURITY.md` and the
  production hardening milestone (17) must say so and recommend `esm-apps`
  or a maintained mirror for production hosts.
* Ubuntu 24.04 hosts run Asterisk 20 and Ubuntu 26.04 hosts run 22; a
  feature that needs 22 would make 24.04 a build-your-own case. Revisit this
  record if Milestone 3 or later finds such a feature, or if the archive
  version falls out of upstream support before the Ubuntu release does.
* The Ubuntu module set loads `cdr_radius` and `cel_radius`, which log a
  missing RADIUS client configuration at every start. Harmless; Milestone 3's
  generated `modules.conf` will not load them.
