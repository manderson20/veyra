# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed a capability family from Veyra's own templates
(docs/CONFIG_VERIFICATION.md §2.7). The templates' sources are scanned, not
rendered, so every branch counts (a setting written only with daylight
saving or only for a BLF key is found too). Jinja tags are blanked and each
``{{ … }}`` becomes a token, then ``base_edits.settings()`` finds the
settings as it does in a rendered file. A token in a setting's name is an
index and becomes ``{n}`` (the second one ``{m}``).

The seeder only adds entries, marked ``seeded-from-template`` with type
``string`` and no value rules, so they never produce an error: they say
"Veyra writes this setting" until someone cites the vendor's guide. Run it
by hand and review the result like any other catalog change::

    python -m veyra.provisioning.capability_seed ../provisioning/capabilities/poly/vvx
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from veyra.provisioning import base_edits
from veyra.provisioning.capabilities import FAMILY_FILENAME, Family, Release, load_family
from veyra.provisioning.renderer import TemplateCatalog

_COMMENT_TAG = re.compile(r"\{#.*?#\}", re.DOTALL)
_STATEMENT = re.compile(r"\{%.*?%\}", re.DOTALL)
_EXPRESSION = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_TOKEN = re.compile(r"VEYRATOKEN([0-9]+)X")
_PLACEHOLDERS = ("{n}", "{m}")


@dataclass
class Found:
    pattern: str
    # A concrete name for looking the pattern up (indexes set to 1).
    sample: str
    seen: set[str] = field(default_factory=set)
    where: set[str] = field(default_factory=set)


def _blank(m: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def scan_source(fmt: str, text: str) -> list[tuple[str, str, str]]:
    """``(pattern, sample name, value as written)`` for every setting of a
    template source."""
    exprs: list[str] = []

    def token(m: re.Match[str]) -> str:
        exprs.append(m.group(0))
        return f"VEYRATOKEN{len(exprs) - 1}X"

    text = _COMMENT_TAG.sub(_blank, text)
    text = _STATEMENT.sub(_blank, text)
    text = _EXPRESSION.sub(token, text)
    out = []
    for s in base_edits.settings(fmt, text):
        parts = _TOKEN.split(s.parameter)
        holders = parts[1::2]
        if len(holders) > len(_PLACEHOLDERS):
            continue  # Three indexes: not a setting name the catalog can describe.
        pattern = sample = parts[0]
        for i, literal in enumerate(parts[2::2]):
            pattern += _PLACEHOLDERS[i] + literal
            sample += "1" + literal
        value = _TOKEN.sub(lambda m: exprs[int(m.group(1))], s.value).strip()
        out.append((pattern, sample, value))
    return out


def scan_family(templates: TemplateCatalog, family: Family) -> dict[str, Found]:
    """Every setting the family's templates write into the files it checks."""
    found: dict[str, Found] = {}
    for key in family.info.templates:
        resolved = templates.resolve(key)
        for spec in resolved.files:
            if spec.name not in family.info.files or not spec.source:
                continue
            for record in resolved.chain:
                text = record.sources.get(spec.source)
                if text is None:
                    continue
                for pattern, sample, value in scan_source(spec.format, text):
                    f = found.setdefault(pattern, Found(pattern, sample))
                    if value:
                        f.seen.add(value)
                    f.where.add(f"{record.key} ({spec.source})")
    return found


def missing(templates: TemplateCatalog, family: Family, release: Release) -> list[Found]:
    """Settings the templates write that the release has no entry for, or
    removed."""
    out = []
    for f in scan_family(templates, family).values():
        hit = release.lookup(f.sample)
        if hit is None or hit[0].removed_in is not None:
            out.append(f)
    return sorted(out, key=lambda f: f.pattern)


def _toml_string(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def entry_toml(f: Found) -> str:
    seen = sorted(f.seen)[:8]
    lines = [
        f"[param.{_toml_string(f.pattern)}]",
        'type = "string"',
        'provenance = "seeded-from-template"',
        f"note = {_toml_string('Written by ' + ', '.join(sorted(f.where)))}",
    ]
    if seen:
        lines.append(f"seen = [{', '.join(_toml_string(s) for s in seen)}]")
    return "\n".join(lines) + "\n"


def seed(directory: Path, templates: TemplateCatalog, write: bool = True) -> list[Found]:
    """Append the missing entries to the family's first release file. Only a
    first release (one without ``extends``) is seeded: later releases list
    changes, and a template's new setting belongs where it was added."""
    family, errors = load_family(directory, "seed", _vendor(directory))
    if errors:
        raise SystemExit("\n".join(errors))
    first = family.releases[0]
    todo = missing(templates, family, first)
    if write and todo:
        path = Path(first.path)
        text = path.read_text(encoding="utf-8").rstrip("\n") + "\n"
        text += "".join("\n" + entry_toml(f) for f in todo)
        path.write_text(text, encoding="utf-8")
    return todo


def _vendor(directory: Path) -> str:
    import tomllib

    data = tomllib.loads((directory / FAMILY_FILENAME).read_text(encoding="utf-8"))
    return str(data["family"]["vendor"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("family", type=Path, help="the family directory, e.g. .../poly/vvx")
    parser.add_argument(
        "--templates",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "provisioning" / "templates",
        help="the provisioning templates directory (official/ inside it)",
    )
    parser.add_argument("--dry-run", action="store_true", help="list, do not write")
    args = parser.parse_args(argv)
    templates = TemplateCatalog.from_paths([args.templates])
    todo = seed(args.family, templates, write=not args.dry_run)
    for f in todo:
        print(f.pattern)
    print(f"{len(todo)} entries {'missing' if args.dry_run else 'added'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
