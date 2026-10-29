#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The help guides (docs/guides/*.md, docs/GUIDES.md): one source for the
Help pages built into Veyra and for the GitHub wiki.

    guides.py build            write frontend/src/generated/guides.json
    guides.py build --check    fail when that file is out of date
    guides.py wiki OUT [--version V]
                               write the wiki pages into OUT
    guides.py stale            list guides whose features changed after the
                               guide was last reviewed (exit 1 when any)
    guides.py coverage         list web pages no guide covers

A guide declares the code it describes (``covers``). When a commit changes
that code after the guide's own last commit, the guide is *stale*: it must
be reviewed, and the review is a commit to the guide (at least moving
``reviewed`` to the version that ships the change). Releases refuse stale
guides.

Standard library only: the renderer handles the Markdown the guides use
(headings, paragraphs, lists, tables, code, notes, links)."""

from __future__ import annotations

import argparse
import fnmatch
import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDES = ROOT / "docs" / "guides"
OUTPUT = ROOT / "frontend" / "src" / "generated" / "guides.json"
APP = ROOT / "frontend" / "src" / "app" / "(app)"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/manderson20/veyra"

# Sections in the order the Help page and the wiki sidebar show them.
SECTIONS = (
    "Getting started",
    "Phones and devices",
    "Calls and call flows",
    "Paging and bells",
    "Voicemail and fax",
    "Sign-in and security",
    "Companion extension",
    "Maintenance",
    "Using Veyra",
)
AUDIENCES = ("admin", "user")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class GuideError(Exception):
    pass


@dataclass
class Guide:
    slug: str
    path: Path
    title: str
    summary: str
    audience: str
    section: str
    reviewed: str
    covers: list[str]
    pages: list[str]
    body: str
    order: int = 50
    headings: list[dict[str, str]] = field(default_factory=list)

    @property
    def wiki_name(self) -> str:
        return wiki_name(self.title)


def wiki_name(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")


# ------------------------------------------------------------------ reading


def _front_matter(text: str, path: Path) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        raise GuideError(f"{path.name}: no front matter (--- at the top)")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise GuideError(f"{path.name}: front matter not closed with ---")
    meta: dict[str, object] = {}
    key = None
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and key:
            value = meta.setdefault(key, [])
            if not isinstance(value, list):
                raise GuideError(f"{path.name}: {key} mixes a value and a list")
            value.append(line[4:].strip())
            continue
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if not m:
            raise GuideError(f"{path.name}: cannot read front matter line {line!r}")
        key, value = m.group(1), m.group(2).strip()
        meta[key] = value if value else []
    return meta, text[end + 5 :]


def load(root: Path = GUIDES) -> list[Guide]:
    guides = []
    for path in sorted(root.glob("*.md")):
        meta, body = _front_matter(path.read_text(), path)

        def text(key: str, meta: dict[str, object] = meta, path: Path = path) -> str:
            value = meta.get(key)
            if not isinstance(value, str) or not value:
                raise GuideError(f"{path.name}: {key} is missing")
            return value

        def items(key: str, meta: dict[str, object] = meta, path: Path = path) -> list[str]:
            value = meta.get(key, [])
            if not isinstance(value, list):
                raise GuideError(f"{path.name}: {key} must be a list")
            return [str(v) for v in value]

        guides.append(
            Guide(
                slug=path.stem,
                path=path,
                title=text("title"),
                summary=text("summary"),
                audience=text("audience"),
                section=text("section"),
                reviewed=text("reviewed"),
                covers=items("covers"),
                pages=items("pages"),
                order=int(str(meta.get("order") or 50)),
                body=body,
            )
        )
    return guides


def tracked_files() -> list[str]:
    return _git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()


def matches(pattern: str, files: list[str]) -> list[str]:
    return [f for f in files if fnmatch.fnmatchcase(f, pattern)]


def validate(guides: list[Guide], files: list[str] | None = None) -> None:
    files = tracked_files() if files is None else files
    slugs = {g.slug for g in guides}
    problems = []
    for g in guides:
        where = g.path.name
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", g.slug):
            problems.append(f"{where}: file name must be lower case words with dashes")
        if g.audience not in AUDIENCES:
            problems.append(f"{where}: audience must be one of {', '.join(AUDIENCES)}")
        if g.section not in SECTIONS:
            problems.append(f"{where}: section {g.section!r} is not in tools/guides.py SECTIONS")
        if not VERSION.match(g.reviewed):
            problems.append(f"{where}: reviewed must be a version like 0.27.44")
        if not g.covers:
            problems.append(f"{where}: covers must list the code the guide describes")
        for pattern in g.covers:
            if not matches(pattern, files):
                problems.append(f"{where}: covers {pattern!r} matches no file")
        for page in g.pages:
            if not (page.startswith("/") and page.endswith("/")):
                problems.append(f"{where}: page {page!r} must start and end with /")
            elif not route_exists(page):
                problems.append(f"{where}: page {page!r} is not a page of the web interface")
        for target in re.findall(r"\]\(guide:([a-z0-9-]+)(?:#[a-z0-9-]+)?\)", g.body):
            if target not in slugs:
                problems.append(f"{where}: link to unknown guide {target!r}")
        for target in re.findall(r"\]\(app:(/[^)#]*)", g.body):
            if not route_exists(target.split("?")[0]):
                problems.append(f"{where}: link to unknown page {target!r}")
        if re.search(r"^# ", g.body, re.M):
            problems.append(f"{where}: no level-1 heading in the body (the title is one)")
    if problems:
        raise GuideError("\n".join(problems))


def route_exists(page: str) -> bool:
    if page in ("/", "/help/"):
        return True
    return (APP / page.strip("/") / "page.tsx").exists()


# ----------------------------------------------------------------- rendering

_INLINE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<link>\[(?P<text>[^\]]+)\]\((?P<href>[^)\s]+)\))"
    r"|(?P<bold>\*\*(?P<b>.+?)\*\*)"
    r"|(?P<em>(?<![\w*])\*(?P<i>[^*\s][^*]*?)\*(?![\w*]))"
)


def _link(text: str, href: str, target: str, guides: dict[str, Guide]) -> str:
    if href.startswith("guide:"):
        slug, _, anchor = href[6:].partition("#")
        g = guides[slug]
        if target == "app":
            return f'<a href="/help/{slug}/{"#" + anchor if anchor else ""}">{text}</a>'
        return f"[{text}]({g.wiki_name}{'#' + anchor if anchor else ''})"
    if href.startswith("app:"):
        if target == "app":
            return f'<a href="{html.escape(href[4:])}">{text}</a>'
        return f"**{text}**"
    if href.startswith("repo:"):
        url = f"{REPO_URL}/blob/main/{href[5:]}"
        if target == "app":
            return f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">{text}</a>'
        return f"[{text}]({url})"
    if target == "app":
        return f'<a href="{html.escape(href)}" target="_blank" rel="noreferrer">{text}</a>'
    return f"[{text}]({href})"


def inline(text: str, guides: dict[str, Guide], target: str = "app") -> str:
    """Inline Markdown to HTML (target "app") or to wiki Markdown with the
    guide-only link schemes resolved (target "wiki")."""
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        before = text[pos : m.start()]
        out.append(html.escape(before, quote=False) if target == "app" else before)
        if m.group("code"):
            code = m.group("code")
            out.append(f"<code>{html.escape(code[1:-1])}</code>" if target == "app" else code)
        elif m.group("link"):
            label = inline(m.group("text"), guides, target)
            out.append(_link(label, m.group("href"), target, guides))
        elif m.group("bold"):
            inner = inline(m.group("b"), guides, target)
            out.append(f"<strong>{inner}</strong>" if target == "app" else f"**{inner}**")
        else:
            inner = inline(m.group("i"), guides, target)
            out.append(f"<em>{inner}</em>" if target == "app" else f"*{inner}*")
        pos = m.end()
    rest = text[pos:]
    out.append(html.escape(rest, quote=False) if target == "app" else rest)
    return "".join(out)


def anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"[`*]", "", text).lower()).strip("-")


_LIST = re.compile(r"^( *)([-*]|\d+\.) +(.*)$")
_NOTE = re.compile(r"^\*\*(Note|Tip|Important|Warning):\*\*\s*", re.I)


def render(body: str, guides: dict[str, Guide]) -> tuple[str, list[dict[str, str]]]:
    """Guide Markdown to HTML, and the guide's level-2 headings."""
    lines = body.strip("\n").splitlines()
    out: list[str] = []
    headings: list[dict[str, str]] = []
    i = 0

    def para(buf: list[str]) -> None:
        if buf:
            out.append(f"<p>{inline(' '.join(s.strip() for s in buf), guides)}</p>")
            buf.clear()

    buf: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            para(buf)
            i += 1
            continue
        if line.startswith("```"):
            para(buf)
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            code = "\n".join(lines[i + 1 : j])
            out.append(f"<pre><code>{html.escape(code)}</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{2,4}) +(.*)$", line)
        if m:
            para(buf)
            level, text = len(m.group(1)), m.group(2).strip()
            a = anchor(text)
            if level == 2:
                headings.append({"id": a, "title": re.sub(r"[`*]", "", text)})
            out.append(f'<h{level} id="{a}">{inline(text, guides)}</h{level}>')
            i += 1
            continue
        if line.startswith(">"):
            para(buf)
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            text = " ".join(quote)
            kind = "note"
            n = _NOTE.match(text)
            if n:
                kind = n.group(1).lower()
                text = text[n.end() :]
            out.append(f'<div class="help-note help-note--{kind}">{inline(text, guides)}</div>')
            continue
        if line.startswith("|"):
            para(buf)
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, rest = (
                rows[0],
                [r for r in rows[1:] if not all(re.match(r"^:?-+:?$", c) for c in r)],
            )
            th = "".join(f"<th>{inline(c, guides)}</th>" for c in head)
            trs = "".join(
                "<tr>" + "".join(f"<td>{inline(c, guides)}</td>" for c in r) + "</tr>" for r in rest
            )
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>")
            continue
        if _LIST.match(line):
            para(buf)
            block = []
            while i < len(lines) and (
                _LIST.match(lines[i])
                or (lines[i].startswith("  ") and lines[i].strip())
                or (
                    not lines[i].strip()
                    and i + 1 < len(lines)
                    and (_LIST.match(lines[i + 1]) or lines[i + 1].startswith("   "))
                )
            ):
                block.append(lines[i])
                i += 1
            out.append(_render_list(block, guides))
            continue
        buf.append(line)
        i += 1
    para(buf)
    return "\n".join(out), headings


def _continues(lines: list[str], i: int) -> bool:
    """A blank line inside a list: the list goes on after it."""
    return i < len(lines) and bool(_LIST.match(lines[i]) or lines[i].startswith("   "))


def _render_list(block: list[str], guides: dict[str, Guide]) -> str:
    """A list, with items continued on indented lines and lists nested by
    indentation."""
    items: list[tuple[int, str, list[str]]] = []  # indent, marker, lines
    for line in block:
        if not line.strip():
            continue
        m = _LIST.match(line)
        if m:
            items.append((len(m.group(1)), m.group(2), [m.group(3)]))
        else:
            items[-1][2].append(line.strip())

    def build(start: int, indent: int) -> tuple[str, int]:
        ordered = items[start][1][0].isdigit()
        tag = "ol" if ordered else "ul"
        parts: list[str] = []
        k = start
        while k < len(items) and items[k][0] >= indent:
            ind, _, text = items[k]
            if ind > indent:
                sub, k = build(k, ind)
                parts[-1] = parts[-1][: -len("</li>")] + sub + "</li>"
                continue
            parts.append(f"<li>{inline(' '.join(text), guides)}</li>")
            k += 1
        return f"<{tag}>{''.join(parts)}</{tag}>", k

    html_out, _ = build(0, items[0][0])
    return html_out


# ---------------------------------------------------------------- versions


def release_dates() -> dict[str, str]:
    """Version → release date, from the CHANGELOG's ``## X — date`` headings."""
    dates = {}
    for m in re.finditer(r"^## (\d+\.\d+\.\d+) — (\d{4}-\d{2}-\d{2})", CHANGELOG.read_text(), re.M):
        dates[m.group(1)] = m.group(2)
    return dates


# ------------------------------------------------------------------- outputs


def build_payload(guides: list[Guide]) -> dict[str, object]:
    by_slug = {g.slug: g for g in guides}
    dates = release_dates()
    entries = []
    for g in sorted(guides, key=lambda g: (SECTIONS.index(g.section), g.order, g.title)):
        body, headings = render(g.body, by_slug)
        entries.append(
            {
                "slug": g.slug,
                "title": g.title,
                "summary": g.summary,
                "audience": g.audience,
                "section": g.section,
                "reviewed": g.reviewed,
                "reviewed_date": dates.get(g.reviewed),
                "pages": g.pages,
                "headings": headings,
                "wiki": f"{REPO_URL}/wiki/{g.wiki_name}",
                "html": body,
            }
        )
    return {"sections": list(SECTIONS), "wiki": f"{REPO_URL}/wiki", "guides": entries}


def build_text(guides: list[Guide]) -> str:
    return json.dumps(build_payload(guides), indent=1, ensure_ascii=False) + "\n"


def wiki_pages(guides: list[Guide], version: str, released: str | None) -> dict[str, str]:
    """File name → content for the wiki: one page per guide with a stamp
    saying which release it reflects, a Home index and a sidebar."""
    by_slug = {g.slug: g for g in guides}
    dates = release_dates()
    when = f" (released {released})" if released else ""
    pages: dict[str, str] = {}
    ordered = sorted(guides, key=lambda g: (SECTIONS.index(g.section), g.order, g.title))
    for g in ordered:
        lines = g.body.strip("\n").splitlines()
        out, in_code = [], False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
            out.append(line if in_code else inline(line, by_slug, target="wiki"))
        if g.reviewed == version:
            reviewed = "Reviewed for this release"
        else:
            on = f", {dates[g.reviewed]}" if g.reviewed in dates else ""
            reviewed = f"Last reviewed for Veyra {g.reviewed}{on}; unchanged since"
        stamp = (
            f"> **Reflects Veyra {version}**{when}. {reviewed} — guides are checked again "
            "whenever the feature they describe changes. In Veyra this guide is under "
            f"**Help** ({'for administrators' if g.audience == 'admin' else 'for everyone'})."
        )
        pages[f"{g.wiki_name}.md"] = f"{stamp}\n\n*{g.summary}*\n\n" + "\n".join(out).strip() + "\n"
    index = [
        f"# Veyra guides\n\n> **Reflects Veyra {version}**{when}. Generated from "
        f"[`docs/guides`]({REPO_URL}/tree/main/docs/guides) at every release; "
        "edit the guides there, not here — changes made in the wiki are overwritten.\n",
        "The same guides are built into Veyra under **Help**.\n",
    ]
    side = [f"**Veyra {version}**\n"]
    for section in SECTIONS:
        items = [g for g in ordered if g.section == section]
        if not items:
            continue
        index.append(f"## {section}\n")
        side.append(f"**{section}**\n")
        for g in items:
            who = "" if g.audience == "admin" else " *(for everyone)*"
            index.append(f"- [{g.title}]({g.wiki_name}){who} — {g.summary}")
            side.append(f"- [{g.title}]({g.wiki_name})")
        index.append("")
        side.append("")
    pages["Home.md"] = "\n".join(index)
    pages["_Sidebar.md"] = "\n".join(side)
    pages["_Footer.md"] = (
        f"Veyra {version}{when} · [Source of these pages]({REPO_URL}/tree/main/docs/guides)\n"
    )
    return pages


# ----------------------------------------------------------------- staleness


def _git(*args: str) -> str:
    # A fixed program with arguments from this script, not from input.
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(ROOT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def stale(guides: list[Guide], files: list[str] | None = None) -> list[tuple[Guide, list[str]]]:
    """Guides whose covered code changed after the guide's own last change:
    in a later commit, or uncommitted while the guide is not."""
    files = tracked_files() if files is None else files
    dirty = set(_git("status", "--porcelain", "--untracked-files=all").splitlines())
    dirty_paths = {line[3:].split(" -> ")[-1].strip('"') for line in dirty}
    result = []
    for g in guides:
        rel = str(g.path.relative_to(ROOT))
        covered = sorted({f for p in g.covers for f in matches(p, files)})
        if rel in dirty_paths:
            continue  # being edited now: the review is in progress
        last = _git("log", "-1", "--format=%H", "--", rel)
        changed: set[str] = set()
        if last:
            names = _git("log", "--format=", "--name-only", f"{last}..HEAD", "--", *covered)
            changed |= {n for n in names.splitlines() if n}
        changed |= {p for p in dirty_paths if p in covered}
        if changed:
            result.append((g, sorted(changed)))
    return result


def uncovered_pages(guides: list[Guide]) -> list[str]:
    covered = [p for g in guides for p in g.pages]
    pages = []
    for page in sorted(APP.rglob("page.tsx")):
        route = "/" + str(page.parent.relative_to(APP)).replace("\\", "/").strip(".") + "/"
        route = route.replace("//", "/")
        if not any(route == c or (c != "/" and route.startswith(c)) for c in covered):
            pages.append(route)
    return pages


# ----------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--check", action="store_true")
    w = sub.add_parser("wiki")
    w.add_argument("out", type=Path)
    w.add_argument("--version")
    sub.add_parser("stale")
    sub.add_parser("coverage")
    args = ap.parse_args(argv)

    try:
        guides = load()
        validate(guides)
    except GuideError as e:
        print(e, file=sys.stderr)
        return 2

    if args.cmd == "build":
        text = build_text(guides)
        if args.check:
            current = OUTPUT.read_text() if OUTPUT.exists() else ""
            if current != text:
                print(
                    f"{OUTPUT.relative_to(ROOT)} is out of date: run tools/guides.py build",
                    file=sys.stderr,
                )
                return 1
            return 0
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(text)
        print(f"{len(guides)} guides → {OUTPUT.relative_to(ROOT)}")
        return 0
    if args.cmd == "wiki":
        version = args.version or re.search(
            r'__version__ = "([^"]+)"', (ROOT / "backend/veyra/version.py").read_text()
        ).group(1)  # type: ignore[union-attr]
        args.out.mkdir(parents=True, exist_ok=True)
        for name, content in wiki_pages(guides, version, release_dates().get(version)).items():
            (args.out / name).write_text(content)
        print(f"{len(guides)} guides → {args.out} (Veyra {version})")
        return 0
    if args.cmd == "stale":
        found = stale(guides)
        for g, changed in found:
            print(f"{g.path.relative_to(ROOT)} (reviewed for {g.reviewed}) — changed since:")
            for c in changed[:12]:
                print(f"    {c}")
            if len(changed) > 12:
                print(f"    … and {len(changed) - 12} more")
        if found:
            print(
                f"\n{len(found)} guide(s) need a review: check each against the change, "
                "update it, and move reviewed: to the version that ships the change.",
                file=sys.stderr,
            )
            return 1
        print("Every guide is current.")
        return 0
    if args.cmd == "coverage":
        missing = uncovered_pages(guides)
        for p in missing:
            print(p)
        print(f"{len(missing)} page(s) without a guide.", file=sys.stderr)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
