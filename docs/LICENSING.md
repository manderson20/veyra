# Licensing Evaluation

**Status:** Undecided. **The decision belongs to the project owner** before
publication (Milestone 18). The repository stays private.

## Current state

The repository was created with a **GPL-3.0** `LICENSE` file. That differs
from the two candidates named in the development directive (AGPLv3 and
Apache 2.0). The file has been left unchanged until the owner decides.
Source files do not yet carry license headers, and the example module
declares `GPL-3.0-or-later` to match the current file.

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
