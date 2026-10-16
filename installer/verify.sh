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

# --- HA role (docs/HIGH_AVAILABILITY.md §5): what node.json says decides
# which services must run here.
HA_ROLE=standalone
if [[ -s "$VEYRA_DATA/ha/node.json" ]]; then
    HA_ROLE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("role") or "standalone")' "$VEYRA_DATA/ha/node.json" 2>/dev/null || echo standalone)"
fi

# --- services
services=(postgresql veyra-api veyra-worker veyra-firewall nginx veyra-ha-agent)
engine_units=()
[[ "$ENGINE" == "asterisk" ]] && engine_units=(asterisk veyra-deployer veyra-pager)
if [[ "$HA_ROLE" == "secondary" ]]; then
    for svc in "${engine_units[@]}"; do
        systemctl is-active --quiet "$svc" \
            && check "service:$svc" fail "running on a standby (the agent stops it)" \
            || check "service:$svc" pass "stopped (standby)"
    done
elif [[ "$HA_ROLE" == "primary" ]]; then
    services+=("${engine_units[@]}")
else
    services+=("${engine_units[@]}")
fi
for svc in "${services[@]}"; do
    if systemctl is-active --quiet "$svc"; then
        check "service:$svc" pass "active"
    else
        check "service:$svc" fail "not active (journalctl -u $svc)"
    fi
    if [[ "$HA_ROLE" != "standalone" ]] && [[ " ${engine_units[*]} " == *" $svc "* ]]; then
        continue  # the agent starts the engine units with the role; not enabled at boot
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
    if grep -qs '^VEYRA_PROVISIONING_HTTP_MODE=full' "$VEYRA_ETC/veyra.env"; then
        check prov-http warn "phone provisioning is also served over plain HTTP in full: SIP secrets cross the network unencrypted"
    else
        check prov-http pass "plain HTTP serves the phone trust bootstrap only (no secrets)"
    fi
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
if [[ -z "$(exposed 5432)" ]]; then
    check postgres-exposure pass "PostgreSQL listens on loopback/socket only"
elif [[ "$HA_ROLE" != "standalone" || -f /etc/postgresql/*/main/conf.d/veyra-ha.conf ]]; then
    check postgres-exposure pass "PostgreSQL listens on the node address for HA replication (TLS, replication role only)"
else
    check postgres-exposure warn "PostgreSQL listens on a network address"
fi
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
    for f in pjsip.conf extensions.conf rtp.conf voicemail.conf queues.conf pjsip_notify.conf musiconhold.conf logger.conf cdr.conf cdr_custom.conf; do
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
    # Call history (docs/REPORTING.md §3.1): unanswered calls logged, the
    # Veyra CSV mapping active, and its file readable by the worker.
    cdr_status="$(asterisk -rx "cdr show status" 2>/dev/null || true)"
    if grep -q "cdr-custom" <<<"$cdr_status" && grep -qE "Log unanswered calls: +Yes" <<<"$cdr_status"; then
        check cdr-custom pass "call records are written for Veyra's call history (unanswered included)"
    else
        check cdr-custom fail "cdr_custom is not active or unanswered calls are not logged (sudo asterisk -rx 'module reload cdr_custom.so'); call history stays empty"
    fi
    if [[ -e /var/log/asterisk/cdr-custom/veyra.csv ]] && ! runuser -u veyra -- test -r /var/log/asterisk/cdr-custom/veyra.csv; then
        check cdr-file fail "/var/log/asterisk/cdr-custom/veyra.csv is not readable by veyra"
    else
        check cdr-file pass "readable by veyra (created with the first call)"
    fi
    # The firewall reads Asterisk's security events (docs/FIREWALL_TRUST.md §4.1).
    if asterisk -rx "logger show channels" 2>/dev/null | grep -q "security.log.*SECURITY"; then
        check security-log pass "Asterisk security events are logged to /var/log/asterisk/security.log"
    else
        check security-log fail "the Asterisk security log channel is not active (sudo asterisk -rx 'logger reload'); SIP attacks are not detected"
    fi
    # Directories shared with Asterisk (Milestone 7): prompts and the mail queue.
    [[ "$(perm "$VEYRA_DATA")" == "750 veyra:asterisk" ]] \
        && check data-dir pass "750 veyra:asterisk" \
        || check data-dir fail "$VEYRA_DATA is $(perm "$VEYRA_DATA") (expected 750 veyra:asterisk)"
    for d in prompts mailqueue mailqueue/failed moh recordings recordings/incoming; do
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
    [[ -x "$VEYRA_PREFIX/current/installer/bin/veyra-vmnotify" ]] \
        && check vmnotify-command pass "executable" \
        || check vmnotify-command fail "$VEYRA_PREFIX/current/installer/bin/veyra-vmnotify is missing or not executable"
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
# --- certificate authority (docs/FIREWALL_TRUST.md §6.2)
if [[ -s "$VEYRA_ETC/tls/ca.crt" ]]; then
    if openssl verify -CAfile "$VEYRA_ETC/tls/ca.crt" "$VEYRA_ETC/tls/veyra.crt" >/dev/null 2>&1; then
        check tls-ca pass "the HTTPS certificate is issued by the Veyra CA"
    else
        check tls-ca pass "the administrator's own certificate is in use (phones need its CA)"
    fi
    [[ "$(perm "$VEYRA_ETC/tls/ca.key")" == "600 root:root" ]] \
        && check tls-ca-key pass "600 root:root" \
        || check tls-ca-key fail "$VEYRA_ETC/tls/ca.key is $(perm "$VEYRA_ETC/tls/ca.key") (expected 600 root:root)"
    cmp -s "$VEYRA_ETC/tls/ca.crt" "$VEYRA_ETC/veyra-ca.crt" \
        && check tls-ca-public pass "public copy for the provisioning bootstrap is current" \
        || check tls-ca-public fail "$VEYRA_ETC/veyra-ca.crt differs from the CA (re-run upgrade.sh); phones cannot be bootstrapped"
else
    check tls-ca warn "no Veyra CA yet (re-run upgrade.sh); phones cannot be bootstrapped to HTTPS"
fi

# --- module catalog (docs/MODULE_CATALOG.md §8)
[[ "$(perm "$VEYRA_DATA/module-store")" == "750 veyra:veyra" ]] \
    && check module-store pass "750 veyra:veyra" \
    || check module-store fail "$VEYRA_DATA/module-store is $(perm "$VEYRA_DATA/module-store") (expected 750 veyra:veyra)"
catalog_keys=("$VEYRA_ETC"/trust/catalog/*.pub)
if [[ -e "${catalog_keys[0]}" ]]; then
    check catalog-trust pass "${#catalog_keys[@]} catalog key(s) trusted"
else
    check catalog-trust warn "no catalog key in $VEYRA_ETC/trust/catalog/: module catalogs cannot be used yet"
fi
grep -qs "Managed by Veyra" /etc/polkit-1/rules.d/50-veyra-services.rules \
    && check services-restart pass "Veyra's services can be restarted from the interface" \
    || check services-restart warn "polkit rule missing: restart Veyra's services on the server after module updates"

# --- updates from the interface (docs/SOFTWARE_UPDATES.md §8)
if [[ -f /etc/systemd/system/veyra-upgrade@.service ]] \
    && grep -qs "veyra-upgrade@" /etc/polkit-1/rules.d/50-veyra-services.rules \
    && [[ "$(perm /var/lib/veyra-upgrade)" == "750 root:veyra" ]]; then
    check upgrade-unit pass "updates can be installed from the interface"
else
    check upgrade-unit warn "veyra-upgrade@.service, its polkit rule or /var/lib/veyra-upgrade missing: install updates with upgrade.sh"
fi

# --- firewall (docs/FIREWALL_TRUST.md §8)
[[ "$(perm "$VEYRA_DATA/firewall")" == "750 veyra:veyra" ]] \
    && check firewall-dir pass "750 veyra:veyra" \
    || check firewall-dir fail "$VEYRA_DATA/firewall is $(perm "$VEYRA_DATA/firewall") (expected 750 veyra:veyra)"
if fw="$(/usr/local/bin/veyra firewall status 2>/dev/null)"; then
    if python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("enabled") else 1)' <<<"$fw"; then
        nft list table inet veyra >/dev/null 2>&1 \
            && check firewall-table pass "on; table inet veyra applied" \
            || check firewall-table fail "the firewall is on but table inet veyra is missing (journalctl -u veyra-firewall)"
    else
        check firewall-table pass "off (System > Firewall turns it on)"
    fi
else
    check firewall-table warn "could not read the firewall settings (veyra firewall status)"
fi

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

# --- high availability (docs/HIGH_AVAILABILITY.md §5): roles must agree, the
# peer must answer, replication must stream and the file sync must be fresh.
if [[ "$HA_ROLE" != "standalone" ]]; then
    if ha="$(/usr/local/bin/veyra ha status --json 2>/dev/null)"; then
        python3 - "$HA_ROLE" <<<"$ha" <<'PY' | while IFS=$'\t' read -r name status msg; do check "$name" "$status" "$msg"; done
import json, sys
role = sys.argv[1]
st = json.load(sys.stdin)
node, rep, sync = st["node"], st.get("replication") or {}, st.get("sync") or {}
out = []
db_role = rep.get("db_role")
agree = (role == "primary" and db_role == "primary" and st.get("holds_address")) or (
    role == "secondary" and db_role == "standby" and not st.get("holds_address")
)
out.append(("ha-role", "pass" if agree else "fail",
            f"{role}, database {db_role}, service address {'held' if st.get('holds_address') else 'not held'}"
            + ("" if agree else " (node.json, the database and the address disagree)")))
if role == "primary":
    state = rep.get("state")
    out.append(("ha-replication", "pass" if state == "streaming" else "warn",
                f"{state or 'no standby connected'}; lag {rep.get('lag_bytes')} bytes"))
else:
    recv = rep.get("receiver")
    out.append(("ha-replication", "pass" if recv == "streaming" else "fail",
                f"WAL receiver {recv or 'stopped'}; replay {rep.get('replay_lsn')}"))
    last = sync.get("last_success_at")
    out.append(("ha-sync", "pass" if last and not sync.get("last_error") else "warn",
                f"last success {last or 'never'} {sync.get('last_error') or ''}".strip()))
peer = st.get("peer") or {}
reach = st.get("peer_reachable")
same = peer.get("version") == st.get("version")
out.append(("ha-peer", "pass" if reach and same else ("warn" if reach else "fail"),
            f"{node.get('peer', {}).get('node_name') or 'no peer'} "
            + ("reachable" if reach else "unreachable")
            + (f", version {peer.get('version')}" + ("" if same else f" (this node {st.get('version')})") if reach else "")))
for row in out:
    print("\t".join(row))
PY
    else
        check ha-agent fail "veyra ha status failed (journalctl -u veyra-ha-agent)"
    fi
fi
