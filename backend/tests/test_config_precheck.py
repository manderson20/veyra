# SPDX-License-Identifier: AGPL-3.0-or-later
"""The configuration checker and precheck (docs/CONFIG_VERIFICATION.md §3):
field shapes agree with the validators that guard them, each rule fires on
its own fixture, fingerprints are stable, and the official templates come
out clean."""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_capabilities import _pack

from veyra.api.v1 import extensions as ext_api
from veyra.provisioning import catalog as fact_catalog
from veyra.provisioning import domains
from veyra.provisioning.capabilities import CapabilityCatalog
from veyra.provisioning.precheck import binding, precheck
from veyra.provisioning.renderer import TemplateCatalog
from veyra.provisioning.spec import CORE_VARIABLES
from veyra.provisioning.verify import FileInput, Target, check_files, firmware_targets

REPO = Path(__file__).resolve().parents[2]
BUILT_IN = REPO / "provisioning" / "capabilities"
ORG = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def templates() -> TemplateCatalog:
    return TemplateCatalog.from_paths([REPO / "provisioning" / "templates"])


@pytest.fixture(scope="module")
def built_in() -> CapabilityCatalog:
    return CapabilityCatalog.from_paths([BUILT_IN])


# ------------------------------------------------------------ field shapes


def _ext(**over):
    return ext_api.ExtensionIn(
        **{"organization_id": ORG, "number": "1001", "display_name": "A", **over}
    )


def test_domains_match_validators():
    d = domains.FACT_DOMAINS
    longest_name = d["line.display_name"].longest
    assert len(longest_name) == domains.DISPLAY_NAME_MAX
    _ext(display_name=longest_name)
    with pytest.raises(ValidationError):
        _ext(display_name=longest_name + "W")
    _ext(number=d["line.extension_number"].longest)
    with pytest.raises(ValidationError):
        _ext(number=d["line.extension_number"].longest + "9")
    assert ext_api._caller_id_name(d["line.caller_id_name"].longest)
    with pytest.raises(ValueError):
        ext_api._caller_id_name(d["line.caller_id_name"].longest + "W")
    assert ext_api._caller_id_number(d["line.caller_id_number"].longest)
    assert ext_api._hotline_target(d["line.hotline"].longest)
    with pytest.raises(ValueError):
        ext_api._hotline_target(d["line.hotline"].longest + "9")
    assert len(d["line.sip_username"].longest) <= domains.SIP_USERNAME_MAX
    # The core variables fed from these fields take everything the field holds.
    core = {v.name: v for v in CORE_VARIABLES}
    assert core["display_name"].max_length >= domains.DISPLAY_NAME_MAX
    assert core["extension_number"].max_length >= domains.EXTENSION_NUMBER_MAX


def test_domains_name_real_facts():
    known = {f.expr for g in fact_catalog.GROUPS for f in g.facts}
    for path in domains.FACT_DOMAINS:
        assert path in known, f"{path} is not a fact the editor offers"


def test_binding():
    t = domains.FACT_DOMAINS
    assert binding(t["line.display_name"].typical) == (["line.display_name"], False)
    fields, composite = binding(f"{t['line.sip_username'].typical}@{t['server.sip_host'].typical}")
    assert fields == ["line.sip_username", "server.sip_host"] and composite
    assert binding(f"{t['zone.multicast_address'].typical}:5001") == (
        ["zone.multicast_address"],
        True,
    )
    assert binding("15") == ([], False)


# ------------------------------------------------------------ rules


@pytest.fixture
def acme(tmp_path) -> CapabilityCatalog:
    return CapabilityCatalog.from_paths([_pack(tmp_path).parent])


def _rules(findings):
    return {(f.severity, f.rule, f.parameter) for f in findings}


def _check(catalog, text, model="D1", firmware="1.0.3", pattern="{mac}.cfg"):
    return check_files(
        catalog, Target("Acme", model, firmware, "test"), [FileInput(pattern, "cfg", text)]
    )


def test_rules(acme):
    found = _check(
        acme,
        "line.1.transport = tcp\n"
        "line.2.transport = tls\n"  # tls only from 1.1
        "line.3.transport = udp\n"  # D1 has two lines
        "old.setting = 2\n"
        "new.setting = 3\n"  # added in 1.1
        "who.knows = 1\n",
    )
    rules = _rules(found)
    assert ("error", "enum.1", "line.2.transport") in rules
    assert ("error", "index.range", "line.3.transport") in rules
    assert ("error", "type.bool", "old.setting") in rules
    assert ("error", "param.not-yet", "new.setting") in rules
    assert not any(f.parameter == "line.1.transport" for f in found)
    enum = next(f for f in found if f.rule == "enum.1")
    assert enum.accepts == "udp, tcp" and enum.source == "Acme Admin Guide 1.0, Lines, p. 12"
    assert enum.release == "1.0" and enum.firmware == "1.0.3"
    unknown = next(f for f in found if f.rule == "param.not-in-catalog")
    assert unknown.severity == "info" and unknown.members == ["who.knows"]
    assert found[0].severity == "error"  # errors first


def test_rules_on_a_later_release(acme):
    found = _check(
        acme,
        "line.2.transport = tls\nold.setting = 1\nnew.setting = 12\ngone.setting = x\n",
        firmware="1.1.0",
    )
    rules = _rules(found)
    assert ("warning", "param.deprecated", "old.setting") in rules
    assert ("error", "range.1", "new.setting") in rules
    assert ("error", "param.removed", "gone.setting") in rules
    assert not any(f.parameter == "line.2.transport" for f in found)
    dep = next(f for f in found if f.rule == "param.deprecated")
    assert "new.setting" in dep.message


def test_not_checked_is_never_passed(acme):
    none = _check(acme, "line.1.transport = tcp\n", model="D7")
    assert [(f.severity, f.rule) for f in none] == [("info", "catalog.none")]
    older = _check(acme, "line.1.transport = tcp\n", firmware="0.9")
    assert [f.rule for f in older] == ["catalog.none"]
    newer = _check(acme, "line.1.transport = tcp\n", firmware="3.0")
    assert "catalog.newer-firmware" in {f.rule for f in newer}
    skipped = _check(acme, "x = 1\n", pattern="other.cfg")
    assert [f.rule for f in skipped] == ["file.skipped"]


def test_secrets_and_fingerprints(acme, tmp_path):
    a = _check(acme, "old.setting = 7\n")
    b = _check(acme, "old.setting = 7\n", firmware="1.0.9")  # same release
    c = _check(acme, "old.setting = 8\n")
    d = _check(acme, "old.setting = 7\n", model="D2")
    fp = [x[0].fingerprint for x in (a, b, c, d)]
    assert fp[0] == fp[1] and len({fp[0], fp[2], fp[3]}) == 3
    assert fp[0].startswith("cv1:")
    # A secret's value never appears in a finding.
    root = tmp_path / "s" / "acme"
    shutil.copytree(_pack(tmp_path / "s0"), root)
    r10 = root / "desk" / "1.0.toml"
    r10.write_text(
        r10.read_text() + '[param."line.{n}.password"]\ntype = "string"\nmax_length = 4\n'
        'source = { ref = "ag", section = "Lines" }\nprovenance = "vendor-doc"\n'
    )
    cat = CapabilityCatalog.from_paths([root.parent])
    secret = _check(cat, "line.1.password = hunter22\n")
    f = next(x for x in secret if x.rule == "type.string")
    assert f.value == "••••" and "hunter22" not in str(f.as_dict())


def test_firmware_targets(built_in):
    t = firmware_targets("Yealink", "T46U", device_image="108.86.0.20", profile_image="108.86.0.1")
    assert [(x.firmware, x.how) for x in t] == [("108.86.0.20", "device-image")]
    t = firmware_targets("Yealink", "T46U", profile_image="108.86.0.1")
    assert [x.how for x in t] == ["profile-image"]
    # Two builds of one release are checked once.
    t = firmware_targets(
        "Yealink", "T46U", reported=["108.86.0.1", "108.86.0.9", None], catalog=built_in
    )
    assert [x.firmware for x in t] == ["108.86.0.1"]
    t = firmware_targets("Yealink", "T46U")
    assert [(x.firmware, x.how) for x in t] == [(None, "oldest")]


# ------------------------------------------------------------ precheck


def test_official_templates_are_clean(built_in, templates):
    """Every model of every family, with one key of each type and paging,
    at the field extremes: no errors and no warnings (only notes)."""
    for pack in built_in.packs.values():
        for family in pack.families.values():
            for key in family.info.templates:
                resolved = templates.resolve(key)
                for model in resolved.record.manifest.template.models:
                    result = precheck(
                        built_in, resolved, Target(pack.info.vendor, model, None, "oldest")
                    )
                    bad = [f.as_dict() for f in result.findings if f.severity != "info"]
                    assert not bad, (key, model, bad)
                    assert result.checked > 20
                    assert {f.rule for f in result.findings} <= {
                        "entry.unverified",
                        "file.skipped",
                    }


def _strict_yealink(tmp_path: Path) -> CapabilityCatalog:
    """The built-in Yealink pack with three entries cited as if from the guide."""
    root = tmp_path / "caps"
    shutil.copytree(BUILT_IN / "yealink", root / "yealink")
    path = root / "yealink" / "t4x" / "86.toml"
    text = path.read_text()
    text = text.replace(
        "revision = 1\n", 'revision = 1\n[release.sources.ag]\ntitle = "Guide V86"\n', 1
    )

    def cite(name: str, body: str) -> None:
        nonlocal text
        start = text.index(f'[param."{name}"]')
        end = text.find("\n[param.", start + 1)
        end = len(text) if end < 0 else end + 1
        text = (
            text[:start]
            + f'[param."{name}"]\n{body}\nsource = {{ ref = "ag", section = "X" }}\n'
            + 'provenance = "vendor-doc"\n'
            + text[end:]
        )

    cite(
        "account.{n}.sip_server.1.transport_type",
        'type = "enum"\nvalues = ["0", "1", "2", "3"]\n'
        'labels = { "0" = "UDP", "1" = "TCP", "2" = "TLS", "3" = "DNS-NAPTR" }',
    )
    cite("account.{n}.label", 'type = "string"\nmax_length = 99')
    cite("linekey.{n}.value", 'type = "string"\nmax_length = 99')
    path.write_text(text)
    cat = CapabilityCatalog.from_paths([root])
    assert cat.load_errors == {}
    return cat


def test_precheck_finds_a_base_file_edit(tmp_path, templates):
    cat = _strict_yealink(tmp_path)
    resolved = templates.resolve("yealink.t4x")
    edit = {
        "file": "{mac}.cfg",
        "parameter": "account.1.sip_server.1.transport_type",
        "value": "4",
        "models": ["T46U"],
    }
    result = precheck(
        cat, resolved, Target("Yealink", "T46U", "108.86.0.15", "reported"), edits=[edit]
    )
    err = [f for f in result.findings if f.severity == "error"]
    assert [(f.rule, f.parameter, f.value) for f in err] == [
        ("enum.1", "account.1.sip_server.1.transport_type", "4")
    ]
    assert err[0].filled_by == [] and err[0].accepts == "0 UDP, 1 TCP, 2 TLS, 3 DNS-NAPTR"
    assert not result.clean
    # The model the edit is not for is unaffected.
    other = precheck(
        cat, resolved, Target("Yealink", "T48U", "108.86.0.15", "reported"), edits=[edit]
    )
    assert not [f for f in other.findings if f.severity == "error"]


def test_precheck_extremes_and_composites(tmp_path, templates):
    cat = _strict_yealink(tmp_path)
    result = precheck(
        cat, templates.resolve("yealink.t4x"), Target("Yealink", "T46U", None, "oldest")
    )
    by = {(f.rule, f.parameter): f for f in result.findings}
    # A label fits with typical names; a 200-character name would not.
    label = by[("type.string", "account.1.label")]
    assert label.severity == "warning" and "longest" in label.message
    assert label.filled_by == ["line.label"]
    # A page key's value is an address and a port: reviewed, not trusted.
    page = by[("binding.composite", "linekey.6.value")]
    assert page.severity == "warning" and page.filled_by == ["zone.multicast_address"]
    assert not [f for f in result.findings if f.severity == "error"]
    # The fingerprint follows the field, not the sample value.
    again = precheck(
        cat, templates.resolve("yealink.t4x"), Target("Yealink", "T46U", None, "oldest")
    )
    assert {f.fingerprint for f in again.findings} == {f.fingerprint for f in result.findings}
