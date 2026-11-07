# Configuration verification

Status: **approved 2026-11-07**, being built on branch `config-verification` (slices in §10). Owner's answers in §0. Builds on
[DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) (templates spec 2,
profiles, firmware), [PROVISIONING_TEMPLATES.md](PROVISIONING_TEMPLATES.md),
[PROVISIONING_BREADTH.md](PROVISIONING_BREADTH.md) (variables, official
templates, Base File Edit #372) and
[PROVISIONING_HARDWARE_CHECKS.md](PROVISIONING_HARDWARE_CHECKS.md).

## 0. Owner decisions (2026-11-07)

- **Two layers of variables.** A phone's file holds the *vendor's
  parameters* (`reg.1.address`). Veyra fills them from *Veyra fields*: data
  each phone has its own value of (the extension number, the SIP user, the
  MAC), already stored in the database and listed in
  `provisioning/catalog.py`. The checker checks the fields, not every
  phone's values (§3.0).
- **A precheck, not a check of every phone.** The checker runs against the
  vendor catalog when a template, profile, Base File Edit or variable is
  saved. It does not render and check each phone.
- **Firmware follows the vendor's packaging.** One release file covers
  several models when the vendor ships one firmware for them (Poly UC
  Software), or one model when the vendor ships firmware per model (§2.2).
- **Enforce is the default** for every installation, new and upgraded.
  Administrators can change it.
- **Modes are per profile at the finest.** There is no per-phone switch;
  build a test profile for phones that should not be checked (§5).
- **A check window.** Every check opens a window with a progress bar. When
  it is clean, the window says so and waits for **OK**. Otherwise it lists
  each item with the setting, the Veyra field that fills it, the value, and
  the values the setting accepts (§7.1).
- **Permissions.** Who may override a finding and who may change a mode are
  permissions in the user roles (§8).
- **Composite settings** take the safest route: they are checked with the
  extreme values and always marked for review (§3.0).
- **Vendor packs.** Each vendor's checks are a self-contained pack, built
  one vendor at a time. A pack states the devices it supports, taken from
  that vendor's documentation and cited. Other developers can build and
  ship their own packs (§2.0).

## 1. Goals

1. **Check before it reaches a phone.** When an administrator changes
   anything that ends up in a file a phone downloads, Veyra checks each
   setting against what that model, on the firmware it will run, accepts.
2. **The checker can be wrong, so the administrator decides.** Errors stop a
   save until the administrator overrides them with a reason. Warnings and
   "not checked" never stop anything.
3. **Data, not emulation.** The checker reads a catalog of parameters per
   vendor, family and firmware release. People write the catalog by hand,
   with AI help, from the vendor's admin guide and release notes, and commit
   it through pull requests. Veyra never scrapes vendor documents.
4. **Modular by firmware release** (owner, 2026-11-07). A new firmware
   release adds a file. The files for older releases stay in place, and a
   phone still on an older release is checked against that release's file.
   Checker rules work the same way: a new rule is added next to the old ones
   and never changes how an existing catalog file is read (§2.6, §3.4).
5. **The administrator can turn it off** (owner, 2026-11-07: someone who is
   "free willing it" does not want it). Checks can be off, advisory or
   enforced, for the whole installation, for one organization or for one
   profile (§5).
6. **Never in the way of a phone.** Serving files (`serve.py`) never runs
   the checker and never refuses a file because of it (§4.3).

Not goals: emulating firmware, proving a configuration works (only a
hardware check does that), and checking files Veyra does not render (such as
firmware images, the phone book and ring tones).

## 2. The capability catalog

### 2.0 Vendor packs

The catalog is made of **packs**, one per vendor (or one per vendor line
when a vendor's lines have nothing in common). A pack holds its families
and their release files (§2.1–§2.5), plus `pack.toml`:

```toml
schema = 1

[pack]
id = "veyra.yealink"              # like a module id: lower case, dot segments
name = "Yealink phones"
vendor = "yealink"
version = "0.1.0"                 # the pack's own version, raised with every change
author = "Veyra Project"
license = "AGPL-3.0-or-later"

# The devices the pack checks, as the vendor's documentation lists them.
# A model the pack does not list is "not covered": it is never checked,
# even if a family's models happen to match it.
[[supports]]
family = "t4x"
models = ["T42U", "T43U", "T44U", "T44W", "T46U", "T48U"]
firmware = ">=86"
source = { title = "Yealink SIP IP Phones Administrator Guide V86", section = "Supported models", page = "TBD" }
```

The loader rejects a pack whose `supports` entry names a family the pack
lacks, or whose family lists a model that no `supports` entry covers. It
also rejects a `supports` entry without a source.

**Where packs come from**, in this order (a later pack id never replaces
an earlier one; the loader refuses the duplicate and logs it):

1. **Built in:** `provisioning/capabilities/<pack>/` in this repository,
   reviewed through pull requests. Poly and Yealink come first, the other
   vendors one at a time after that.
2. **Modules:** a module ships a pack with `[provisioning] capabilities =
   "capabilities"` in `module.toml`. Signing and trust are the same as for
   any module (docs/MODULE_DEVELOPMENT.md §6). This is the path for other
   developers. A pack is data only, so no code runs.
3. **Local:** an administrator imports a pack directory or archive under
   Provisioning → Checks → Packs, the same way local templates are
   imported. This is for testing a pack before it is published.

A developer builds a pack with `veyra-cli provisioning pack new <vendor>`
(writes the skeleton), `pack validate <dir>` (the loader's checks), `pack
seed <dir> --template <key>` (§2.7) and `pack check <dir>` (runs the checker
on every template the pack's families list). `docs/CAPABILITY_CATALOG.md`
is the pack author's guide.

**Coverage page.** Provisioning → Checks → Coverage lists every pack with
its version, where it came from, the models and firmware it supports and
their sources. It also lists the models in use in Veyra that no pack covers,
so it is clear which phones are checked and which are not.

### 2.1 Layout

```
provisioning/capabilities/
  poly/vvx/family.toml           family: vendor, models, formats, files, version scheme
  poly/vvx/6.3.0.toml            first release: the full parameter list
  poly/vvx/6.4.0.toml            extends 6.3.0: only what changed
  poly/vvx/6.4.3.toml            extends 6.4.0
  yealink/t4x/family.toml
  yealink/t4x/86.toml            Yealink release line 86 (x.86.0.y)
  yealink/t4x/86.80.toml         extends 86
```

These are TOML files, like `template.toml`. One directory per family, one
`family.toml` and one file per firmware release. The release files form a
chain through `extends`. The loader resolves each release into a flat
parameter table, so a lookup never walks the chain at check time.

**Adding a release** means adding one small file that lists only the
changes since the previous release, so the pull request is the change. **A
correction** to an existing release edits that release's file and raises its
`revision`. Releases that extend it pick the correction up unless they
override that parameter themselves.

Each pack is self-contained: a release file can only extend a release in
the same pack (§2.0).

### 2.2 `family.toml`

```toml
schema = 1

[family]
vendor = "poly"                   # lower case; matches the template's manufacturer
family = "vvx"
name = "Poly VVX (UC Software)"
models = ["VVX 150", "VVX 250", "VVX 350", "VVX 411", "VVX 450"]
format = "xml"                    # xml | cfg | grandstream-p | algo-conf
# How versions compare: "dotted" compares each dot-separated number in turn.
# "yealink" ignores the model prefix (the first number; for example 66 or
# 108) and compares the rest, because the same release line carries a
# different prefix on each model.
version_scheme = "dotted"
# How the vendor ships firmware: "family" (one release for every model
# listed, as Poly UC Software does) or "model" (each model has its own
# firmware and release files list the models they cover, as Yealink does).
firmware_packaging = "family"
# Files of the family's templates that the checker reads, as their filename
# patterns in template.toml. Others (such as the Poly master file, which
# only lists other files) are skipped, and the report says so.
files = ["veyra-{mac}.cfg"]
# Templates that use this catalog. A template's own family is the first
# family whose models include the device's model.
templates = ["poly.vvx.base", "poly.vvx.411", "poly.vvx.450"]
```

### 2.3 A release file: the first one (Poly)

The values below show the format. Each entry must be checked against the
vendor's guide before it is committed. The citations here are placeholders,
not real page numbers.

```toml
schema = 1

[release]
version = "6.3.0"                 # the release this file describes
# Versions this file is used for. Default: from this version up to (not
# including) the next release file of the family.
applies_to = ">=6.3.0, <6.4.0"
revision = 1                      # raised by every correction to this file
# What the entries were taken from. Entries refer to these by key.
[release.sources.ag63]
title = "Poly UC Software 6.3.0 Administrator Guide"
version = "6.3.0"
url = "https://docs.poly.com/"   # the vendor's landing page, never a copy

# One table per parameter. The name may hold an index placeholder {n}.
[param."reg.{n}.address"]
type = "string"
format = "sip-host"               # optional refinement of the type, see §3.2
index = { min = 1, max = 34 }
index_max_by_model = { "VVX 150" = 2, "VVX 250" = 4 }
note = "Registration address of line n."
source = { ref = "ag63", section = "Registration parameters", page = "TBD" }
provenance = "vendor-doc"         # vendor-doc | observed-on-hardware | seeded-from-template

[param."reg.{n}.server.{m}.transport"]
type = "enum"
values = ["DNSnaptr", "TCPpreferred", "UDPOnly", "TLS", "TCPOnly"]
default = "DNSnaptr"
index = { min = 1, max = 34 }
index2 = { min = 1, max = 2 }
note = "Transport for server m of line n."
source = { ref = "ag63", section = "Registration parameters", page = "TBD" }
provenance = "vendor-doc"

[param."device.net.vlanId"]
type = "int"
range = { min = 1, max = 4094 }
allow_empty = true
note = "Voice VLAN; empty for none."
provenance = "seeded-from-template"   # not yet cited: the checker warns (§3.3)

[param."feature.exampleOnlyOnColour.enabled"]
type = "bool"
bool_values = ["0", "1"]
not_models = ["VVX 150"]          # the model ignores it
added_in = "6.3.0"
note = "Illustration of a model exclusion."
source = { ref = "ag63", section = "TBD", page = "TBD" }
provenance = "vendor-doc"
```

### 2.4 A later release: only the changes

```toml
schema = 1

[release]
version = "6.4.0"
extends = "6.3.0"
revision = 1
[release.sources.rn64]
title = "Poly UC Software 6.4.0 Release Notes"
version = "6.4.0"

[added."feature.exampleNew.enabled"]        # a full entry, as in §2.3
type = "bool"
bool_values = ["0", "1"]
note = "New in 6.4.0."
source = { ref = "rn64", section = "New parameters", page = "TBD" }
provenance = "vendor-doc"

[changed."reg.{n}.server.{m}.transport"]    # only the fields that changed
values = ["DNSnaptr", "TCPpreferred", "UDPOnly", "TLS", "TCPOnly", "TLSOnly"]
source = { ref = "rn64", section = "Changed parameters", page = "TBD" }

[deprecated."call.exampleOld"]
replaced_by = "call.exampleNew"
source = { ref = "rn64", section = "Deprecated parameters", page = "TBD" }

[removed."feature.exampleGone"]
source = { ref = "rn64", section = "Removed parameters", page = "TBD" }
```

The `added_in`, `deprecated_in` and `removed_in` fields of the resolved
entry come from the release that added, deprecated or removed it. A
hand-written `added_in` is only needed in the first file of a family.

### 2.5 The Yealink equivalent

```toml
# provisioning/capabilities/yealink/t4x/family.toml
schema = 1
[family]
vendor = "yealink"
family = "t4x"
name = "Yealink T4x"
models = ["T42U", "T43U", "T44U", "T44W", "T46U", "T48U"]
format = "cfg"
version_scheme = "yealink"        # 108.86.0.15 and 66.86.0.15 are both release 86.0.15
firmware_packaging = "model"      # each release file names the models it covers
files = ["{mac}.cfg"]
templates = ["yealink.base", "yealink.t4x"]

# provisioning/capabilities/yealink/t4x/86.toml
schema = 1
[release]
version = "86"
models = ["T42U", "T43U", "T44U", "T44W", "T46U", "T48U"]   # with "model" packaging
revision = 1
[release.sources.ag86]
title = "Yealink SIP IP Phones Administrator Guide V86"
version = "86"

[param."account.{n}.sip_server.{m}.transport_type"]
type = "enum"
values = ["0", "1", "2", "3"]
labels = { "0" = "UDP", "1" = "TCP", "2" = "TLS", "3" = "DNS-NAPTR" }
default = "0"
index = { min = 1, max = 16 }
index_max_by_model = { "T42U" = 12, "T43U" = 12 }
index2 = { min = 1, max = 2 }
note = "Transport for SIP server m of account n."
source = { ref = "ag86", section = "Account settings", page = "TBD" }
provenance = "vendor-doc"

[param."features.intercom.allow"]
type = "bool"
bool_values = ["0", "1"]
default = "1"
provenance = "seeded-from-template"

[param."linekey.{n}.type"]
type = "int"
index = { min = 1, max = 29 }
range = { min = 0, max = 99 }    # the vendor lists the meaningful codes; see open question 4
provenance = "seeded-from-template"
```

### 2.6 Schema and loader

`backend/veyra/provisioning/capabilities.py` reads the files the way
`spec.py` reads `template.toml`: pydantic models with `extra="forbid"`, and
a `CapabilityError` that lists every problem with its file and key. The
loader also checks that:

- `schema` is a version it knows. Each schema version has its own pydantic
  model. A new schema version adds a model and never changes an old one, so
  old files load exactly as they did (goal 4).
- `extends` names an existing release of the same family, with no loops and
  a lower version.
- `added` names a parameter the parent does not have. `changed`,
  `deprecated` and `removed` name one it has.
- Each `source.ref` exists in some release of the chain. `vendor-doc`
  entries have a source. `seeded-from-template` entries need none.
- Types and their fields fit together: `values` only for an enum, `range`
  only for an int, and `{n}`/`{m}` present exactly when `index`/`index2`
  are.
- No release ranges in a family overlap. Every model in `index_max_by_model`
  and `not_models` is one of the family's models.

A unit test loads the whole built-in catalog, and CI fails on any problem.
The loaded catalog is cached per process, the same way the template catalog
is.

### 2.7 Seeding

To start, there are two families, Poly VVX (`poly.vvx.411`, `.450`, on
`poly.vvx.base`; first release 5.9.0) and Yealink T4x (`yealink.t4x` on
`yealink.base`; first release 86). The seeder
(`python -m veyra.provisioning.capability_seed <family dir>`) **scans** the
templates' sources instead of rendering them, so that settings written only
in some branches (daylight saving, one key type) are found too. It blanks
the Jinja tags, turns each `{{ … }}` into a token, and then finds the
settings with `base_edits.settings()`. A token in a name becomes `{n}`, and
a second one becomes `{m}`. The seeder adds the missing entries to the
family's first release as `type = "string"`, with no value rules and
`provenance = "seeded-from-template"`. The note says which template writes
the setting, and `seen` lists what it writes. Such an entry never produces
an error. The seeder only adds entries and never changes existing ones. It
is run by hand, and its output is reviewed like any other catalog change.
The supported-models list in each seeded `pack.toml` is also marked
`seeded-from-template` until it is replaced with the vendor's list.

A test renders every official template for every model of the two families.
It asserts the result has **no errors** and lists any parameter missing from
the catalog. A template change that adds a parameter therefore fails until
the catalog has it.

## 3. The checker

### 3.0 Fields, not phones

A template rarely writes a fixed value. Most parameters are filled from a
Veyra field: `account.1.user_name = {{ line.sip_username }}`. Every phone
has its own value of that field, but Veyra already knows the field's shape,
because it enforces that shape when the value is saved. An extension number
is 2 to 32 digits, a VLAN is 1 to 4094, a display name is at most 80
characters. So the precheck asks **"can any value this field can hold
break this parameter?"** once, and does not ask "does phone 47's value
break it?" for each phone.

1. **Field domains.** Each `Fact` in `provisioning/catalog.py` and each core
   or template variable (`spec.py` `VariableDef`, provisioning variables)
   gets a domain: its type and its length, pattern or range. Facts take it
   from the validator that guards the database field, such as the
   extension's number pattern. A test asserts that each domain matches its
   validator, so the two cannot drift apart. These are **not new database
   columns**. The data stays where it is, and only its description is
   added.
2. **Bindings.** The precheck renders the template once with *tracer
   values*. Each field gets a distinct value of a valid shape, and the
   checker reads which field ended up in which parameter. This works
   whatever Jinja the template uses (loops, filters, `if`), and it needs no
   parser of Jinja expressions. A parameter that holds a fixed value is
   checked by that value. A parameter fed by one or more fields is checked
   by their domains.
3. **Composite settings.** A setting built from several fields and text
   (`{{ line.sip_username }}@{{ server.sip_host }}`) is checked with the
   shortest and longest value of each field together, and it always gets a
   **warning**, `binding.composite`, that marks it for review. The rule is
   the checker's and does not change per firmware. The vendor's limits it
   is checked against (length, format) come from the release file and can
   change per firmware.
4. **Domain against rule.** A field's domain must fit the parameter's
   rules. If no value of the domain fits, the result is an **error** (a
   display name in an int parameter). If only some values fit, it is a
   **warning** that gives an example value that would fail ("a display name
   over 64 characters would be cut"). If every value fits, the parameter
   passes.
5. **Counts.** Index ranges (`reg.{n}`, `linekey.{n}`) come from what the
   profile defines: its key list is checked as it is, and lines up to the
   model's most lines.

The rendered values a profile fixes (its values, keys, Base File Edits and
the provisioning variables it resolves) are real values at profile level,
and the checker checks them as values. What varies per phone is covered by
the domains. A device's own overrides (`device.values`, device keys) are the
only per-phone values, and a device save checks those against the parameters
they feed. It does not run a full render.

### 3.1 Function

```python
# backend/veyra/provisioning/verify.py; pure, no database
def check_file(
    catalog: CapabilityCatalog,
    *, vendor: str, model: str, firmware: FirmwareTarget,
    file_pattern: str, fmt: str, content: str,
) -> list[Finding]
```

The checker reads the rendered file after Base File Edits, through
`base_edits.settings()`. For a Grandstream file it takes the `P<n>` elements,
and for an Algo file the `key = value` lines; it has no parsers of its own.
For each setting it:

1. matches the name to an entry, an exact name first and then the indexed
   patterns, and fills in `n`/`m`.
2. runs the rules (§3.2) for the resolved release.

Values of secret parameters (those matching `base_edits.SECRET_NAME`) are
checked but never copied into a finding. The finding shows `••••` and the
fingerprint uses the value's SHA-256.

`FirmwareTarget` holds the version, the catalog release it resolved to, and
how it was chosen (§3.5).

### 3.2 Rules

Each rule has a stable id. The id is part of the fingerprint, so changing a
rule's behaviour means adding a new id (`enum.2`) and retiring the old one.
It is never an edit, and it never re-opens findings people have already
looked at (goal 4).

| Rule id | Severity | Fires when |
|---|---|---|
| `param.unknown-model` | error | the entry's `not_models` contains the model |
| `param.not-yet` | error | the firmware is older than the entry's `added_in` |
| `param.removed` | error | the firmware is at or past `removed_in` |
| `index.range` | error | `{n}` or `{m}` is outside `index`, or above `index_max_by_model` for the model |
| `type.bool` / `type.int` / `type.ip` / `type.url` / `type.string` | error | the value does not parse as the type (`string` checks `max_length` and `pattern` if given) |
| `enum.1` | error | the value is not one of `values` |
| `range.1` | error | the int is outside `range` |
| `param.deprecated` | warning | the firmware is at or past `deprecated_in` (the note names `replaced_by`) |
| `binding.composite` | warning | the setting is built from several fields and text; review it (§3.0) |
| `entry.unverified` | info (a note) | the entry is only `seeded-from-template` (shown once per file as a count; see §3.3) |
| `param.not-in-catalog` | info | the parameter is not in the catalog |
| `catalog.none` | info | the vendor, family or firmware has no catalog; the whole file is not checked |
| `catalog.newer-firmware` | info | the firmware is newer than the newest release; it was checked against the newest one |
| `file.skipped` | info | the family does not check this file (such as the Poly master file) |

An empty value is accepted when the entry has `allow_empty = true` or the
template writes an empty value to clear the setting. Without either, an
empty value goes through the type rule.

### 3.3 Findings

```json
{
  "fingerprint": "cv1:6f0c…",          // sha256 over the fields below
  "severity": "error",                  // error | warning | info
  "rule": "enum.1",
  "vendor": "yealink", "family": "t4x", "model": "T46U",
  "firmware": "108.86.0.15", "release": "86", "catalog_revision": 1,
  "file": "{mac}.cfg",                  // the pattern, never the MAC
  "parameter": "account.1.sip_server.1.transport_type",
  "pattern": "account.{n}.sip_server.{m}.transport_type",
  "value": "4",
  "message": "4 is not a transport this firmware knows (0 UDP, 1 TCP, 2 TLS, 3 DNS-NAPTR).",
  "note": "Transport for SIP server m of account n.",
  "source": "Yealink SIP IP Phones Administrator Guide V86, Account settings",
  "provenance": "vendor-doc",
  "origin": "base_edit",               // template | base_edit | variable | profile_value | device_value, when known
  "override": null                      // or {by, at, reason, checker_wrong} (§4.2)
}
```

The fingerprint covers `vendor, family, model, release, file, parameter,
value (hashed if secret), rule`. It leaves out the catalog revision, so a
catalog correction does not re-open a finding the administrator already
overrode. It covers the release rather than the exact firmware version,
because builds within one release share one rule set. Moving a phone to
another release re-opens the finding, as the owner asked ("if the value,
model or firmware changes, the finding comes back").

"Not checked" is never shown as passing. The interface shows three counts:
**Errors**, **Warnings**, and **Not checked** (grey, with "Veyra has no data
for these settings: they were not checked"). A file with only not-checked
findings is labelled **Not checked**, never **OK**. Unverified entries
(`entry.unverified`) appear as one grey note per file, such as "37 settings
are checked against data taken from Veyra's own template, not yet from the
vendor's guide." The list of those settings is behind a toggle, so the
official templates can come out clean with one note instead of fifty lines.

### 3.4 Modularity, summed up

- One file per firmware release. Older releases are never deleted while any
  supported template still uses them. Each phone is checked against the
  release that covers its firmware.
- Rules have versioned ids, so new behaviour means a new id and old
  overrides keep matching.
- Each `schema` version has its own loader model, kept for good.
- Formats are reached through `base_edits.settings()`. A new vendor format
  adds one reader there, which Base File Edit also gains, and one value in
  `family.format`.

### 3.5 Which firmware to check against

For a device, the first of:

1. the firmware image assigned to the device, else the one assigned to its
   profile (`FirmwareImage.version`)
2. the version the phone last reported (`Device.firmware_reported`)
3. the oldest release in the family's catalog. A template could name its
   own minimum (open question 3).

For a profile or template there is no single phone, so the checker uses
**each distinct** version from the profile's image, its devices' images and
reported versions, and step 3 when none are known. It checks each one per
model the profile serves, and the findings name the version they belong
to. Versions in the same release are checked once.

## 4. Where it runs

### 4.1 Hooks

| Change | Endpoint (backend/veyra/api/v1) | Rendered for |
|---|---|---|
| Local template save / Customize | `provisioning.py` `PUT /templates/{key}`, import | sample facts per listed model × firmware targets (§3.5 step 3, plus versions in use by profiles on it) |
| Validate a template | `POST /templates/validate`, the editor's preview | same, findings returned only |
| Base File Edit | `device_profiles.py` base edits | each model of the profile × its firmware targets |
| Profile save (values, keys, template) | `device_profiles.py` `POST`, `PATCH` | same |
| Device save | `devices.py` `POST`, `PATCH`, `use-template` | only the device's own overrides, against the parameters they feed (§3.0); moving a device to a profile shows that profile's result |
| Device Configuration tab preview | `devices.py` preview (adds `findings` next to `warnings`) | the profile's precheck for this model and firmware, plus the device's overrides |
| Provisioning variable change | `provisioning_variables.py` `POST`, `PATCH` | the variable's value against the parameters it feeds in each template that uses it, per model × firmware: one check per template, not per profile or phone, so it runs while you wait |
| Firmware image assigned | profile or device save with `firmware_image_id` | every phone that would run it: "will the new firmware still take our configuration" |

Rendering reuses `render()` with tracer facts built like `sample_facts()`
(§3.0). It never uses a real phone's facts. Secret values are hashed as in §3.1 and never leave the checker.

The firmware assignment check returns the findings that are **new** under
the new release compared with the current one, grouped by phone and
setting, such as "12 phones: `call.exampleOld` is deprecated in 6.4.0". It
lists the findings that go away too.

### 4.2 Acknowledging and overriding

Every save endpoint above takes one optional field:

```json
"acknowledge": [
  { "fingerprint": "cv1:6f0c…", "reason": "Vendor support confirmed 4 = TLS only on 86.80", "checker_wrong": true }
]
```

- If the change produces **errors** that are neither acknowledged in the
  request nor already overridden for that scope, nothing is saved. The
  response is `422` with the API's problem body, `code:
  "config_findings"`, and `errors` holding the findings: all of them,
  including warnings and info, so the dialog can show the full picture.
- If every error is acknowledged or already overridden, the save goes
  through. The response carries `findings` (with their `override`) next to
  the saved object, the same way the preview carries `warnings`.
- Warnings and info never stop a save.
- A reason is required: 5 to 500 characters.

The `POST /provisioning/verify` endpoint (read only) checks a profile, a
device or a template with unsaved changes. The frontend calls it while
editing and before saving.

### 4.3 Serving

`serve.py` never runs the checker. After each save Veyra stores the
device's check summary (`devices.config_check`: JSONB holding the counts of
open errors, overridden errors, warnings and not checked, plus the time).
When a phone fetches a file and the summary shows open errors (possible
only when checks are advisory, or when the catalog changed since the save),
the request log line gets `check: open errors`. It goes to the log only, and
the file is served as usual.

### 4.4 When the catalog changes

A Veyra update can bring catalog corrections. After an update, a background
job re-checks profiles and devices and refreshes `config_check`. Findings
that are newly open show on the dashboard's provisioning widget and on the
device list, and they never block a phone. Overrides whose finding no
longer occurs are marked `stale` and drop out of the open list (they stay
in the history).

## 5. Turning it off

| Mode | Meaning |
|---|---|
| `enforce` | errors stop a save until overridden (§4.2) |
| `advisory` | findings are shown on every page and in every response; nothing stops a save, and nobody is asked for a reason |
| `off` | the checker does not run for that scope: no findings, no firmware check, no log line. Pages show "Configuration checks are off for this profile (by X on date)" in the place of the findings |

The mode can be set at three levels, and the most specific one that is set
applies:

1. **Installation**, `installation.config_check_mode`. Default `enforce`.
   Set under Settings → Provisioning by someone with installation
   settings permission. Upgraded installations start on `enforce` too
   (owner, 2026-11-07).
2. **Organization**, `organizations.config_check_mode`, nullable (inherits).
   Set by whoever can change the organization.
3. **Profile**, `device_profiles.config_check_mode`, nullable. This covers
   a lab profile or the one building that is "free willing it". Whoever can
   save the profile can change its mode. This is the finest level, and there
   is no per-phone switch: to leave one phone unchecked, put it on a test
   profile (owner, 2026-11-07).

Changing a mode is audited. Overrides stay stored while checks are off and
apply again when checks are turned back on. Templates have no mode of their
own: an `off` profile turns checks off for a template used through that
profile, and the template editor follows the organization's mode.

## 6. Overrides table

Migration `0093_config_check_overrides`:

```
config_check_overrides
  id               uuid pk
  organization_id  uuid fk organizations, null for an installation template
  scope_type       text   template | profile | device
  scope_id         text   template key, or the profile's or device's id
  fingerprint      text
  severity, rule, vendor, family, model, release, catalog_revision,
  file, parameter  text
  value            text   null when the parameter is secret
  value_sha256     text
  reason           text
  checker_wrong    bool
  created_by       uuid fk users (set null)
  created_at       timestamptz
  revoked_by / revoked_at   nullable: Revoke keeps the row
  stale_at         timestamptz null (§4.4)
  unique (scope_type, scope_id, fingerprint) where revoked_at is null
```

Scope: an override made on a profile save covers every device on the
profile that produces the same fingerprint. An override made on a device
covers only that device. An override on a template covers the template's
own rendering (the editor), and profiles still need their own, because
their values differ (open question 7).

Audit: `provisioning.check.override`, `.revoke`, and `.mode` events with the
fingerprint, the parameter, the masked value and the reason.

Plus `devices.config_check` (JSONB, §4.3) and the three `config_check_mode`
columns (§5).

## 7. Interface sketch

### 7.1 The check window

Every check opens a window: on save, on **Check now**, and on assigning
firmware. While the check runs, a progress bar shows the step it is on
("Rendering Yealink T4x for T46U on 86 (3 of 8)").

```
Clean                                   Problems
┌ Configuration check ──────────────┐   ┌ Configuration check ──────────────────────────────┐
│ ████████████████████████  done    │   │ ████████████████████████  done                    │
│                                   │   │ ✖ 1 error   ⚠ 2 warnings   ○ 14 not checked       │
│ ✔ No problems found               │   │                                                   │
│   212 settings checked on         │   │ ✖ account.1.sip_server.1.transport_type           │
│   T46U, T48U · firmware 86        │   │   Filled by: Base File Edit (fixed value)         │
│ ○ 37 checked against Veyra's own  │
│   data, not yet the vendor's guide│
│ ○ 14 settings not in Veyra's data │   │   Value: 4                                        │
│   were not checked       [ Show ] │   │   Accepts: 0 UDP, 1 TCP, 2 TLS, 3 DNS-NAPTR       │
│                                   │   │   Source: Yealink Admin Guide V86, Accounts       │
│                         [ OK ]    │   │ ⚠ account.1.label                                 │
└───────────────────────────────────┘   │   Filled by: line.display_name (up to 80 chars)   │
                                        │   Accepts: text, up to 64 characters              │
                                        │   Example that fails: an 80-character name        │
                                        │ ⚠ …                                               │
                                        │ [ Cancel ]  [ Override and save… ]                │
                                        └───────────────────────────────────────────────────┘
```

- **Clean** means no errors and no warnings. It still shows how many
  settings were not checked, because "not checked" is never "passed".
  **OK** closes the window, and the acknowledgement is recorded with the
  check.
- **Problems** lists every error and warning. Each item shows the setting,
  the **Veyra field or variable** that fills it (or "fixed value" with
  where it was set), the value or the field's range, and **what the
  setting accepts**: the enum values with their labels, the range, or the
  type and length. The source the vendor gave is also shown.
- With warnings only, **Save** goes ahead. With errors, **Override and
  save…** asks for a reason (and "The checker is wrong"). It is shown only
  to users with the override permission (§8). Everyone else sees "Ask an
  administrator to review these" and can only **Cancel**.
- In `advisory` mode the window appears the same way but never blocks. In
  `off` mode no window appears.

### 7.2 On the pages

```
Profile: Building A teachers                     [ Save ]
┌ Configuration check ─────────── enforced ▾ ───────────────────────┐
│ ✖ 1 error   ⚠ 1 warning   ○ 14 not checked   ✔ 1 overridden       │
│                                                                   │
│ ✖ {mac}.cfg  account.1.sip_server.1.transport_type = 4            │
│   T46U on 108.86.0.15 (release 86): not a transport this firmware │
│   knows (0 UDP, 1 TCP, 2 TLS, 3 DNS-NAPTR).                       │
│   Source: Yealink Administrator Guide V86, Account settings        │
│   From: Base File Edit                         [ Override… ]      │
│ ⚠ 37 settings checked against Veyra's own template data, not yet  │
│   the vendor's guide                                     [ Show ] │
│ ○ 14 settings not in the catalog: not checked            [ Show ] │
│ ✔ linekey.30.type: overridden by A. Admin on 2026-11-07:          │
│   "Expansion module present"                           [ Revoke ] │
└───────────────────────────────────────────────────────────────────┘

Override…  ┌───────────────────────────────────────────┐
           │ Why is this setting right?                │
           │ [ Vendor support confirmed on 86.80     ] │
           │ ☐ The checker is wrong (report it so the  │
           │   catalog can be corrected)               │
           │           [ Cancel ]  [ Override and save ]│
           └───────────────────────────────────────────┘
```

- `components/provisioning/ConfigFindings.tsx` is one component on the
  template editor, the Customize dialog, the Base File Edit page, the
  profile and device pages, the Configuration tab and the variables page.
  Each finding sits next to its setting where the page shows settings (the
  Base File Edit rows and the template editor's line).
- On save: when the response is `config_findings`, a dialog lists the
  errors. **Override and save** asks for one reason that applies to the
  errors ticked in the list (all of them by default).
- The firmware assignment shows the "new under this firmware" diff before
  saving (§4.1).
- **Provisioning → Checks**: the list of overrides with filters for
  organization, vendor, family, `checker wrong`, `stale` and `revoked`. The
  filter **Checker is wrong** is the to-do list for catalog fixes, with an
  export to CSV for a pull request.
- The device list gets a **Check** column (✖ open errors / ✔ / ○ not
  checked / off).

## 8. Permissions

Two new permissions in `core/security/permissions.py` appear in the user
roles editor like any other (owner, 2026-11-07):

| Permission | Allows | Default roles |
|---|---|---|
| `provisioning.check.override` | **Override and save** past errors, revoke overrides, and mark "the checker is wrong" | `org_admin` |
| `provisioning.check.mode` | change the mode of an organization or a profile | `org_admin` |

Saving still needs `provisioning.write` as today. Without the override
permission, a save with errors cannot go through. The installation's mode
needs `system.settings.write`. Every override, revocation and mode change
is audited.

## 9. Adding a firmware release

- `docs/guides/configuration-checks.md` (an admin guide, frontmatter like the
  other guides): what the three severities mean, overriding, "the checker
  is wrong", the modes, and the firmware assignment check.
- `docs/CAPABILITY_CATALOG.md` (for contributors): the file format, how to
  add a release or correct an entry, how to cite a source, how to run the
  checker on the official templates (`veyra-cli provisioning check-catalog
  --family poly/vvx`), and what reviewers look for.
- `docs/prompts/add-firmware-release.md`: a prompt for Claude, given
  together with a vendor's release notes or admin guide. Claude writes the
  release file (`extends` the previous one and lists only the changes, each
  with a section/page citation), runs the loader and the checker against
  every official template of the family, reports what would newly fail and
  opens a pull request. It never guesses a parameter's rules: anything the
  document does not state plainly goes into the pull request's "Open
  questions" list instead of the file.

## 10. Build slices (after approval)

1. **Done:** the pack and catalog schema, the loader
   (`provisioning/capabilities.py`), the seeded Poly VVX and Yealink T4x
   packs, the seeder, and the test that every setting the official
   templates write is in the catalog.
2. Field domains on facts and variables (with the validator test), then the
   checker (`verify.py`): tracer rendering, bindings, the value and domain
   rules, and unit tests with fixtures for each rule.
3. Migration 0093, modes, the `acknowledge` contract, the hooks in §4.1 and
   `POST /provisioning/verify`, the `config_check` summary, the serve-time
   log line, and the audit events.
4. Interface: `ConfigFindings`, the save dialog, the Checks page, the mode
   control, and the device list column.
5. The firmware assignment check (the diff between releases).
6. Pack sources from modules and local import, the Coverage page and the
   `pack` commands.
7. The guides, the pack author's guide, the prompt, the CHANGELOG, Test:
   issues and the wiki.

## 11. Open questions

1. ~~"Pass cleanly" vs unverified warnings.~~ Resolved: unverified entries
   are a note in the check window (§7.1), not a warning, so the official
   templates can come out clean. Original question: The official templates will
   have no errors but will carry one "unverified" warning per file until
   the entries are cited. Is one summarized warning acceptable, or should
   `seeded-from-template` count as info until the first vendor-doc pass?
2. ~~Default mode for existing installations.~~ Resolved: `enforce`, and
   administrators can change it.
3. **Template firmware minimum.** `template.toml` has only free text
   (`firmware = "UC Software 5.9 / 6.x"`). Should I add an optional
   structured `firmware_min` for §3.5 step 3, or rely on the oldest catalog
   release?
4. **How deep the enums go.** Yealink `linekey.N.type` has dozens of codes,
   and some are model-specific. The proposal is to seed it as an int range
   and tighten it in the first vendor-doc pass.
5. **Expansion modules.** Line keys above the phone's own count depend on
   an attached EXP module (#416). Until devices record that, `index.range`
   on line keys would be a warning, not an error.
6. ~~Variable changes at installation scope.~~ Resolved by the precheck
   (§3.0): one check per template that uses the variable, while you wait.
7. **Override inheritance.** Should a template-level override also cover
   every profile on that template, for settings that come only from the
   template text? (Proposed: no; each profile stands on its own.)
8. ~~Device-level mode.~~ Resolved: per profile at the finest; use a test
   profile.
9. ~~Catalogs from modules.~~ Resolved: vendor packs from the repository,
   modules or a local import (§2.0).
10. **Grandstream and Algo** families are left for after VVX and T4x; the
    format already allows them.
11. ~~Composite parameters.~~ Resolved: checked with the extreme values and
    always marked for review (§3.0).
