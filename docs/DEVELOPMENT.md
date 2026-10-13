# Development

## 1. Environment

Development and testing use Proxmox VMs. These are **not production
systems**.

| Host | Initial role | vCPU | RAM | Disk | Notes |
|---|---|---|---|---|---|
| `veyra-dev1` | primary | 6 | 8 GB | 100 GB (root LV extended to 97 GB on 2026-10-12) | Ubuntu 26.04.1 LTS; development is done here. **Also runs a real Veyra installation** made by `installer/install.sh` on 2026-10-12 (`/opt/veyra`, services `veyra-api`/`veyra-worker`, NGINX, Asterisk 22.5.2); see `docs/installations/`. The development database `veyra_dev` and the installed database `veyra` coexist in the same PostgreSQL. |
| `veyra-dev2` | secondary | 6 | 8 GB | 100 GB | **Not provisioned yet** (owner, 2026-10-12) |

Both VMs are on the **same physical Proxmox host**, so the pair can test
application-level HA but not host failure.

**Ubuntu 24.04 test container:** LXD is initialised on veyra-dev1
(`lxd init --auto`). The stopped container `veyra-noble` holds the 24.04
installation from Milestone 1; `lxc start veyra-noble` to inspect it,
`lxc delete veyra-noble` to remove it, `lxc launch ubuntu:24.04 <name>` for a
fresh one. Copy the source in with `lxc file push` (a tarball without
`.git`, `node_modules` and `.venv`, with `frontend/out/` included).

**Running the installer from Claude Code:** the auto-mode permission
classifier refuses `sudo installer/install.sh` and `upgrade.sh`. The owner
runs them with `! cd ~/veyra && sudo installer/install.sh --yes`; the output
returns to the session. Read-only sudo commands, `--dry-run` runs and the
LXD container work are allowed.

> **Temporary development privilege:** `/etc/sudoers.d/90-veyra-dev` grants
> `itadmin` password-less sudo on veyra-dev1 so the coding agent can
> install packages. Remove it when it is no longer needed:
> `sudo rm /etc/sudoers.d/90-veyra-dev`.

GitHub access from veyra-dev1 uses a **repository-scoped deploy key**
(`~/.ssh/veyra_deploy`, host alias `github-veyra` in `~/.ssh/config`).

## 2. Toolchain (as installed on veyra-dev1)

| Tool | Version | Source |
|---|---|---|
| Python | 3.14.4 | Ubuntu 26.04 |
| PostgreSQL | 18.6 | Ubuntu 26.04 |
| Node.js / npm | 22.22.1 / 9.2.0 | Ubuntu 26.04 |
| ShellCheck | Ubuntu 26.04 package | |
| NGINX | 1.28.3 | Ubuntu 26.04 (installed by `install.sh`) |
| Asterisk | 22.5.2 | Ubuntu 26.04 universe (installed by `install.sh`; ADR 0010) |
| LXD | snap | for the Ubuntu 24.04 container |

Install them with:

```
sudo apt-get install python3-venv python3-dev build-essential libpq-dev postgresql nodejs npm shellcheck
```

## 3. Backend

```
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install --no-deps -e .

# local database (development credentials only)
sudo -u postgres psql -c "CREATE ROLE veyra_dev LOGIN PASSWORD 'veyra_dev' CREATEDB"
sudo -u postgres createdb -O veyra_dev veyra_dev

export VEYRA_ENV_FILE=/dev/null VEYRA_ENVIRONMENT=development \
  VEYRA_DATABASE_URL=postgresql+psycopg://veyra_dev:veyra_dev@127.0.0.1/veyra_dev \
  VEYRA_COOKIE_SECURE=false VEYRA_ALLOW_UNSIGNED_MODULES=true \
  VEYRA_MODULE_PATHS=$PWD/../modules VEYRA_TEMPLATE_PATHS=$PWD/../provisioning/templates
.venv/bin/veyra db upgrade
# the key that encrypts SIP secrets (the installer creates it on a server)
VEYRA_INSTALLATION_KEY_FILE=$PWD/.dev-installation.key .venv/bin/veyra installation-key generate
export VEYRA_INSTALLATION_KEY_FILE=$PWD/.dev-installation.key
.venv/bin/veyra setup-token
.venv/bin/uvicorn veyra.main:create_app --factory --reload --port 8000
```

OpenAPI documentation is served at `http://127.0.0.1:8000/api/docs`.

Checks (CI runs the same commands):

```
.venv/bin/ruff check veyra tests ../modules && .venv/bin/ruff format --check veyra tests ../modules
.venv/bin/mypy
.venv/bin/pytest -q          # needs PostgreSQL; drops and recreates veyra_test
```

Tests use `VEYRA_TEST_DATABASE_URL`
(default `postgresql+psycopg://veyra_dev:veyra_dev@127.0.0.1/veyra_test`).
The role needs `CREATEDB`.

New core migration:
`.venv/bin/alembic revision --autogenerate -m "…"`. Then review the
generated file and run `alembic check`.

## 3a. Versioning

`backend/veyra/version.py` is the single source of truth and
`frontend/package.json` must match (`tests/test_version.py` checks). Before
1.0 the scheme is:

| Event | Version |
|---|---|
| A milestone completes (in roadmap order: 0, 1, 2, 3, 4, 4b, 5, …) | minor bump: Milestone 4 → `0.4.0`, Milestone 4b → `0.5.0`, Milestone 5 → `0.6.0` |
| A fix shipped between milestones | patch bump: `0.4.1` |
| Work in progress on a milestone branch | next version with `-dev`: `0.5.0-dev` |
| Public release (Milestone 18) | `1.0.0`, then ordinary semantic versioning |

The installer names each release `<version>-<git revision>` (visible in the
sidebar tooltip and `/etc/veyra/install-state.json`) and refuses downgrades
of the numeric version. Bump with:

```
sed -i 's/^__version__ = .*/__version__ = "0.5.0-dev"/' backend/veyra/version.py
(cd frontend && npm version 0.5.0-dev --no-git-tag-version)
```

## 3b. Testing telephony without a phone

`tools/fakephone.py` is a standard-library SIP user agent that registers an
extension against the local engine, answers qualify pings and incoming
calls (after a configurable delay), and honours BYE. It sends no audio. It
exercises registration badges, Active Calls, click-to-dial and deploy-when-
idle from the server alone:

```bash
python3 -I tools/fakephone.py --user <endpoint-name> --password <sip-secret> \
    --local-port 5080 --answer-after 3 &
sudo asterisk -rx "pjsip qualify <endpoint-name>"          # registered within ~1 s
sudo asterisk -rx "channel originate PJSIP/<endpoint-name> application Wait 600"
sudo veyra config generate --deploy                         # or: config deploy N --when-idle
curl -s -u veyra:$(sudo cat /etc/veyra/secrets/ari_password) \
    -X DELETE http://127.0.0.1:8088/ari/channels/<channel-id>  # hang up
```

Click-to-dial through the production adapter:

```bash
sudo -u veyra /opt/veyra/current/backend/.venv/bin/python -c "
from veyra.core.config import Settings
from veyra.telephony import get_adapter
from veyra.telephony.asterisk.generator import CONTEXT_INTERNAL
a = get_adapter(Settings())
print(a.originate('<endpoint-name>', '*43', caller_id='*43 <*43>', context=CONTEXT_INTERNAL, timeout=30))
print(a.active_calls())"
```

A freshly registered phone shows as registered only after the engine's
first qualify ping (`qualify_frequency`, 60 s), because ARI's endpoint
state is derived from contact reachability, not from the REGISTER itself.

## 4. Frontend

```
cd frontend
npm ci
npm run dev        # http://localhost:3000; /api is proxied to 127.0.0.1:8000
npm run lint && npm run typecheck && npm test && npm run build   # build → out/
```

The UI is a static export served by NGINX in production
([ADR 0002](adr/0002-static-frontend.md)).

## 5. Installer

```
shellcheck -x -P SCRIPTDIR installer/*.sh installer/lib/*.sh installer/templates/*.sh
installer/tests/test_lib.sh
sudo installer/preflight.sh
sudo installer/install.sh --dry-run --yes
```

## 6. Dependency policy

* Pin exact versions (`requirements.txt`, `package-lock.json`, action SHAs in workflows).
* Only adopt versions that have been published for **at least two weeks**. For npm, regenerate the lockfile with npm 11 or newer and a date cutoff, for example `npx npm@11.6.2 install --before=<date>`. (Ubuntu's npm 9.2 can run `npm ci` from the lockfile but crashes when resolving dependencies.)
* **Security exception (recorded 2026-10-12):** `next` and `eslint-config-next` 16.3.8 (published 2026-09-30) are used instead of 16.3.6 because 16.3.6 has high-severity advisories fixed in 16.3.8. The lockfile was generated with `--before=2026-09-30T17:00:00Z`, so every package is at least 12 days old.
* ESLint stays on 9.x because the `eslint-config-next` 16.3 plugins do not support ESLint 10.
* Prefer the standard library and existing dependencies over new ones. Add a dependency only with a stated reason in the pull request. Current additions and their reasons: `segno` (QR codes for authenticator enrolment rendered server-side; pure Python, BSD, no transitive dependencies).
* Dependabot opens weekly update PRs. CI runs `pip-audit` and `npm audit` (production dependencies).

## 7. Git workflow

* `main` is the stable branch. Work happens on feature branches (`milestone-0`, `feature/...`) and is merged through pull requests.
* Use meaningful commit messages: an imperative subject and a body explaining *why*.
* Never commit secrets. `.gitignore` excludes `.env*`, `*.key`, `*.pem` and `secrets/`, and CI runs gitleaks. The only credentials in the repository are the throwaway local development and CI database credentials, which are allow-listed.
* Each milestone ends with a completion report in `docs/milestones/`.

## 8. Conventions

* The backend uses ruff (lint and format, line length 100), mypy, and type hints throughout.
* API errors are problem details. Every mutation is audited. Permissions are checked in the backend.
* Never fabricate data. When something is unavailable, return `null` or `unknown` and let the UI say so.
* Unfinished features are labelled with the milestone that delivers them. There are no buttons that do nothing.
