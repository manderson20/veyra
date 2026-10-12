#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Remove Veyra from this server.
#
# By default only the Veyra application, services and web configuration are
# removed. The database, configuration, credentials, voicemail/recordings and
# backups are KEPT so that a later install.sh picks up where you left off.
#
# Usage: sudo installer/uninstall.sh [--yes] [--dry-run] [--purge]
#   --purge   ALSO delete the Veyra database, /etc/veyra and /var/lib/veyra.
#             Requires typing the hostname to confirm. Backups in
#             /var/backups/veyra are never deleted by this script.
# System packages (PostgreSQL, Asterisk, NGINX) are never removed.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

PURGE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --purge) PURGE=1 ;;
        -h|--help) sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
    shift
done
require_root

if [[ ! -e "$STATE_FILE" && ! -d "$VEYRA_PREFIX" ]]; then
    info "Veyra does not appear to be installed; nothing to remove."
    exit 0
fi

step "Removing Veyra"
info "Removes: services, application files ($VEYRA_PREFIX), NGINX site, the veyra command."
if (( PURGE )); then
    warn "PURGE: also deletes the '$VEYRA_DB_NAME' database, $VEYRA_ETC and $VEYRA_DATA."
    if [[ "$DRY_RUN" != "1" ]]; then
        [[ -t 0 ]] || die "--purge must be confirmed interactively."
        read -r -p "Type the hostname ($(hostname -s)) to confirm permanent deletion: " reply
        [[ "$reply" == "$(hostname -s)" ]] || die "Confirmation did not match. Nothing was changed."
    fi
else
    info "Keeps: database, $VEYRA_ETC, $VEYRA_DATA and backups."
    confirm "Remove the Veyra application from this server?" || die "Cancelled."
fi

for svc in veyra-api veyra-worker; do
    if systemctl list-unit-files "$svc.service" >/dev/null 2>&1; then
        run systemctl disable --now "$svc" || true
    fi
    [[ -f "/etc/systemd/system/$svc.service" ]] && run rm -f "/etc/systemd/system/$svc.service"
done
run systemctl daemon-reload

if [[ -e /etc/nginx/sites-enabled/veyra.conf || -e /etc/nginx/sites-available/veyra.conf ]]; then
    run rm -f /etc/nginx/sites-enabled/veyra.conf /etc/nginx/sites-available/veyra.conf
    if systemctl is-active --quiet nginx; then
        run nginx -t && run systemctl reload nginx
    fi
fi
[[ -f /usr/local/bin/veyra ]] && run rm -f /usr/local/bin/veyra
[[ -d "$VEYRA_PREFIX" ]] && run rm -rf "$VEYRA_PREFIX"

if [[ -f /etc/asterisk/ari.conf ]] && grep -q "Managed by Veyra" /etc/asterisk/ari.conf; then
    info "Asterisk still has Veyra's ARI/HTTP settings; backups of the originals are next to them (*.veyra-backup-*)."
fi

if (( PURGE )); then
    run runuser -u postgres -- dropdb --if-exists "$VEYRA_DB_NAME"
    run runuser -u postgres -- psql -qc "DROP ROLE IF EXISTS $VEYRA_DB_ROLE"
    run rm -rf "$VEYRA_ETC" "$VEYRA_DATA"
    if id -u "$VEYRA_USER" >/dev/null 2>&1; then run userdel "$VEYRA_USER"; fi
    ok "Veyra and its data were removed. Backups remain in $VEYRA_BACKUP_DIR."
else
    state_set status "uninstalled" || true
    ok "Veyra was removed. Data was kept; run install.sh to reinstall."
fi
