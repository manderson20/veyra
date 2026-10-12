# Provisioning Templates

Veyra generates phone configuration files from **templates**. Templates are
data, not code: they are rendered in a sandbox and cannot run server-side
code, read files or reach the network.

Status (Milestone 0): the specification, the catalog, validation, preview,
export and import (API), and the official Poly VVX 411/450 templates. Serving
files to phones over HTTPS, assigning templates to devices and testing on
real hardware come in **Milestone 9**. The Poly templates are marked
`experimental` until they have been verified on real phones.

## 1. Sources and precedence

| Source | Where it lives | Who changes it | Updated by Veyra? |
|---|---|---|---|
| official | `provisioning/templates/official/` in a release | Veyra project (reviewed and tested) | Yes, with template updates |
| community | `<template path>/community/` | Community contributors, clearly labelled | Yes, if the administrator opts in |
| local | Database (`provisioning_templates`) | The administrator | **Never** |

* Official template keys are reserved: a community or local template cannot take an official key.
* **To customize an official template**, create a local template with its own key whose `parent` is the official template, and override only what you need. The official template is never modified, so official updates and local customizations never conflict.
* Local templates record `parent_version`. When an official parent is updated, the catalog flags the local template (`parent_updated: true`) so the administrator can compare and adopt changes. Nothing is merged automatically.

## 2. Template directory

```
poly-vvx-411/
  template.toml
  phone.cfg.j2        template sources (.j2 .cfg .xml .json .ini .txt .conf .tmpl), ≤ 256 KB each
```

## 3. `template.toml` (spec_version 1)

```toml
spec_version = 1
features = ["single_line", "ntp", "vlan"]

[template]
key = "poly.vvx.411"            # lower-case segments separated by . or -
name = "Poly VVX 411"
version = "0.1.0"               # semantic version
manufacturer = "Poly"
models = ["VVX 411"]            # required unless abstract
abstract = false                # abstract templates are only used as parents
parent = "poly.vvx.base"        # optional, up to 8 levels
parent_version = "0.1.0"        # parent version this was derived from
firmware = "UC Software 5.9 / 6.x"
status = "experimental"         # stable | experimental | deprecated
description = "…"

[[files]]
name = "veyra-{mac}.cfg"        # output filename pattern: {mac} {mac_upper} {model_slug}
source = "phone.cfg.j2"
format = "xml"                  # xml | json | ini | cfg | text  (xml is auto-escaped)

[[variables]]                   # extra, template-specific variables
name = "sip_transport"
default = "UDPOnly"
pattern = "^(UDPOnly|TCPOnly|TLS|DNSnaptr)$"
sensitive = false

[defaults]                      # override defaults of core or inherited variables
ntp_server = "time.example.org"
```

**Inheritance:** a child inherits its parent's files, variables and
defaults. A child file with the same output `name` replaces the parent's.
Inside a source file, `{% extends "<parent-key>/<file>" %}` extends a
specific ancestor's file, and `{% block %}` overrides parts of it (the Poly
model templates do this). Plain names (`{% include "macros.j2" %}`) resolve
from the child up the chain. Nothing outside the chain can be loaded.

## 4. Variables

Approved core variables (`GET /api/v1/provisioning/variables`):

| Variable | Type | Notes |
|---|---|---|
| `extension_number` | string | required, `[0-9*#+]` |
| `sip_username` | string | required |
| `sip_password` | string | required, **sensitive** |
| `sip_server` | string | required, host or address |
| `sip_port` | integer | default 5060 |
| `display_name`, `caller_id` | string | ≤ 80 characters |
| `timezone` | string | IANA name (e.g. `America/Chicago`) |
| `ntp_server` | string | default `pool.ntp.org` |
| `vlan_id` | integer | blank = no VLAN |
| `provisioning_url` | string | http(s) URL |

Device facts available to templates and filenames: `mac` (12 lower-case hex
digits), `mac_upper`, `model`.

Templates may declare additional variables. They cannot redefine core or
device variables. Every value is validated (type, length, pattern, no
control characters) before rendering, and unknown values are rejected.

Filters: the standard Jinja2 filters plus `utc_offset_seconds` (time zone →
current UTC offset in seconds) and `bool01`.

## 5. Security rules

* Rendering uses `ImmutableSandboxedEnvironment` with `StrictUndefined` and **no globals** (`range`, `cycler`, `lipsum` and similar are removed). Attribute tricks such as `''.__class__` raise a security error.
* Validation rejects templates that reference undeclared variables.
* Output filenames must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. Template source paths cannot be absolute or contain `..`. Symbolic links are rejected.
* **Secrets:** `sip_password` (and any variable marked `sensitive`) is masked as `********` in previews. Templates cannot carry a default `sip_password`, and exports drop defaults for sensitive variables. Rendered files containing credentials are never logged.
* Production delivery (M9) will be HTTPS only, authenticated per device, and rate-limited.

## 6. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/provisioning/templates` | Catalog, including load errors and `parent_updated` flags |
| GET | `/api/v1/provisioning/templates/{key}` | Resolved chain, files, variables, defaults (sensitive values omitted), validation |
| POST | `/api/v1/provisioning/templates/{key}/preview` | Render with sample values; secrets masked |
| GET | `/api/v1/provisioning/templates/{key}/export` | Portable JSON export (no secrets) |
| POST | `/api/v1/provisioning/templates/validate` | Dry-run an import |
| POST | `/api/v1/provisioning/templates/import` | Store as a local template |

The export format is
`{"format": "veyra-provisioning-template", "format_version": 1, "manifest": {...}, "sources": {"file": "text"}}`.

On the command line, `veyra templates validate <dir> [--base <root>]` checks
a template directory.

## 7. Community contribution workflow (design)

1. The administrator creates and tests a local template.
2. They export it (JSON, no secrets) and submit it to the Veyra repository as a pull request under `provisioning/templates/community/<key>/`, with the models and firmware tested.
3. Maintainers review it. CI validates and renders it with sample data.
4. Accepted templates ship labelled **community**. Templates promoted to **official** after hardware testing move to `official/` and get `status = "stable"`.

## 8. Official templates

| Key | Models | Status | Notes |
|---|---|---|---|
| `poly.vvx.base` | (abstract) | experimental | Master `{mac}.cfg` plus `veyra-{mac}.cfg` with registration, SNTP and VLAN |
| `poly.vvx.411` | VVX 411 | experimental | Initial hardware test target |
| `poly.vvx.450` | VVX 450 | experimental | Initial hardware test target |

Known limitations of the Poly templates:

* Time zones are written as a fixed UTC offset computed at render time, with DST disabled. Files must be regenerated after DST changes until proper DST rules are added (M9).
* Single line only. Line keys, BLF, directory and firmware upgrade parameters are planned for M9.
* Not yet verified on VVX 411/450 hardware.
