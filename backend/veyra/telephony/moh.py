# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold music sets on disk (docs/PAGING_RECORDINGS.md §3.2).

The engine plays a set as a ``mode=files`` class reading ``<moh dir>/<slug>/``.
The API keeps that directory in step with the set: one copy of each library
recording, named by its position so ``sort=alpha`` plays the listed order.
Copies rather than links, so a recording replaced in the library is picked
up at the next play and a deleted set leaves nothing dangling. Asterisk opens
each file when it plays it, so changed audio needs no reload; a changed
track list changes the generated ``musiconhold.conf`` and the deployer
reloads the module.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# A set's folder: its slug, or ``<namespace>_<slug>`` for organizations with
# their own engine namespace (docs/MULTI_TENANCY.md §2).
_DIR_RE = re.compile(r"^(?:[a-z0-9]{1,16}_)?[a-z0-9][a-z0-9-]{0,39}$")


class MohError(Exception):
    pass


def class_dir(base: Path, slug: str) -> Path:
    if not _DIR_RE.match(slug):
        raise MohError(f"hold music slug {slug!r} is not valid")
    return base / slug


def track_name(position: int, prompt_slug: str) -> str:
    """``01-welcome.wav``: the position keeps the listed order under ``sort=alpha``."""
    return f"{position + 1:02d}-{prompt_slug}.wav"


def sync_class(base: Path, slug: str, sources: list[tuple[str, Path]]) -> list[str]:
    """Make ``<base>/<slug>/`` hold exactly the recordings of ``sources``
    (``(prompt slug, file)`` in playing order). Returns the file names.
    Missing source files are skipped with a warning (the library row exists
    but its audio is gone); the set then plays what is there."""
    target = class_dir(base, slug)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MohError(f"the hold music directory {target} could not be created: {e}") from e
    wanted: dict[str, Path] = {}
    for i, (prompt_slug, src) in enumerate(sources):
        if not _SLUG_RE.match(prompt_slug):
            raise MohError(f"recording slug {prompt_slug!r} is not valid")
        wanted[track_name(i, prompt_slug)] = src
    for existing in target.iterdir():
        if existing.name not in wanted and not existing.name.startswith("."):
            try:
                existing.unlink()
            except OSError as e:
                log.warning("Could not remove stale hold music file %s: %s", existing, e)
    names: list[str] = []
    for name, src in wanted.items():
        dest = target / name
        if not src.is_file():
            log.warning("Hold music set %s: recording %s has no audio file", slug, src)
            continue
        try:
            if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
                tmp = dest.with_name(f".{name}.tmp")
                shutil.copyfile(src, tmp)
                tmp.replace(dest)
            else:
                # Same size: compare contents cheaply enough for prompt-sized files.
                if dest.read_bytes() != src.read_bytes():
                    tmp = dest.with_name(f".{name}.tmp")
                    shutil.copyfile(src, tmp)
                    tmp.replace(dest)
        except OSError as e:
            raise MohError(f"the recording could not be copied to {dest}: {e}") from e
        names.append(name)
    return names


def remove_class(base: Path, slug: str) -> None:
    target = class_dir(base, slug)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
