# SPDX-License-Identifier: AGPL-3.0-or-later
"""The backend and frontend must agree on the version (docs/DEVELOPMENT.md §Versioning)."""

import json
import re
from pathlib import Path

from veyra.version import __version__

REPO = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def test_version_is_semantic_and_matches_the_frontend():
    assert SEMVER.match(__version__), __version__
    package = json.loads((REPO / "frontend" / "package.json").read_text())
    assert package["version"] == __version__
