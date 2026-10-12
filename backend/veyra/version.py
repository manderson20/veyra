"""Single source of truth for the Veyra core version (semantic versioning)."""

__version__ = "0.1.0-dev.0"

# Version of the module API exposed to modules. Modules declare a compatible
# range for this (``core_api``) in their manifest. Bumped on any breaking
# change to ``veyra.modules.context.ModuleContext``.
MODULE_API_VERSION = "1.0.0"
