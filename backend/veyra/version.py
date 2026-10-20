# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single source of truth for the Veyra core version.

Scheme (docs/DEVELOPMENT.md §Versioning): 0.<n>.0 is released when the
n-th milestone in the roadmap order completes (Milestone 4 -> 0.4.0,
Milestone 4b -> 0.5.0, Milestone 5 -> 0.6.0, ...); fixes between milestones
bump the patch number; work in progress carries a ``-dev`` suffix; 1.0.0 is
the public release. frontend/package.json must carry the same version
(tests/test_version.py checks).
"""

__version__ = "0.27.37"

# Version of the module API exposed to modules. Modules declare a compatible
# range for this (``core_api``) in their manifest. Bumped on any breaking
# change to ``veyra.modules.context.ModuleContext``.
MODULE_API_VERSION = "1.3.0"
