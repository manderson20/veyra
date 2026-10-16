# Licensing Evaluation

**Status:** Decided 2026-10-12: **AGPL-3.0-or-later** ([ADR 0013](adr/0013-license-agpl.md)).
The owner delegated the choice to the team ("change as necessary"); the
evaluation below is kept as the record of why. The repository stays private
until Milestone 23 (the public release).

## Current state

`LICENSE` is the AGPL-3.0 text. Python, TypeScript and shell sources carry
`SPDX-License-Identifier: AGPL-3.0-or-later` headers; `pyproject.toml`,
`package.json` and the example module manifest declare the same. Before
accepting outside contributions (Milestone 23) adopt DCO sign-off.

The repository was originally created with a GPL-3.0 file, which was never
the intended license.

## Candidates

| | AGPL-3.0 | Apache-2.0 | GPL-3.0 (current file) |
|---|---|---|---|
| Copyleft | Strong, including network use: hosted or MSP-modified versions must offer source to users | None (permissive) | Strong, but no network clause: a hosted, modified Veyra need not release source |
| Fit with "future hosted deployments" by third parties | Keeps improvements open | Allows closed forks and closed hosted offerings | Allows closed hosted offerings |
| Commercial adoption by MSPs and vendors | Some organizations avoid AGPL | Easiest | Moderate |
| Patent grant | Yes (v3) | Yes, explicit | Yes (v3) |
| Third-party modules | Modules talk to the core through an HTTP API (service runtime) and so are not derivative works, which allows proprietary modules. In-process official modules would follow the core license. | No restriction | As AGPL, minus the network clause |

## Dependency compatibility

* **Asterisk (GPLv2):** Veyra does not link to Asterisk. It controls it over ARI and generated configuration files, so it is a separate program and Asterisk's license does not constrain Veyra's. Asterisk itself remains GPLv2 when redistributed in packages.
* **Python dependencies:** FastAPI, Starlette, Pydantic, SQLAlchemy, Alembic, uvicorn, psycopg (LGPL-3.0), argon2-cffi, cryptography (Apache-2.0/BSD) and Jinja2 are all compatible with AGPL-3.0, GPL-3.0 and Apache-2.0 distribution. psycopg's LGPL permits use from Apache-2.0 code.
* **Frontend:** Next.js and React (MIT) are compatible with all three.
* **PostgreSQL and NGINX** (permissive) are separate programs.

## Recommendation for the owner's decision

* For a community project whose goal is to stay open even when others host it: **AGPL-3.0-or-later**.
* For maximum adoption, including closed commercial derivatives: **Apache-2.0**.

Either way, replace `LICENSE` and add SPDX headers in the same change, and
adopt a contributor agreement (DCO sign-off is the lightest option) before
accepting outside contributions.
