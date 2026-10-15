# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every library a bundled module imports must be a production dependency
(requirements.txt): the AND clocks module imported httpx, which was only a
development dependency, and could not be installed in production."""

import ast
import re
import sys
from importlib.metadata import packages_distributions

from conftest import REPO


def _names(path):
    out = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.add(re.split(r"[\[=<>~ ]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return out


def test_bundled_module_imports_are_production_dependencies():
    allowed = _names(REPO / "backend" / "requirements.txt")
    dists = packages_distributions()
    missing = []
    for py in sorted((REPO / "modules").glob("*/backend/**/*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                tops = [node.module.split(".")[0]]
            else:
                continue
            for top in tops:
                if top in sys.stdlib_module_names or top in ("veyra", "__future__"):
                    continue
                names = {d.lower().replace("_", "-") for d in dists.get(top, [top])}
                if not names & allowed:
                    missing.append(f"{py.relative_to(REPO)} imports {top}")
    assert not missing, missing
