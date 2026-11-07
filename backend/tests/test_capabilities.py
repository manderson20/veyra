# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device capability catalog (docs/CONFIG_VERIFICATION.md §2): the built-in
packs load, cover every setting the official templates write, resolve
releases through ``extends``, and the loader refuses malformed packs."""

from pathlib import Path

import pytest

from veyra.provisioning import capability_seed
from veyra.provisioning.capabilities import (
    CapabilityCatalog,
    CapabilityError,
    load_pack,
    parse_range,
    parse_version,
)
from veyra.provisioning.renderer import TemplateCatalog

REPO = Path(__file__).resolve().parents[2]
BUILT_IN = REPO / "provisioning" / "capabilities"


@pytest.fixture(scope="module")
def catalog() -> CapabilityCatalog:
    return CapabilityCatalog.from_paths([BUILT_IN])


@pytest.fixture(scope="module")
def templates() -> TemplateCatalog:
    return TemplateCatalog.from_paths([REPO / "provisioning" / "templates"])


def test_built_in_packs_load(catalog):
    assert catalog.load_errors == {}
    assert {"veyra.poly", "veyra.yealink"} <= set(catalog.packs)


def test_official_templates_are_covered(catalog, templates):
    """Every setting an official template writes has an entry in every
    release of its family; a template change that adds a setting fails here
    until the catalog has it (run veyra.provisioning.capability_seed)."""
    for pack in catalog.packs.values():
        for family in pack.families.values():
            for key in family.info.templates:
                assert key in templates.records, f"{family.key}: no template {key}"
            for release in family.releases:
                gaps = capability_seed.missing(templates, family, release)
                assert not gaps, (
                    f"{family.key} {release.version} lacks: {[g.pattern for g in gaps]}"
                )


def test_supported_models_match_templates(catalog, templates):
    for pack in catalog.packs.values():
        for family in pack.families.values():
            records = [templates.records[k] for k in family.info.templates]
            listed = {m for r in records for m in r.manifest.template.models}
            assert listed <= set(family.info.models), family.key


def test_family_and_release_lookup(catalog):
    hit = catalog.family_for("Yealink", "T46U")
    assert hit is not None
    pack, family, support = hit
    assert (pack.info.id, family.info.family) == ("veyra.yealink", "t4x")
    assert support.provenance == "seeded-from-template"
    release, why = family.release_for("108.86.0.15", "T46U")
    assert release is not None and release.version == "86" and why == "exact"
    assert family.release_for("66.85.0.20", "T46U") == (None, "older")
    assert family.release_for("not a version", "T46U") == (None, "invalid")
    assert catalog.family_for("Yealink", "T58W") is None  # not covered
    assert catalog.family_for("Poly", "T46U") is None
    poly = catalog.family_for("Poly", "VVX 450")
    assert poly is not None
    entry, index = poly[1].releases[0].lookup("reg.3.server.1.transport") or (None, ())
    assert entry is not None and entry.name == "reg.{n}.server.1.transport" and index == (3,)
    assert poly[1].releases[0].lookup("reg.3.nonsense") is None


def test_versions():
    assert parse_version("6.4.5.1234") == (6, 4, 5, 1234)
    assert parse_version("108.86.0.15", "yealink") == (86, 0, 15)
    assert parse_version("86", "yealink") == (86,)
    assert parse_version("6.3.0 rev A") == (6, 3, 0)
    r = parse_range(">=6.3.0, <6.4")
    assert r.contains((6, 3, 9)) and not r.contains((6, 4, 0)) and not r.contains((6, 2))
    with pytest.raises(ValueError):
        parse_range(">=2, <1")
    with pytest.raises(ValueError):
        parse_range("~1.0")


def test_scan_source():
    xml = '<a reg.{{ line.index }}.address="{{ line.sip_username }}" x.y="1" />{# z.q="2" #}'
    assert capability_seed.scan_source("xml", xml) == [
        ("reg.{n}.address", "reg.1.address", "{{ line.sip_username }}"),
        ("x.y", "x.y", "1"),
    ]
    cfg = "{% for k in keys %}\nlinekey.{{ k.index }}.type = 15\n{% endfor %}\n## a.b = 1\n"
    assert capability_seed.scan_source("cfg", cfg) == [("linekey.{n}.type", "linekey.1.type", "15")]


# ------------------------------------------------------------ a test pack

PACK = """schema = 1
[pack]
id = "test.acme"
name = "Acme"
vendor = "acme"
version = "1.0.0"
[[supports]]
family = "desk"
models = ["D1", "D2"]
firmware = ">=1.0"
source = { title = "Acme Admin Guide 1.0", section = "Models" }
"""
FAMILY = """schema = 1
[family]
vendor = "acme"
family = "desk"
name = "Acme desk"
models = ["D1", "D2"]
format = "cfg"
files = ["{mac}.cfg"]
"""
R10 = """schema = 1
[release]
version = "1.0"
[release.sources.ag]
title = "Acme Admin Guide 1.0"
[param."line.{n}.transport"]
type = "enum"
values = ["udp", "tcp"]
index = { min = 1, max = 4 }
index_max_by_model = { D1 = 2 }
source = { ref = "ag", section = "Lines", page = "12" }
provenance = "vendor-doc"
[param."old.setting"]
type = "bool"
bool_values = ["0", "1"]
source = { ref = "ag", section = "Misc" }
provenance = "vendor-doc"
[param."gone.setting"]
type = "string"
provenance = "seeded-from-template"
"""
R11 = """schema = 1
[release]
version = "1.1"
extends = "1.0"
[release.sources.rn]
title = "Acme Release Notes 1.1"
[added."new.setting"]
type = "int"
range = { min = 0, max = 9 }
source = { ref = "rn", section = "New" }
provenance = "vendor-doc"
[changed."line.{n}.transport"]
values = ["udp", "tcp", "tls"]
source = { ref = "rn", section = "Changed" }
[deprecated."old.setting"]
replaced_by = "new.setting"
source = { ref = "rn", section = "Deprecated" }
[removed."gone.setting"]
source = { ref = "rn", section = "Removed" }
"""
R12 = """schema = 1
[release]
version = "1.2"
extends = "1.1"
revision = 2
"""


def _pack(tmp_path: Path) -> Path:
    files = {
        "pack.toml": PACK,
        "desk/family.toml": FAMILY,
        "desk/1.0.toml": R10,
        "desk/1.1.toml": R11,
        "desk/1.2.toml": R12,
    }
    root = tmp_path / "acme"
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_inheritance(tmp_path):
    pack = load_pack(_pack(tmp_path))
    family = pack.families["desk"]
    assert [r.version for r in family.releases] == ["1.0", "1.1", "1.2"]
    r10, r11, r12 = family.releases
    assert r10.applies.text == "" and r10.applies.contains((1, 0, 5))
    assert not r10.applies.contains((1, 1))
    assert family.release_for("1.1.3", "D1")[0] is r11
    assert family.release_for("2.0", "D1") == (r12, "newer")
    assert family.release_for("0.9", "D1") == (None, "older")
    t10 = r10.lookup("line.1.transport")
    t11 = r11.lookup("line.1.transport")
    assert t10 and t10[0].values == ("udp", "tcp") and t10[0].index_max_by_model == {"D1": 2}
    assert t11 and t11[0].values == ("udp", "tcp", "tls")
    # A change keeps what it does not replace, and cites its own source.
    assert t11[0].index_max_by_model == {"D1": 2} and "Release Notes 1.1" in t11[0].source
    assert t10[0].source == "Acme Admin Guide 1.0, Lines, p. 12"
    assert r10.exact.get("new.setting") is None
    assert r11.exact["new.setting"].added_in == "1.1"
    assert r11.exact["old.setting"].deprecated_in == "1.1"
    assert r11.exact["old.setting"].replaced_by == "new.setting"
    assert r12.exact["gone.setting"].removed_in == "1.1"  # inherited
    assert r12.revision == 2
    assert r10.exact["old.setting"].deprecated_in is None  # older releases are untouched


# (file, text replaced, replacement, an error that must appear)
BROKEN = [
    ("desk/1.1.toml", '[changed."line', '[changed."nope', "does not have"),
    ("desk/1.1.toml", '[added."new.setting"]', '[added."old.setting"]', "already has"),
    ("desk/1.0.toml", 'source = { ref = "ag", section = "Misc" }\n', "", "cites its source"),
    ("desk/1.0.toml", 'values = ["udp", "tcp"]\n', "", "an enum lists its values"),
    ("desk/1.0.toml", "D1 = 2", "D9 = 2", "not a model of the family"),
    ("desk/1.0.toml", 'ref = "ag", section = "Lines"', 'ref = "xx", section = "L"', "not in any"),
    ("pack.toml", 'models = ["D1", "D2"]', 'models = ["D1"]', "no supports entry covers D2"),
    ("pack.toml", 'family = "desk"', 'family = "wall"', "no family 'wall'"),
    (
        "pack.toml",
        'source = { title = "Acme Admin Guide 1.0", section = "Models" }\n',
        "",
        "source",
    ),
    ("desk/1.2.toml", 'extends = "1.1"', 'extends = "0.5"', "the family lacks"),
    ("desk/1.2.toml", "schema = 1", "schema = 2", "schema 2"),
    (
        "desk/1.2.toml",
        "revision = 2",
        'revision = 2\n[param."x"]\ntype = "string"',
        "lists changes",
    ),
    ("desk/1.0.toml", 'version = "1.0"', 'version = "1.0"\napplies_to = ">=1.0, <1.5"', "overlap"),
    ("desk/1.0.toml", "max = 4 }", "max = 4 }\nindex2 = { min = 1 }", "index2 without"),
    ("desk/family.toml", 'vendor = "acme"', 'vendor = "other"', "vendor differs"),
]


@pytest.mark.parametrize(("name", "old", "new", "message"), BROKEN)
def test_loader_refuses(tmp_path, name, old, new, message):
    root = _pack(tmp_path)
    path = root / name
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    with pytest.raises(CapabilityError) as e:
        load_pack(root)
    assert any(message in err for err in e.value.errors), e.value.errors


def test_duplicate_pack_ids_are_refused(tmp_path):
    first = _pack(tmp_path / "a")
    second = _pack(tmp_path / "b")
    catalog = CapabilityCatalog.from_paths([first.parent])
    catalog.extend([second.parent], "local")
    assert list(catalog.packs) == ["test.acme"]
    assert catalog.packs["test.acme"].origin == "built-in"
    assert any("already loaded" in e for errs in catalog.load_errors.values() for e in errs)


def test_seed_only_adds(tmp_path, templates):
    """Seeding fills a first release with what the templates write, marks it
    seeded, and leaves existing entries alone."""
    root = tmp_path / "caps" / "yealink" / "t4x"
    root.mkdir(parents=True)
    src = BUILT_IN / "yealink" / "t4x"
    (root / "family.toml").write_text((src / "family.toml").read_text())
    (root / "86.toml").write_text(
        '# hand written\nschema = 1\n[release]\nversion = "86"\n'
        'models = ["T42U", "T43U", "T44U", "T44W", "T46U", "T48U"]\n'
        '[release.sources.ag]\ntitle = "Guide"\n'
        '[param."features.intercom.allow"]\ntype = "bool"\nbool_values = ["0", "1"]\n'
        'source = { ref = "ag", section = "Intercom" }\nprovenance = "vendor-doc"\n'
    )
    added = capability_seed.seed(root, templates)
    assert "features.intercom.allow" not in {f.pattern for f in added}
    assert "account.{n}.user_name" in {f.pattern for f in added}
    text = (root / "86.toml").read_text()
    assert text.startswith("# hand written") and 'bool_values = ["0", "1"]' in text
    assert capability_seed.seed(root, templates) == []  # nothing left to add
