#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Veyra preflight checks. Read-only: inspects the host and reports whether it
# is ready for installation. Never changes anything.
#
# Usage: preflight.sh [--json] [--role standalone|primary|secondary]
# Exit status: 0 ready, 1 at least one blocking failure, 2 warnings only.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

JSON=0
ROLE="standalone"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --json) JSON=1 ;;
        --role) ROLE="${2:?}"; shift ;;
        -h|--help) sed -n '3,9p' "$0"; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
    shift
done

FAILURES=0
WARNINGS=0
RESULTS=()

record() { # status name message
    local status="$1" name="$2" message="$3"
    RESULTS+=("$status|$name|$message")
    case "$status" in
        fail) FAILURES=$((FAILURES + 1)); [[ $JSON == 1 ]] || fail "$name: $message" ;;
        warn) WARNINGS=$((WARNINGS + 1)); [[ $JSON == 1 ]] || warn "$name: $message" ;;
        *) [[ $JSON == 1 ]] || ok "$name: $message" ;;
    esac
}

check_os() {
    local id version
    id="$(os_release_value ID || true)"
    version="$(os_release_value VERSION_ID || true)"
    if [[ "$id" != "ubuntu" ]]; then
        record fail os "Unsupported operating system '${id:-unknown}'; Ubuntu Server is required."
    elif [[ "$version" == "$SUPPORTED_PRIMARY" ]]; then
        record pass os "Ubuntu $version LTS (primary target)"
    elif [[ "$version" == "$SUPPORTED_SECONDARY" ]]; then
        record warn os "Ubuntu $version LTS (secondary target; package versions differ, see docs/INSTALLATION.md)"
    else
        record fail os "Ubuntu $version is not supported (use $SUPPORTED_PRIMARY or $SUPPORTED_SECONDARY)."
    fi
    local arch
    arch="$(uname -m)"
    case "$arch" in
        x86_64|aarch64) record pass architecture "$arch" ;;
        *) record fail architecture "Unsupported architecture $arch" ;;
    esac
    if [[ -d /usr/share/xsessions ]] && ls /usr/share/xsessions/*.desktop >/dev/null 2>&1; then
        record warn desktop "A desktop environment is installed; Veyra targets Ubuntu Server."
    fi
    if systemctl is-system-running >/dev/null 2>&1 || [[ "$(systemctl is-system-running 2>/dev/null)" == "degraded" ]]; then
        record pass systemd "systemd is running ($(systemctl is-system-running 2>/dev/null || true))"
    else
        record fail systemd "systemd is not running as PID 1"
    fi
}

check_hardware() {
    local cpus mem_kb mem_gb free_root free_var
    cpus="$(nproc)"
    mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
    mem_gb=$(( (mem_kb + 524288) / 1048576 ))
    if (( cpus < 2 )); then record fail cpu "$cpus CPU(s); at least 2 required"
    elif (( cpus < 4 )); then record warn cpu "$cpus CPU(s); 4 or more recommended"
    else record pass cpu "$cpus CPU(s)"; fi
    if (( mem_kb < 1900000 )); then record fail memory "${mem_gb} GB RAM; at least 2 GB required"
    elif (( mem_kb < 3800000 )); then record warn memory "${mem_gb} GB RAM; 4 GB or more recommended"
    else record pass memory "${mem_gb} GB RAM"; fi
    free_root=$(df -Pk / | awk 'NR==2 {print int($4/1048576)}')
    free_var=$(df -Pk /var | awk 'NR==2 {print int($4/1048576)}')
    if (( free_root < 5 )); then record fail disk "Only ${free_root} GB free on /; at least 5 GB required"
    elif (( free_var < 20 )); then record warn disk "${free_var} GB free on /var; 20 GB+ recommended for recordings, voicemail and backups"
    else record pass disk "${free_root} GB free on /, ${free_var} GB on /var"; fi
    # Unallocated LVM space is common after a default Ubuntu Server install.
    if command -v vgs >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
        local vfree
        vfree="$(vgs --noheadings --units g -o vg_free 2>/dev/null | awk '{s+=$1} END {printf "%d", s}')"
        if [[ -n "$vfree" ]] && (( vfree >= 10 )); then
            record warn lvm "${vfree} GB of the LVM volume group is unallocated (see docs/INSTALLATION.md to extend)"
        fi
    fi
}

check_network() {
    if ip route show default 2>/dev/null | grep -q default; then
        record pass route "Default route via $(ip route show default | awk '{print $3; exit}')"
    else
        record fail route "No default route; package installation requires network access"
    fi
    if getent ahosts archive.ubuntu.com >/dev/null 2>&1; then
        record pass dns "DNS resolution works"
    else
        record fail dns "Cannot resolve archive.ubuntu.com"
    fi
    local fqdn
    fqdn="$(hostname -f 2>/dev/null || hostname)"
    if getent hosts "$(hostname)" >/dev/null 2>&1; then
        record pass hostname "$(hostname) ($fqdn) resolves locally"
    else
        record warn hostname "$(hostname) does not resolve; add it to /etc/hosts or DNS"
    fi
    local addr public=0 count=0
    for addr in $(host_addresses); do
        count=$((count + 1))
        is_private_address "$addr" || public=1
    done
    if (( count == 0 )); then
        record fail addresses "No global IP addresses found"
    elif (( public )); then
        record warn addresses "A public IP address is configured; the administrative interface will not listen on it unless --allow-public-admin is given"
    else
        record pass addresses "$(host_addresses | tr '\n' ' ')"
    fi
}

check_time() {
    local synced
    synced="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown)"
    if [[ "$synced" == "yes" ]]; then
        record pass time "Clock synchronized ($(timedatectl show -p Timezone --value 2>/dev/null))"
    else
        record warn time "Clock is not NTP-synchronized; TLS, SIP and HA depend on accurate time"
    fi
}

check_access() {
    if [[ "$(id -u)" -eq 0 ]]; then
        record pass privileges "Running as root"
    elif sudo -n true 2>/dev/null; then
        record pass privileges "sudo available without a password"
    else
        record warn privileges "Not root; install.sh must be run with sudo"
    fi
    if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet ssh.socket 2>/dev/null; then
        record pass ssh "SSH is running (the installer never changes SSH settings)"
    else
        record warn ssh "SSH does not appear to be running"
    fi
}

check_firewall() {
    if ! command -v ufw >/dev/null 2>&1; then
        record pass firewall "ufw is not installed"
        return
    fi
    local status=""
    if [[ "$(id -u)" -eq 0 ]]; then
        status="$( (ufw status 2>/dev/null || true) | head -n1)"
    elif systemctl is-active --quiet ufw 2>/dev/null; then
        status="Status: active (service)"
    fi
    if [[ "$status" == *" active"* ]]; then
        record warn firewall "ufw is active; the installer does not change firewall rules. Required ports are listed in docs/NETWORKING.md"
    elif [[ -n "$status" ]]; then
        record pass firewall "ufw is inactive"
    else
        record pass firewall "ufw service is not active"
    fi
}

check_services() {
    local svc
    for svc in apache2 freeswitch lighttpd; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            record fail "service:$svc" "$svc is running and conflicts with Veyra"
        fi
    done
    for svc in postgresql nginx asterisk; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            record warn "service:$svc" "$svc is already running; the installer will reuse it and back up any configuration it changes"
        fi
    done
    local port
    for port in 80 443; do
        if port_in_use "$port" && ! systemctl is-active --quiet nginx 2>/dev/null; then
            record fail "port:$port" "TCP port $port is in use by another program"
        fi
    done
    if port_in_use "$VEYRA_API_PORT" && ! systemctl is-active --quiet veyra-api 2>/dev/null; then
        record fail "port:$VEYRA_API_PORT" "TCP port $VEYRA_API_PORT (Veyra API, loopback) is in use"
    fi
    if [[ -r "$STATE_FILE" ]]; then
        local status version
        status="$(state_get status || true)"; version="$(state_get version || true)"
        if [[ "$status" == "complete" ]]; then
            record warn existing "Veyra $version is already installed; use upgrade.sh to upgrade"
        elif [[ "$status" == "uninstalled" ]]; then
            record pass existing "Veyra was uninstalled with its data kept; install.sh will reuse it"
        else
            record warn existing "A previous installation did not finish (state: ${status:-unknown}); install.sh will resume"
        fi
    fi
    if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
        record fail apt "The package manager is busy (another apt/dpkg process is running)"
    fi
}

check_role() {
    case "$ROLE" in
        standalone) record pass role "standalone" ;;
        primary|secondary)
            record warn role "HA roles are accepted for planning only; HA installation arrives in Milestone 16" ;;
        *) record fail role "Unknown role '$ROLE'" ;;
    esac
}

[[ $JSON == 1 ]] || { . "$SCRIPT_DIR/lib/branding.sh"; veyra_banner "$(dirname "$SCRIPT_DIR")" "Preflight"; step "Preflight checks"; }
check_os
check_hardware
check_network
check_time
check_access
check_firewall
check_services
check_role

if [[ $JSON == 1 ]]; then
    python3 - "${RESULTS[@]}" <<'PY'
import json, sys
items = [dict(zip(("status", "check", "message"), r.split("|", 2))) for r in sys.argv[1:]]
print(json.dumps({"checks": items,
                  "failures": sum(i["status"] == "fail" for i in items),
                  "warnings": sum(i["status"] == "warn" for i in items)}, indent=2))
PY
else
    echo
    if (( FAILURES )); then fail "$FAILURES blocking problem(s), $WARNINGS warning(s). Fix the failures and run again."
    elif (( WARNINGS )); then warn "Ready with $WARNINGS warning(s)."
    else ok "All checks passed."; fi
fi
(( FAILURES )) && exit 1
(( WARNINGS )) && exit 2
exit 0
