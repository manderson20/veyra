import copy
import tomllib

import pytest
from conftest import REPO

from veyra.modules.manifest import (
    ManifestError,
    load_manifest,
    manifest_json_schema,
    parse_manifest,
)

EXAMPLE = REPO / "modules" / "veyra-example-notes"


def example() -> dict:
    return tomllib.loads((EXAMPLE / "module.toml").read_text())


def test_example_manifest_is_valid():
    m = load_manifest(EXAMPLE)
    assert m.id == "veyra.example-notes"
    assert m.permission_namespace == "example_notes."
    assert m.ui.views[0].endpoint == "notes"


def test_json_schema_available():
    assert "module" in manifest_json_schema()["properties"]


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d["module"].update(id="Bad Id"), "module.id"),
        (lambda d: d["module"].update(version="1.0"), "module.version"),
        (lambda d: d["compatibility"].update(core_api="not a range"), "core_api"),
        (
            lambda d: d["permissions"].append({"key": "other.read", "description": "x"}),
            "must start with",
        ),
        (lambda d: d["database"].update(table_prefix="notes_"), "table_prefix"),
        (lambda d: d["events"].update(publishes=["core.hijack"]), "must start with"),
        (lambda d: d["ui"]["nav"][0].update(view="missing"), "unknown view"),
        (
            lambda d: d["ui"]["views"][0].update(permission="example_notes.admin"),
            "undeclared permission",
        ),
        (lambda d: d["ui"]["views"][0].update(endpoint="../../users"), "endpoint"),
        (lambda d: d["runtime"].update(entrypoint="os.system"), "entrypoint"),
        (lambda d: d.update(unexpected=True), "unexpected"),
    ],
)
def test_invalid_manifests_rejected(mutate, fragment):
    data = copy.deepcopy(example())
    mutate(data)
    with pytest.raises(ManifestError) as exc:
        parse_manifest(data)
    assert any(fragment in e for e in exc.value.errors), exc.value.errors
