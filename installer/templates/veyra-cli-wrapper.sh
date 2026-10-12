#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# shellcheck disable=SC1090  # sources the fixed environment file below
# Managed by Veyra installer
# Runs the `veyra` administration command as the veyra service account with
# the installation's configuration. Use: sudo veyra <command>
set -euo pipefail
VEYRA_BIN=/opt/veyra/current/backend/.venv/bin/veyra
ENV_FILE=/etc/veyra/veyra.env
if [[ "$(id -un)" == "veyra" ]]; then
    set -a; . "$ENV_FILE"; set +a
    exec "$VEYRA_BIN" "$@"
fi
if [[ "$(id -u)" -ne 0 ]]; then
    echo "veyra: run with sudo (for example: sudo veyra status)" >&2
    exit 1
fi
# shellcheck disable=SC2016  # expanded by the inner shell
exec runuser -u veyra -- bash -c 'set -a; . "$0"; set +a; exec "$1" "${@:2}"' "$ENV_FILE" "$VEYRA_BIN" "$@"
