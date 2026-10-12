import copy

import pytest
from conftest import REPO

from veyra.provisioning.renderer import (
    MASK,
    TemplateCatalog,
    TemplateRecord,
    export_template,
    output_filename,
    render,
    validate,
)
from veyra.provisioning.spec import TemplateError, parse_template_manifest

VALUES = {
    "extension_number": "1001",
    "sip_username": "ext1001",
    "sip_password": 'p@ss<&>"',
    "sip_server": "10.0.0.5",
    "display_name": "Front <Office>",
    "timezone": "America/Chicago",
}


@pytest.fixture
def catalog() -> TemplateCatalog:
    c = TemplateCatalog.from_paths([REPO / "provisioning" / "templates"])
    assert not c.load_errors
    return c


def local(catalog: TemplateCatalog, sources: dict[str, str], **template) -> TemplateRecord:
    manifest = {
        "template": {
            "key": "local.test",
            "name": "Test",
            "version": "1.0.0",
            "manufacturer": "Acme",
            "models": ["X1"],
            **template,
        },
        "files": [{"name": "{mac}.cfg", "source": "a.j2", "format": "text"}],
    }
    rec = TemplateRecord(parse_template_manifest(manifest), "local", sources)
    catalog.records[rec.key] = rec
    return rec


@pytest.mark.parametrize("model_key", ["poly.vvx.411", "poly.vvx.450"])
def test_official_templates_validate(catalog, model_key):
    assert validate(catalog.resolve(model_key)) == []


def test_render_poly_inherits_and_escapes(catalog):
    files = render(
        catalog.resolve("poly.vvx.411"), VALUES, mac="00:04:F2:AB:CD:EF", model="VVX 411"
    )
    names = [f.filename for f in files]
    assert names == ["0004f2abcdef.cfg", "veyra-0004f2abcdef.cfg"]
    phone = files[1].content
    assert 'reg.1.auth.password="p@ss&lt;&amp;&gt;&#34;"' in phone
    assert 'reg.1.label="Front &lt;Office&gt;"' in phone
    assert "Model-specific settings for VVX 411" in phone  # child block
    assert "device.net.vlanId" not in phone  # vlan_id not set


def test_preview_masks_secrets(catalog):
    files = render(
        catalog.resolve("poly.vvx.450"),
        VALUES,
        mac="0004f2000001",
        model="VVX 450",
        mask_secrets=True,
    )
    content = "".join(f.content for f in files)
    assert MASK in content and "p@ss" not in content


def test_value_validation(catalog):
    r = catalog.resolve("poly.vvx.411")
    with pytest.raises(TemplateError) as exc:
        render(
            r,
            {**VALUES, "sip_server": 'evil" injected="1', "bogus": 1},
            mac="0004f2000001",
            model="VVX 411",
        )
    assert any("sip_server" in e for e in exc.value.errors)
    assert any("Unknown variables" in e for e in exc.value.errors)
    with pytest.raises(TemplateError):
        render(
            r,
            {k: v for k, v in VALUES.items() if k != "sip_password"},
            mac="0004f2000001",
            model="VVX 411",
        )


def test_model_and_abstract_checks(catalog):
    with pytest.raises(TemplateError):
        render(catalog.resolve("poly.vvx.411"), VALUES, mac="0004f2000001", model="VVX 450")
    with pytest.raises(TemplateError):
        render(catalog.resolve("poly.vvx.base"), VALUES, mac="0004f2000001", model="VVX 411")
    with pytest.raises(TemplateError):
        render(catalog.resolve("poly.vvx.411"), VALUES, mac="not-a-mac", model="VVX 411")


@pytest.mark.parametrize(
    "source",
    [
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{ cycler.__init__.__globals__.os.popen('id').read() }}",
        "{% for x in range(10**9) %}{% endfor %}",
    ],
)
def test_sandbox_blocks_code_execution(catalog, source):
    local(catalog, {"a.j2": source})
    with pytest.raises(TemplateError):
        render(catalog.resolve("local.test"), VALUES, mac="0004f2000001", model="X1")


def test_validation_flags_undeclared_variables(catalog):
    local(catalog, {"a.j2": "{{ extension_number }} {{ secret_backdoor }}"})
    problems = validate(catalog.resolve("local.test"))
    assert any("secret_backdoor" in p for p in problems)


def test_loader_cannot_escape_chain(catalog):
    local(catalog, {"a.j2": "{% include '../../../../etc/passwd' %}"})
    with pytest.raises(TemplateError):
        render(catalog.resolve("local.test"), VALUES, mac="0004f2000001", model="X1")


def test_local_override_of_official_parent(catalog):
    local(
        catalog,
        {
            "a.j2": "{% extends 'poly.vvx.base/phone.cfg.j2' %}"
            "{% block model_settings %}LOCAL{% endblock %}"
        },
        parent="poly.vvx.base",
        models=["VVX 411"],
    )
    files = render(catalog.resolve("local.test"), VALUES, mac="0004f2000001", model="VVX 411")
    assert any("LOCAL" in f.content for f in files)
    # the official template is unchanged
    official = render(catalog.resolve("poly.vvx.411"), VALUES, mac="0004f2000001", model="VVX 411")
    assert not any("LOCAL" in f.content for f in official)


def test_inheritance_loop_detected(catalog):
    local(catalog, {"a.j2": "x"}, parent="local.test")
    with pytest.raises(TemplateError):
        catalog.resolve("local.test")


@pytest.mark.parametrize("pattern", ["../{mac}.cfg", "{mac}/x.cfg", "{secret}.cfg"])
def test_filename_patterns_rejected(pattern):
    with pytest.raises(TemplateError):
        parse_template_manifest(
            {
                "template": {
                    "key": "a.b",
                    "name": "x",
                    "version": "1.0.0",
                    "manufacturer": "x",
                    "models": ["m"],
                },
                "files": [{"name": pattern, "source": "a.j2", "format": "text"}],
            }
        )


def test_output_filename_validated():
    assert (
        output_filename("{mac_upper}-{model_slug}.xml", "0004f2abcdef", "VVX 411")
        == "0004F2ABCDEF-vvx-411.xml"
    )


def test_export_contains_no_secrets(catalog):
    rec = local(catalog, {"a.j2": "{{ extension_number }}"})
    data = copy.deepcopy(rec.manifest.model_dump(mode="json"))
    data["variables"] = [{"name": "api_key", "sensitive": True, "default": "hunter2"}]
    rec = TemplateRecord(parse_template_manifest(data), "local", {"a.j2": "x"})
    exported = export_template(rec)
    assert "hunter2" not in str(exported)


def test_templates_may_not_default_sip_password():
    with pytest.raises(TemplateError):
        parse_template_manifest(
            {
                "template": {
                    "key": "a.b",
                    "name": "x",
                    "version": "1.0.0",
                    "manufacturer": "x",
                    "models": ["m"],
                },
                "defaults": {"sip_password": "1234"},
            }
        )
