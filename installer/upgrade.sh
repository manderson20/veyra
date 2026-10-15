#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Upgrade an existing Veyra installation from this source tree.
#
# Procedure: preflight → compatibility and disk checks → database and
# configuration backup → build the new release beside the current one →
# stop API/worker → switch release → migrate → restart → verify.
# Asterisk is not restarted, so calls in progress are not interrupted.
#
# If migrations fail they are rolled back (they run in one transaction) and
# the previous release is reactivated automatically. If the new release
# fails verification after migrating, the database has already changed:
# follow the forward-recovery steps printed (docs/UPDATE_MANAGEMENT.md).
#
# Usage: sudo installer/upgrade.sh [--yes] [--dry-run] [--keep-releases N]
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/branding.sh
. "$SCRIPT_DIR/lib/branding.sh"

KEEP_RELEASES=3
SKIP_TELEPHONY=0
ALLOW_PUBLIC=0
LISTEN=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --keep-releases) KEEP_RELEASES="${2:?}"; shift ;;
        -h|--help) sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
    shift
done

require_root
[[ "$(state_get status 2>/dev/null || true)" == "complete" ]] \
    || die "No completed Veyra installation found. Use install.sh (it also resumes unfinished installs)."

OLD_VERSION="$(state_get version)"
OLD_RELEASE_DIR="$(readlink -f "$VEYRA_PREFIX/current")"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SOURCE_DIR/backend/veyra/version.py")"
REVISION="$(git -C "$SOURCE_DIR" rev-parse --short=10 HEAD 2>/dev/null || echo local)"
if [[ "$REVISION" != "local" ]] && ! git -C "$SOURCE_DIR" diff --quiet HEAD -- . 2>/dev/null; then
    REVISION="${REVISION}-dirty"
fi
RELEASE_NAME="${VERSION}-${REVISION}"
RELEASE_DIR="$VEYRA_PREFIX/releases/$RELEASE_NAME"
TELEPHONY_ENGINE="$(sed -n 's/^VEYRA_TELEPHONY_ENGINE=//p' "$VEYRA_ETC/veyra.env")"
[[ "$TELEPHONY_ENGINE" == "none" ]] && SKIP_TELEPHONY=1

# A failed upgrade must not mark the (still working) installation as failed.
STATE_STATUS_KEY="upgrade_status"
# shellcheck source=lib/steps.sh
. "$SCRIPT_DIR/lib/steps.sh"
trap on_error ERR
trap on_exit EXIT

INSTALL_LOG="$VEYRA_LOG_DIR/upgrade-$(date -u +%Y%m%d-%H%M%S).log"
[[ "$DRY_RUN" == "1" ]] && INSTALL_LOG=""
veyra_banner "$SOURCE_DIR" "Upgrade"
info "Installed: $OLD_VERSION ($OLD_RELEASE_DIR)"
info "New:       $RELEASE_NAME"

if [[ "$RELEASE_DIR" == "$OLD_RELEASE_DIR" ]]; then
    ok "This release is already active; nothing to do."
    exit 0
fi
# Semantic-version comparison (pre-release suffixes are compared textually).
if [[ "$OLD_VERSION" != "$VERSION" ]] && version_ge "${OLD_VERSION%%-*}" "${VERSION%%-*}" \
    && [[ "${OLD_VERSION%%-*}" != "${VERSION%%-*}" ]]; then
    die "Refusing to downgrade from $OLD_VERSION to $VERSION (database migrations are not reversible)."
fi

do_preflight

begin capacity "Checking disk space"
db_bytes="$(runuser -u postgres -- psql -tAc "SELECT pg_database_size('$VEYRA_DB_NAME')")"
need_kb=$(( db_bytes * 2 / 1024 + 2 * 1024 * 1024 ))
free_kb="$(df -Pk "$VEYRA_BACKUP_DIR" | awk 'NR==2 {print $4}')"
(( free_kb > need_kb )) || die "Not enough free space for the backup and new release (need $((need_kb / 1024)) MB)."
ok "$((free_kb / 1024)) MB free; $((need_kb / 1024)) MB needed"

begin backup "Backing up the database and configuration"
stamp="$(date -u +%Y%m%d-%H%M%S)"
DB_BACKUP="$VEYRA_BACKUP_DIR/veyra-db-${OLD_VERSION}-${stamp}.dump"
CONF_BACKUP="$VEYRA_BACKUP_DIR/veyra-etc-${OLD_VERSION}-${stamp}.tar.gz"
run bash -c "umask 077; runuser -u postgres -- pg_dump -Fc '$VEYRA_DB_NAME' > '$DB_BACKUP'"
run tar -czf "$CONF_BACKUP" -C / "${VEYRA_ETC#/}"
run chmod 0600 "$CONF_BACKUP"
ok "Database: $DB_BACKUP"
ok "Configuration: $CONF_BACKUP"

echo
info "Expected impact: the web interface and API restart (typically under a minute)."
info "Telephone service is not interrupted: Asterisk is reloaded, not restarted, and only"
info "when its Veyra-managed files changed."
confirm "Upgrade Veyra from $OLD_VERSION to $VERSION now?" || die "Cancelled. Nothing has been changed (backups were kept)."
state_set upgrade_in_progress "$RELEASE_NAME"

do_packages
do_versions
# Credentials introduced after the original installation (kept when present).
do_secrets
do_release

begin switch "Switching to the new release"
run systemctl stop veyra-worker veyra-api
systemctl list-unit-files veyra-deployer.service >/dev/null 2>&1 && run systemctl stop veyra-deployer
do_activate
CURRENT_STEP="migrate"
step "Applying database migrations"
if ! run /usr/local/bin/veyra db upgrade; then
    fail "Migration failed and was rolled back. Restoring the previous release."
    run ln -sfn "$OLD_RELEASE_DIR" "$VEYRA_PREFIX/current.new"
    run mv -T "$VEYRA_PREFIX/current.new" "$VEYRA_PREFIX/current"
    run systemctl start veyra-api veyra-worker
    state_set upgrade_in_progress ""
    die "Upgrade failed; Veyra $OLD_VERSION is running again. Log: $INSTALL_LOG"
fi
ok "Database schema is current"

do_tls
do_telephony
do_services
do_nginx

begin verify "Verifying the upgraded installation"
if [[ "$DRY_RUN" != "1" ]] && ! "$SCRIPT_DIR/verify.sh"; then
    fail "The new release does not pass verification and the database has already been migrated."
    fail "Forward recovery: inspect 'journalctl -u veyra-api', fix and re-run upgrade.sh."
    fail "Full restore (loses changes made since the backup):"
    fail "  sudo systemctl stop veyra-api veyra-worker"
    fail "  sudo runuser -u postgres -- pg_restore --clean --if-exists -d $VEYRA_DB_NAME $DB_BACKUP"
    fail "  sudo ln -sfn $OLD_RELEASE_DIR $VEYRA_PREFIX/current && sudo systemctl start veyra-api veyra-worker"
    exit 1
fi

state_set version "$VERSION"
state_set release "$RELEASE_NAME"
state_set previous_release "$OLD_RELEASE_DIR"
state_set upgrade_in_progress ""
state_set upgrade_status "complete"
state_set upgraded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
[[ "$DRY_RUN" == "1" ]] || /usr/local/bin/veyra updates record --component veyra_core --target veyra \
    --from-version "$OLD_VERSION" --to-version "$VERSION" --outcome success \
    --backup-ref "$DB_BACKUP" || warn "Could not record the upgrade in the update history"

begin prune "Removing old releases (keeping $KEEP_RELEASES)"
mapfile -t releases < <(find "$VEYRA_PREFIX/releases" -mindepth 1 -maxdepth 1 -type d \
    -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
for old in "${releases[@]:$KEEP_RELEASES}"; do
    [[ "$old" == "$RELEASE_DIR" || "$old" == "$OLD_RELEASE_DIR" ]] && continue
    run rm -rf "$old"
    info "Removed $old"
done
if [[ "$OLD_VERSION" == "$VERSION" ]]; then
    ok "Veyra $VERSION upgraded to release $RELEASE_NAME (from $(basename "$OLD_RELEASE_DIR"))."
else
    ok "Veyra upgraded from $OLD_VERSION to $VERSION."
fi
