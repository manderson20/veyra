#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Shared helpers for the Veyra installer scripts.
# shellcheck shell=bash

# ---------------------------------------------------------------- constants
# shellcheck disable=SC2034  # used by the scripts that source this file
VEYRA_PREFIX="${VEYRA_PREFIX:-/opt/veyra}"
VEYRA_ETC="${VEYRA_ETC:-/etc/veyra}"
VEYRA_DATA="${VEYRA_DATA:-/var/lib/veyra}"
VEYRA_LOG_DIR="${VEYRA_LOG_DIR:-/var/log/veyra}"
VEYRA_BACKUP_DIR="${VEYRA_BACKUP_DIR:-/var/backups/veyra}"
# Optional site settings for the installer, kept across upgrades. Known keys:
#   VEYRA_PUBLIC_HOST  the host name users and phones type for this server
#                      (Companion host permission and policy, docs/COMPANION.md
#                      §5.1; provisioning URL, docs/DEVICE_PROVISIONING.md §3)
#   VEYRA_PROVISIONING_HTTP  1 to also serve phone provisioning over plain HTTP
#                      (opt-in; docs/DEVICE_PROVISIONING.md §3.3)
#   VEYRA_PROVISIONING_HTTP_MODE  bootstrap (default: plain HTTP hands out only
#                      the Veyra CA and the HTTPS address, docs/FIREWALL_TRUST.md
#                      §6.3) or full (every file, SIP secrets unencrypted)
# shellcheck disable=SC1091
[[ -f "/etc/veyra/installer.conf" ]] && source "/etc/veyra/installer.conf"
VEYRA_USER="veyra"
VEYRA_DB_NAME="veyra"
VEYRA_DB_ROLE="veyra"
VEYRA_API_ADDR="127.0.0.1"
VEYRA_API_PORT="8100"
STATE_FILE="${VEYRA_ETC}/install-state.json"
SUPPORTED_PRIMARY="26.04"
SUPPORTED_SECONDARY="24.04"

DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"
INSTALL_LOG="${INSTALL_LOG:-}"

# ---------------------------------------------------------------- output
_use_color() {
    [[ -z "${NO_COLOR:-}" && -t 1 && "${TERM:-dumb}" != "dumb" ]]
}

if _use_color; then
    C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'; C_BOLD=$'\033[1m'
else
    C_RESET=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_CYAN=""; C_BOLD=""
fi

_log_file() {
    [[ -n "$INSTALL_LOG" ]] && printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$INSTALL_LOG"
    return 0
}

info()  { printf '%s[INFO]%s %s\n' "$C_CYAN" "$C_RESET" "$*"; _log_file "INFO $*"; }
ok() {
    local note=""
    [[ "$DRY_RUN" == "1" ]] && note=" (dry run: not actually changed)"
    printf '%s[ OK ]%s %s%s\n' "$C_GREEN" "$C_RESET" "$*" "$note"; _log_file "OK   $*"
}
warn()  { printf '%s[WARN]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; _log_file "WARN $*"; }
fail()  { printf '%s[FAIL]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; _log_file "FAIL $*"; }
step()  { printf '\n%s==>%s %s%s%s\n' "$C_CYAN" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"; _log_file "STEP $*"; }
die()   { fail "$*"; exit 1; }

# Run a command, or print it in dry-run mode. Output is appended to the log.
run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '%s  [dry-run]%s %s\n' "$C_DIM" "$C_RESET" "$*"
        _log_file "DRY  $*"
        return 0
    fi
    _log_file "RUN  $*"
    if [[ -n "$INSTALL_LOG" ]]; then
        "$@" >>"$INSTALL_LOG" 2>&1
    else
        "$@"
    fi
}

confirm() {
    local prompt="$1"
    [[ "$ASSUME_YES" == "1" ]] && return 0
    [[ -t 0 ]] || die "Confirmation required ($prompt); re-run with --yes to proceed non-interactively."
    local reply
    read -r -p "$prompt [y/N] " reply
    [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

require_root() {
    [[ "$(id -u)" -eq 0 ]] || die "This script must be run as root (use sudo)."
}

# ---------------------------------------------------------------- versions
# version_ge A B  → true when A >= B (dotted numeric versions)
# The commit of a source tree: from git in a checkout, or from the REVISION
# file of a release archive (docs/SOFTWARE_UPDATES.md §1.1).
source_revision() {
    local dir="$1" rev=""
    if [[ -e "$dir/.git" ]] && rev="$(git -C "$dir" rev-parse --short=10 HEAD 2>/dev/null)"; then
        git -C "$dir" diff --quiet HEAD -- . 2>/dev/null || rev="${rev}-dirty"
    elif [[ -s "$dir/REVISION" ]]; then
        rev="$(tr -cd '0-9a-f' <"$dir/REVISION" | head -c 40)"
    fi
    printf '%s' "${rev:-local}"
}

version_ge() {
    [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

os_release_value() {
    local key="$1" file="${OS_RELEASE_FILE:-/etc/os-release}"
    [[ -r "$file" ]] || return 1
    # shellcheck disable=SC1090
    ( . "$file"; eval "printf '%s' \"\${$key:-}\"" )
}

# ---------------------------------------------------------------- files
# backup_file PATH → copies PATH to PATH.veyra-backup-<timestamp> (if it exists)
backup_file() {
    local path="$1"
    [[ -e "$path" ]] || return 0
    local dest
    dest="${path}.veyra-backup-$(date -u +%Y%m%d%H%M%S)"
    run cp -a "$path" "$dest"
    info "Backed up $path to $dest"
}

# install_managed_file SRC DEST MODE OWNER:GROUP MARKER
# Installs SRC to DEST. An existing DEST that does not carry MARKER (i.e. was
# not written by Veyra) is backed up first; an identical file is left alone.
# Sets MANAGED_FILE_CHANGED=1 when it (re)writes DEST, so callers can decide
# whether a service needs a reload.
MANAGED_FILE_CHANGED=0
install_managed_file() {
    local src="$1" dest="$2" mode="$3" owner="$4" marker="${5:-Managed by Veyra}"
    if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
        return 0
    fi
    if [[ -f "$dest" ]] && ! grep -q "$marker" "$dest"; then
        backup_file "$dest"
    fi
    run install -D -m "$mode" -o "${owner%%:*}" -g "${owner##*:}" "$src" "$dest"
    MANAGED_FILE_CHANGED=1
}

# render_template SRC DEST KEY=VALUE...  (replaces @KEY@ placeholders)
render_template() {
    local src="$1" dest="$2"; shift 2
    local content
    content="$(<"$src")"
    local pair key value
    for pair in "$@"; do
        key="${pair%%=*}"; value="${pair#*=}"
        content="${content//@${key}@/${value}}"
    done
    if grep -q '@[A-Z_]\+@' <<<"$content"; then
        die "Unrendered placeholder in $src: $(grep -o '@[A-Z_]\+@' <<<"$content" | head -n1)"
    fi
    printf '%s\n' "$content" >"$dest"
}

random_secret() {
    # 32 bytes of randomness, URL-safe, no padding
    head -c 32 /dev/urandom | base64 | tr -d '=+/\n' | cut -c1-40
}

# 256-bit key as 64 lower-case hexadecimal characters (the installation key
# format read by veyra.core.security.crypto).
random_hex_key() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    fi
}

# ---------------------------------------------------------------- state
state_get() {
    local key="$1"
    [[ -r "$STATE_FILE" ]] || return 1
    python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2]); print("" if v is None else v)' \
        "$STATE_FILE" "$key"
}

state_set() {
    local key="$1" value="$2"
    [[ "$DRY_RUN" == "1" ]] && return 0
    install -d -m 0755 "$(dirname "$STATE_FILE")"
    python3 - "$STATE_FILE" "$key" "$value" <<'PY'
import json, os, sys, tempfile
path, key, value = sys.argv[1:4]
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data[key] = value
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
os.chmod(tmp, 0o644)
os.replace(tmp, path)
PY
}

# ---------------------------------------------------------------- network
# Is an IPv4/IPv6 address private, loopback or link-local?
is_private_address() {
    local ip="$1"
    case "$ip" in
        127.*|10.*|192.168.*|169.254.*) return 0 ;;
        172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) return 0 ;;
        100.6[4-9].*|100.[7-9][0-9].*|100.1[0-1][0-9].*|100.12[0-7].*) return 0 ;; # CGNAT
        ::1|fe80:*|fc*|fd*) return 0 ;;
    esac
    return 1
}

host_addresses() {
    ip -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
}

port_in_use() {
    local port="$1" proto="${2:-tcp}"
    if [[ "$proto" == "udp" ]]; then
        ss -H -lun "sport = :$port" 2>/dev/null | grep -q .
    else
        ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .
    fi
}
