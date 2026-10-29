# SPDX-License-Identifier: AGPL-3.0-or-later
"""The help guides (docs/GUIDES.md): every guide in the repository is valid,
the built copy for the web interface is current, and the renderer handles
what guides use."""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("guides", ROOT / "tools" / "guides.py")
assert spec and spec.loader
guides = importlib.util.module_from_spec(spec)
sys.modules["guides"] = guides
spec.loader.exec_module(guides)


def test_repository_guides_are_valid_and_built():
    loaded = guides.load()
    assert loaded
    guides.validate(loaded)
    assert guides.OUTPUT.read_text() == guides.build_text(loaded), "run tools/guides.py build"
    assert guides.INDEX.read_text() == guides.index_text(loaded), "run tools/guides.py build"


def _guide(tmp_path, name, front, body="Text."):
    (tmp_path / f"{name}.md").write_text(f"---\n{front}\n---\n{body}\n")


FRONT = """title: A guide
summary: What it does.
audience: admin
section: Getting started
reviewed: 0.27.44
pages:
  - /system/companion/
covers:
  - tools/guides.py"""


def test_validation_names_each_problem(tmp_path):
    _guide(tmp_path, "good", FRONT, "See [the other](guide:missing) and [x](app:/nowhere/).")
    _guide(
        tmp_path,
        "Bad_Name",
        FRONT.replace("admin", "staff").replace("tools/guides.py", "no/such/*"),
    )
    loaded = guides.load(tmp_path)
    try:
        guides.validate(loaded, files=["tools/guides.py"])
    except guides.GuideError as e:
        text = str(e)
    else:
        raise AssertionError("expected problems")
    assert "unknown guide 'missing'" in text
    assert "unknown page '/nowhere/'" in text
    assert "Bad_Name.md: file name" in text
    assert "audience must be" in text
    assert "'no/such/*' matches no file" in text


def test_render_html_and_wiki(tmp_path):
    body = """Intro with **bold**, *em*, `code <b>`, dial \\*97 and [a guide](guide:other#steps).

## Steps

1. First, see [Sign-in](app:/system/sign-in/).
2. Second
   continued line.
   - nested one
   - nested two
3. Third

> **Tip:** A tip.

| A | B |
|---|---|
| 1 | <x> |

```
raw <tag>
```"""
    _guide(tmp_path, "one", FRONT, body)
    _guide(tmp_path, "other", FRONT.replace("A guide", "Other guide"))
    loaded = guides.load(tmp_path)
    by = {g.slug: g for g in loaded}
    html, headings = guides.render(by["one"].body, by)
    assert headings == [{"id": "steps", "title": "Steps"}]
    assert "<strong>bold</strong>" in html and "<em>em</em>" in html
    assert "<code>code &lt;b&gt;</code>" in html
    assert "dial *97 and" in html
    assert '<a href="/help/other/#steps">a guide</a>' in html
    assert '<a href="/system/sign-in/">Sign-in</a>' in html
    assert "<li>Second continued line.<ul><li>nested one</li><li>nested two</li></ul></li>" in html
    assert html.count("<li>") == 5
    assert '<div class="help-note help-note--tip">A tip.</div>' in html
    assert "<td>&lt;x&gt;</td>" in html
    assert "<pre><code>raw &lt;tag&gt;</code></pre>" in html

    pages = guides.wiki_pages(loaded, "0.27.45", "2026-11-02")
    one = pages["A-guide.md"]
    assert one.startswith("> **Reflects Veyra 0.27.45** (released 2026-11-02).")
    assert "Last reviewed for Veyra 0.27.44" in one
    assert "[a guide](Other-guide#steps)" in one and "**Sign-in**" in one
    assert "raw <tag>" in one
    assert "[A guide](A-guide)" in pages["Home.md"] and "_Sidebar.md" in pages


def test_help_links_resolve_to_built_pages():
    data = json.loads(guides.OUTPUT.read_text())
    slugs = {g["slug"] for g in data["guides"]}
    for g in data["guides"]:
        for target in re.findall(r'href="/help/([a-z0-9-]+)/', g["html"]):
            assert target in slugs
