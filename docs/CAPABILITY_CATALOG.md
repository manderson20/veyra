# Capability packs: the pack author's guide

Configuration checks ([CONFIG_VERIFICATION.md](CONFIG_VERIFICATION.md))
compare the settings Veyra writes for a phone with **vendor data**: what each
model accepts on each firmware release. That data lives in **capability
packs**, one per vendor. This guide is for whoever writes or corrects a pack:
a Veyra contributor, a reseller, or a district administrator with a phone
Veyra doesn't cover yet.

A pack is data only. It never runs code, and a mistake in it can never stop a
phone from getting its files: at worst a save shows a wrong error, which an
administrator can override and report.

## 1. Where a pack lives

| Source | Where | Who |
|---|---|---|
| Built in | `provisioning/capabilities/<pack>/` in this repository | contributors, through pull requests |
| A module | the module's own directory, named in `module.toml` | module authors (docs/MODULE_DEVELOPMENT.md) |
| Imported | a ZIP under **Provisioning → Configuration Checks → Vendor data** | platform administrators, to try a pack before publishing it |

A pack id can only be loaded once: a module or an import that reuses a
built-in pack's id is refused, and the refusal is shown on the Coverage list.
When two packs cover the same model, an imported pack wins over a module's,
and a module's over a built-in one.

From the server console, `sudo veyra packs import <dir>` imports a pack
directory as the web page does, and `sudo veyra packs remove <id>` removes it.
Running services pick the change up at their next check.

`docs/examples/capability-pack-yealink-strict/` is an example: the built-in
Yealink T4x data with three made-up rules, for trying the checks.

A module ships a pack with:

```toml
[provisioning]
capabilities = "capabilities"   # a directory of packs inside the module
```

## 2. Layout

```
<pack>/
  pack.toml              the pack, and the devices it supports
  <family>/
    family.toml          the family: models, file format, version scheme
    <version>.toml       one file per firmware release
```

`veyra packs new <dir> --vendor acme --family desk` writes a skeleton.

### `pack.toml`

```toml
schema = 1

[pack]
id = "community.acme"          # lower-case segments; built-in packs use veyra.*
name = "Acme phones"
vendor = "acme"                # the templates' manufacturer, in lower case
version = "0.1.0"              # raise it with every change
author = "…"
license = "…"

# The devices the pack checks, exactly as the vendor's documentation lists
# them. A model no entry lists is "not covered" and is never checked.
[[supports]]
family = "desk"
models = ["D1", "D2"]
firmware = ">=1.0"
source = { title = "Acme Administrator Guide 1.0", section = "Supported models", page = "4" }
```

Every `supports` entry cites the vendor document that lists the models. Use
`provenance = "seeded-from-template"` only while the list still comes from
Veyra's own templates; the Coverage list then says so.

### `family.toml`

```toml
schema = 1
[family]
vendor = "acme"
family = "desk"                # the directory name
name = "Acme desk phones"
models = ["D1", "D2"]
format = "cfg"                 # xml | cfg | grandstream-p | algo-conf
version_scheme = "dotted"      # dotted | yealink (first number is the model prefix)
firmware_packaging = "family"  # family: one firmware for all models; model: per model
files = ["{mac}.cfg"]          # the template files the checker reads
templates = ["acme.desk"]      # templates that use this family (for `packs check`)
```

### The first release: every setting

```toml
schema = 1
[release]
version = "1.0"
revision = 1
# models = ["D1"]              # only with firmware_packaging = "model"

[release.sources.guide]
title = "Acme Administrator Guide 1.0"
version = "1.0"
url = "https://example.com/docs"   # the vendor's page; never a copy of the PDF

[param."line.{n}.transport"]
type = "enum"                  # bool | int | string | enum | ip | url | host
values = ["udp", "tcp", "tls"]
labels = { udp = "UDP", tcp = "TCP", tls = "TLS" }
default = "udp"
index = { min = 1, max = 4 }   # what {n} may be
index_max_by_model = { D1 = 2 }
note = "Transport of line n."
source = { ref = "guide", section = "Lines", page = "12" }
provenance = "vendor-doc"      # vendor-doc | observed-on-hardware | seeded-from-template
```

What each type checks:

| Type | Fields | Refuses |
|---|---|---|
| `bool` | `bool_values` (default `["0", "1"]`) | anything else |
| `int` | `range = { min, max }` | non-numbers, out of range |
| `enum` | `values`, `labels` | values not listed |
| `string` | `max_length`, `pattern` | too long, not matching |
| `host` | `max_length` | not a host name or IP address |
| `url` | `max_length` | not http(s), ftp(s) or tftp with a host |
| `ip` | | not an IP address |

Any entry can also have `allow_empty = true` and `not_models = [...]` (models
that ignore the setting). Names may hold `{n}` and `{m}` for indexes, as in
`reg.{n}.server.{m}.transport`.

### A later release: only the changes

```toml
schema = 1
[release]
version = "1.1"
extends = "1.0"

[release.sources.notes]
title = "Acme 1.1 Release Notes"

[added."line.{n}.srtp"]        # a full entry
type = "bool"
source = { ref = "notes", section = "New" }
provenance = "vendor-doc"

[changed."line.{n}.transport"] # only the fields that change
values = ["udp", "tcp", "tls", "dns-srv"]
source = { ref = "notes", section = "Changed" }

[deprecated."line.{n}.oldflag"]
replaced_by = "line.{n}.srtp"
source = { ref = "notes", section = "Deprecated" }

[removed."feature.gone"]
source = { ref = "notes", section = "Removed" }
```

A release applies from its own version up to the next release file. Use
`applies_to = ">=1.1, <1.3"` only when the vendor says so. A phone on firmware
newer than the newest release is checked against the newest one, with a note.

## 3. Rules for entries

- **Cite, don't copy.** Give the document's title, version, section and page.
  Never commit the vendor's PDF or long passages of it.
- **Never guess.** If the guide doesn't say what values a setting takes, keep
  it a `string` without rules and write the question in the pull request. A
  wrong rule stops administrators' saves; a missing one only leaves the
  setting unchecked.
- **Old releases stay.** A new firmware release is a new file. Correct an
  existing release only when its entry is wrong, and raise its `revision`.
- **`observed-on-hardware`** is for what you saw a real phone accept or
  refuse. Cite the model and firmware in `note`.

## 4. Seeding from Veyra's templates

`veyra packs seed <pack>/<family> --templates provisioning/templates` adds
every setting the family's templates write and the release lacks, as
`seeded-from-template` entries with no rules. It never changes an existing
entry. Seeding is a starting point: replace each seeded entry with a cited one
as you go through the guide.

## 5. Checking a pack

```
veyra packs validate <pack>
veyra packs check <pack> --templates provisioning/templates
```

`validate` lists every problem in the files. `check` runs the configuration
check on every template the families list, for every model and every
release, and exits with 1 when a release would refuse something an official
template writes. Fix the entry, or the template, before publishing.

In this repository, `backend/tests/test_capabilities.py` loads every built-in
pack and fails when an official template writes a setting a release lacks,
and `test_config_precheck.py` fails when an official template is refused.

## 6. Adding a firmware release with an AI assistant

[docs/prompts/add-firmware-release.md](prompts/add-firmware-release.md) is a
prompt to give Claude together with the vendor's release notes or admin guide.
It writes the release file with citations, runs the checks, and opens a pull
request that lists everything it could not confirm.

## 7. What reviewers look for

- Each `vendor-doc` entry's source exists and says what the entry says.
- Rules are not stricter than the document: an enum lists every value the
  guide gives, and a range is the guide's own.
- The release only lists changes, and nothing is removed from older files.
- `veyra packs check` passes, or the pull request explains each new refusal.
