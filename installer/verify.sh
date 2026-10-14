#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# check() always returns 0, so "cond && check pass || check fail" is safe.
# shellcheck disable=SC2015
# Verify a Veyra installation. Read-only.
#
# Usage: sudo installer/verify.sh [--json]
# Exit status: 0 healthy, 1 one or more checks failed.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

JSON=0
[[ "${1:-}" == "--json" ]] && JSON=1
FAILURES=0
RESULTS=()

check() { # name status message
    RESULTS+=("$2|$1|$3")
    if [[ "$2" == "fail" ]]; then FAILURES=$((FAILURES + 1)); [[ $JSON == 1 ]] || fail "$1: $3"
    elif [[ "$2" == "warn" ]]; then [[ $JSON == 1 ]] || warn "$1: $3"
    else [[ $JSON == 1 ]] || ok "$1: $3"; fi
}

require_root
ENGINE="$(sed -n 's/^VEYRA_TELEPHONY_ENGINE=//p' "$VEYRA_ETC/veyra.env" 2>/dev/null || echo unknown)"

perm() { stat -c '%a %U:%G' "$1" 2>/dev/null || echo missing; }

# --- services
services=(postgresql veyra-api veyra-worker nginx)
[[ "$ENGINE" == "asterisk" ]] && services+=(asterisk veyra-deployer veyra-pager)
for svc in "${services[@]}"; do
    if systemctl is-active --quiet "$svc"; then
        check "service:$svc" pass "active"
    else
        check "service:$svc" fail "not active (journalctl -u $svc)"
    fi
    systemctl is-enabled --quiet "$svc" 2>/dev/null || check "service:$svc" warn "not enabled at boot"
done

# --- application
if curl -fsS "http://$VEYRA_API_ADDR:$VEYRA_API_PORT/api/v1/system/ping" >/dev/null 2>&1; then
    check api pass "API answers on $VEYRA_API_ADDR:$VEYRA_API_PORT"
else
    check api fail "API does not answer on $VEYRA_API_ADDR:$VEYRA_API_PORT"
fi
if curl -fsSk https://127.0.0.1/api/v1/system/ping >/dev/null 2>&1; then
    check https pass "HTTPS proxy to the API works"
else
    check https fail "https://127.0.0.1/api/v1/system/ping failed"
fi
if curl -fsSk https://127.0.0.1/ | grep -qi '<html'; then
    check web pass "Web interface is served"
else
    check web fail "Web interface is not served at https://127.0.0.1/"
fi
if out="$(/usr/local/bin/veyra db current 2>&1)"; then
    check schema pass "$out"
else
    check schema fail "Database schema is not current: $out"
fi

# --- phone provisioning (Milestone 9, docs/DEVICE_PROVISIONING.md §3)
if grep -qs "location /provisioning/" /etc/nginx/sites-available/veyra.conf; then
    check prov-location pass "NGINX serves /provisioning/"
else
    check prov-location fail "NGINX site has no /provisioning/ location (re-run the installer)"
fi
code="$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/provisioning/000000000000.cfg 2>/dev/null || echo 000)"
[[ "$code" == "401" ]] && check prov-auth pass "provisioning requires credentials (401)" \
    || check prov-auth fail "https://127.0.0.1/provisioning/000000000000.cfg answered $code (expected 401)"
if grep -qs '^VEYRA_PROVISIONING_HTTP=1' "$VEYRA_ETC/veyra.env"; then
    check prov-http warn "phone provisioning is also served over plain HTTP: SIP secrets cross the network unencrypted"
else
    check prov-http pass "provisioning over HTTPS only"
fi
[[ "$(perm "$VEYRA_DATA/firmware")" == "755 veyra:veyra" ]] \
    && check firmware-dir pass "755 veyra:veyra" \
    || check firmware-dir fail "$VEYRA_DATA/firmware is $(perm "$VEYRA_DATA/firmware") (expected 755 veyra:veyra)"

# --- audio library (Milestone 9c): compressed uploads need ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then
    check audio-ffmpeg pass "ffmpeg available (MP3 and other compressed uploads accepted)"
else
    check audio-ffmpeg warn "ffmpeg is not installed: the audio library accepts WAV uploads only (apt install ffmpeg)"
fi

# --- exposure
listeners="$(ss -H -ltn 2>/dev/null | awk '{print $4}')"
exposed() { # port → prints non-loopback listeners
    grep -E "[:.]$1\$" <<<"$listeners" | grep -vE '^(127\.0\.0\.1|\[::1\]|::1):' || true
}
[[ -z "$(exposed "$VEYRA_API_PORT")" ]] && check api-exposure pass "API listens on loopback only" \
    || check api-exposure fail "API port $VEYRA_API_PORT is reachable from the network"
[[ -z "$(exposed 5432)" ]] && check postgres-exposure pass "PostgreSQL listens on loopback/socket only" \
    || check postgres-exposure warn "PostgreSQL listens on a network address"
if [[ "$ENGINE" == "asterisk" ]]; then
    [[ -z "$(exposed 8088)" ]] && check ari-exposure pass "ARI listens on loopback only" \
        || check ari-exposure fail "ARI (8088) is reachable from the network"
    [[ -z "$(grep -E '[:.]5038$' <<<"$listeners" || true)" ]] && check ami pass "AMI is disabled" \
        || check ami fail "AMI (5038) is listening"
    if curl -fsS -u "veyra:$(cat "$VEYRA_ETC/secrets/ari_password")" \
        http://127.0.0.1:8088/ari/asterisk/info >/dev/null 2>&1; then
        check ari pass "ARI authenticates"
    else
        check ari fail "ARI does not answer or rejects the Veyra credential"
    fi
fi

# --- engine include directory and stub files (Milestone 3)
if [[ "$ENGINE" == "asterisk" ]]; then
    [[ "$(perm /etc/asterisk/veyra)" == "2750 veyra:asterisk" ]] \
        && check engine-include-dir pass "2750 veyra:asterisk" \
        || check engine-include-dir fail "/etc/asterisk/veyra is $(perm /etc/asterisk/veyra) (expected 2750 veyra:asterisk)"
    for f in pjsip.conf extensions.conf rtp.conf voicemail.conf queues.conf pjsip_notify.conf musiconhold.conf; do
        grep -qs "Managed by Veyra" "/etc/asterisk/$f" \
            && check "engine-stub:$f" pass "Veyra-managed" \
            || check "engine-stub:$f" fail "/etc/asterisk/$f is not the Veyra-managed stub"
    done
    grep -qs "Managed by Veyra" /etc/asterisk/modules.conf \
        && check engine-modules-conf pass "Veyra-managed" \
        || check engine-modules-conf fail "/etc/asterisk/modules.conf is not Veyra-managed (voicemail may not work)"
    # The VoiceMail application must be registered (Milestone 7): a competing
    # voicemail module that failed to load unregisters it.
    app_registered() { # app → 0 when registered (up to three looks, a second apart)
        for _ in 1 2 3; do
            asterisk -rx "core show application $1" 2>/dev/null | grep -qi "Info about application '$1'" && return 0
            sleep 1
        done
        return 1
    }
    if app_registered VoiceMail; then
        check engine-voicemail-app pass "VoiceMail application registered"
    else
        check engine-voicemail-app fail "the VoiceMail application is not registered in Asterisk (restart Asterisk after the modules.conf change: sudo systemctl restart asterisk)"
    fi
    # Queues and call pickup (Milestone 8): the applications must be registered
    # and the default music-on-hold class must have files to play.
    # An application is unregistered for a moment while its module reloads
    # (the deployer reloads app_queue.so right after the services start), so
    # a miss is retried before it counts.
    for app in Queue Pickup PickupChan; do
        if app_registered "$app"; then
            check "engine-app:$app" pass "$app application registered"
        else
            check "engine-app:$app" fail "the $app application is not registered in Asterisk"
        fi
    done
    # Device management (Milestone 9): the service account sends NOTIFY through the CLI.
    if runuser -u veyra -- asterisk -rx "core show version" 2>/dev/null | grep -q "Asterisk"; then
        check engine-cli pass "service account can use the Asterisk CLI (control socket group asterisk)"
    else
        check engine-cli fail "the veyra service account cannot use the Asterisk CLI (asterisk.conf, under an active [files] header: astctlpermissions = 0660, astctlgroup = asterisk, then restart Asterisk); phones cannot be told to reprovision"
    fi
    if asterisk -rx "moh show classes" 2>/dev/null | grep -q "Class: default"; then
        check engine-moh pass "music-on-hold class default is loaded"
    else
        check engine-moh fail "music-on-hold class 'default' is not loaded (install asterisk-moh-opsound-wav, then: sudo asterisk -rx 'module unload res_musiconhold.so' && sudo asterisk -rx 'module load res_musiconhold.so'); queue callers would wait in silence"
    fi
    # Directories shared with Asterisk (Milestone 7): prompts and the mail queue.
    [[ "$(perm "$VEYRA_DATA")" == "750 veyra:asterisk" ]] \
        && check data-dir pass "750 veyra:asterisk" \
        || check data-dir fail "$VEYRA_DATA is $(perm "$VEYRA_DATA") (expected 750 veyra:asterisk)"
    for d in prompts mailqueue mailqueue/failed moh; do
        [[ "$(perm "$VEYRA_DATA/$d")" == "2770 veyra:asterisk" ]] \
            && check "data-dir:$d" pass "2770 veyra:asterisk" \
            || check "data-dir:$d" fail "$VEYRA_DATA/$d is $(perm "$VEYRA_DATA/$d") (expected 2770 veyra:asterisk)"
    done
    id -nG "$VEYRA_USER" 2>/dev/null | tr ' ' '\n' | grep -qx asterisk \
        && check service-groups pass "$VEYRA_USER is in group asterisk" \
        || check service-groups fail "$VEYRA_USER is not in group asterisk (the worker cannot read queued voicemail notifications or *95 recordings)"
    [[ -x "$VEYRA_PREFIX/current/installer/bin/veyra-mailqueue" ]] \
        && check mailqueue-command pass "executable" \
        || check mailqueue-command fail "$VEYRA_PREFIX/current/installer/bin/veyra-mailqueue is missing or not executable"
fi

# --- permissions
[[ "$(perm "$VEYRA_ETC/secrets")" == "750 root:veyra" ]] && check secrets-dir pass "750 root:veyra" \
    || check secrets-dir fail "$VEYRA_ETC/secrets is $(perm "$VEYRA_ETC/secrets") (expected 750 root:veyra)"
for f in "$VEYRA_ETC"/secrets/*; do
    [[ -e "$f" ]] || continue
    mode="$(stat -c '%a' "$f")"
    [[ "$mode" == "640" || "$mode" == "600" ]] && check "secret:$(basename "$f")" pass "$mode" \
        || check "secret:$(basename "$f")" fail "mode $mode (expected 640 or 600)"
done
# The installation key (Milestone 4): present, readable by the service account, well formed.
if [[ -s "$VEYRA_ETC/secrets/installation.key" ]] \
    && grep -qxE '[0-9a-fA-F]{64}' "$VEYRA_ETC/secrets/installation.key" \
    && [[ "$(stat -c '%G' "$VEYRA_ETC/secrets/installation.key")" == "$VEYRA_USER" ]]; then
    check installation-key pass "present (fingerprint $(/usr/local/bin/veyra installation-key check --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("fingerprint", "?"))' 2>/dev/null || echo '?'))"
else
    check installation-key fail "$VEYRA_ETC/secrets/installation.key is missing, malformed or not group $VEYRA_USER (run: sudo veyra installation-key generate)"
fi
# Modules shipped with the release are signed with this server's key
# (docs/MODULE_DEVELOPMENT.md §6); the example module is unsigned on purpose.
if out="$(/usr/local/bin/veyra modules list 2>&1)"; then
    unsigned="$(awk 'NR > 1 && $1 !~ /^veyra\.example-/ && $NF != "official" {print $1}' <<<"$out" | paste -sd' ')"
    [[ -z "$unsigned" ]] && check modules-signed pass "bundled modules verified" \
        || check modules-signed fail "not verified: $unsigned (re-run the upgrade to sign them)"
else
    check modules-signed fail "veyra modules list failed: $(head -1 <<<"$out")"
fi
[[ "$(perm "$VEYRA_ETC/tls/veyra.key" | cut -d' ' -f1)" == "600" ]] && check tls-key pass "600" \
    || check tls-key fail "TLS key permissions are $(perm "$VEYRA_ETC/tls/veyra.key")"
# Symbolic links (the venv's python and lib64 links) always report mode 777 and are skipped.
if [[ -n "$(find "$VEYRA_PREFIX/current/" -xdev ! -type l \( -user veyra -o -perm -o+w \) -print -quit 2>/dev/null)" ]]; then
    check code-ownership fail "Application code is writable by the service account or others"
else
    check code-ownership pass "Application code is read-only for the service account"
fi
if [[ -f "$VEYRA_PREFIX/current/companion/crx-info.json" ]]; then
    check companion-package pass "signed, id $(python3 -c "import json;print(json.load(open('$VEYRA_PREFIX/current/companion/crx-info.json'))['id'])" 2>/dev/null)"
else
    check companion-package warn "Companion extension not packaged; the download is unavailable"
fi

if [[ $JSON == 1 ]]; then
    python3 - "${RESULTS[@]}" <<'PY'
import json, sys
items = [dict(zip(("status", "check", "message"), r.split("|", 2))) for r in sys.argv[1:]]
print(json.dumps({"checks": items, "failures": sum(i["status"] == "fail" for i in items)}, indent=2))
PY
fi
(( FAILURES == 0 )) || { [[ $JSON == 1 ]] || fail "$FAILURES check(s) failed."; exit 1; }
[[ $JSON == 1 ]] || ok "Installation verified."
