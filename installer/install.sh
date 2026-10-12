#!/usr/bin/env bash
# Veyra installer for Ubuntu Server (26.04 LTS primary, 24.04 LTS secondary).
#
# Installs and configures everything Veyra needs on a fresh Ubuntu Server:
# system packages, PostgreSQL, Asterisk, Python backend, web frontend, NGINX,
# systemd services, service account, credentials, database schema and TLS.
# Safe to re-run: every step checks current state first, existing
# configuration is backed up before it is replaced, and a failed run can be
# resumed by running the installer again.
#
# Usage: sudo installer/install.sh [options]
#   --yes                    Do not ask for confirmation
#   --dry-run                Show what would be done without changing anything
#   --skip-telephony         Do not install or configure Asterisk
#   --listen ADDR            Address for the web interface (repeatable; default:
#                            this host's private addresses and 127.0.0.1)
#   --allow-public-admin     Also listen on public addresses (not recommended)
#   --role standalone        Installation role (HA roles arrive in Milestone 16)
#   -h, --help               Show this help
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/branding.sh
. "$SCRIPT_DIR/lib/branding.sh"

SKIP_TELEPHONY=0
ALLOW_PUBLIC=0
ROLE="standalone"
LISTEN=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --skip-telephony) SKIP_TELEPHONY=1 ;;
        --allow-public-admin) ALLOW_PUBLIC=1 ;;
        --listen) LISTEN+=("${2:?--listen requires an address}"); shift ;;
        --role) ROLE="${2:?}"; shift ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
    shift
done

[[ "$ROLE" == "standalone" ]] || die "Only --role standalone is supported in this release (HA: Milestone 16)."

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SOURCE_DIR/backend/veyra/version.py")"
[[ -n "$VERSION" ]] || die "Cannot determine the Veyra version from $SOURCE_DIR"
REVISION="$(git -C "$SOURCE_DIR" rev-parse --short=10 HEAD 2>/dev/null || echo local)"
RELEASE_NAME="${VERSION}-${REVISION}"
RELEASE_DIR="$VEYRA_PREFIX/releases/$RELEASE_NAME"
TELEPHONY_ENGINE="asterisk"
[[ $SKIP_TELEPHONY == 1 ]] && TELEPHONY_ENGINE="none"
# shellcheck source=lib/steps.sh
. "$SCRIPT_DIR/lib/steps.sh"
trap on_error ERR

# ------------------------------------------------------------------ main

require_root
install -d -m 0750 "$VEYRA_LOG_DIR" 2>/dev/null || true
INSTALL_LOG="$VEYRA_LOG_DIR/install-$(date -u +%Y%m%d-%H%M%S).log"
[[ "$DRY_RUN" == "1" ]] && INSTALL_LOG=""
veyra_banner "$SOURCE_DIR" "Installer"
mode_note=""
[[ "$DRY_RUN" == "1" ]] && mode_note=" (DRY RUN: nothing will be changed)"
info "Veyra $RELEASE_NAME, role: $ROLE, telephony: $TELEPHONY_ENGINE$mode_note"
[[ -n "$INSTALL_LOG" ]] && info "Log: $INSTALL_LOG"
previous_status="$(state_get status 2>/dev/null || true)"
[[ -n "$previous_status" && "$previous_status" != "complete" ]] && warn "Resuming an unfinished installation (last state: $previous_status)"

do_preflight
state_set status "in_progress"
state_set started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
do_packages
do_versions
do_account
do_secrets
do_database
do_release
do_activate
do_migrate
do_tls
do_telephony
do_services
do_nginx

begin verify "Verifying the installation"
if [[ "$DRY_RUN" == "1" ]]; then
    info "[dry-run] would run verify.sh"
else
    "$SCRIPT_DIR/verify.sh" || die "Verification failed; the installation is not complete."
fi
state_set status complete
state_set version "$VERSION"
state_set release "$RELEASE_NAME"
state_set role "$ROLE"
state_set completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
do_setup_token
if [[ "$DRY_RUN" == "1" ]]; then
    info "Dry run complete. Nothing was changed."
else
    ok "Veyra $VERSION is installed."
fi
