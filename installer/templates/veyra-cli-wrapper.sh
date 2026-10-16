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
as_veyra() {
    # shellcheck disable=SC2016  # expanded by the inner shell
    runuser -u veyra -- bash -c 'set -a; . "$0"; set +a; exec "$1" "${@:2}"' "$ENV_FILE" "$VEYRA_BIN" "$@"
}
# Firewall console recovery (docs/INSTALLATION.md): the database part runs as
# the service account; removing the nftables table needs root, and must work
# even when the database or the firewall service is down.
if [[ "${1:-}" == "firewall" && "${2:-}" == "off" ]]; then
    as_veyra firewall off --database-only || echo "veyra: the database was not updated; removing the table anyway" >&2
    if nft delete table inet veyra 2>/dev/null; then
        echo "Table inet veyra removed."
    else
        echo "Table inet veyra was not present."
    fi
    exit 0
fi
# Installation key rotation (docs/PRODUCTION_HARDENING.md §3.1): root makes
# the new key, the service account re-encrypts the database with it, root
# installs it (keeping the previous key) and restarts the services.
if [[ "${1:-}" == "installation-key" && "${2:-}" == "rotate" ]]; then
    # Only --force is passed through: an unknown flag (or -h/--help, which the
    # inner command would answer with its help text and exit 0) must never
    # reach the step that installs the new key.
    for a in "${@:3}"; do
        case "$a" in
            --force) ;;
            -h|--help)
                echo "Use: sudo veyra installation-key rotate [--force]"
                echo "Generates a new installation key, re-encrypts every stored secret with it,"
                echo "installs it (keeping the previous key as installation.key.previous) and"
                echo "restarts the services. --force rotates even when some ciphertexts do not"
                echo "decrypt with the current key (docs/PRODUCTION_HARDENING.md §3.1)."
                exit 0 ;;
            *) echo "veyra: installation-key rotate takes only --force" >&2; exit 2 ;;
        esac
    done
    KEY=/etc/veyra/secrets/installation.key
    NEW="$(mktemp -p /etc/veyra/secrets .installation.key.XXXXXX)"
    trap 'rm -f "$NEW"' EXIT
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n' >"$NEW"; echo >>"$NEW"
    chown root:veyra "$NEW"; chmod 0640 "$NEW"
    # The new key is installed only when the service account reports a
    # completed rotation ({"rotated": n, ...}); any other exit is a no-op.
    if ! out="$(as_veyra installation-key rotate --new-key "$NEW" "${@:3}")" \
        || [[ "$out" != *'"rotated"'* ]]; then
        echo "veyra: the database was not changed; the current key stays" >&2
        exit 1
    fi
    printf '%s\n' "$out"
    cp -p "$KEY" "$KEY.previous"; chmod 0600 "$KEY.previous"
    mv -f "$NEW" "$KEY"; chown root:veyra "$KEY"; chmod 0640 "$KEY"
    trap - EXIT
    systemctl restart veyra-api veyra-worker 2>/dev/null || true
    systemctl try-restart veyra-deployer veyra-pager veyra-firewall veyra-ha-agent 2>/dev/null || true
    echo "Installation key rotated; the previous key is $KEY.previous (remove it once a backup with the new key is verified)."
    exit 0
fi
as_veyra "$@"
