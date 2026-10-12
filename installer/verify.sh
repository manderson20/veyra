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

# --- services
services=(postgresql veyra-api veyra-worker nginx)
[[ "$ENGINE" == "asterisk" ]] && services+=(asterisk)
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

# --- permissions
perm() { stat -c '%a %U:%G' "$1" 2>/dev/null || echo missing; }
[[ "$(perm "$VEYRA_ETC/secrets")" == "750 root:veyra" ]] && check secrets-dir pass "750 root:veyra" \
    || check secrets-dir fail "$VEYRA_ETC/secrets is $(perm "$VEYRA_ETC/secrets") (expected 750 root:veyra)"
for f in "$VEYRA_ETC"/secrets/*; do
    [[ -e "$f" ]] || continue
    mode="$(stat -c '%a' "$f")"
    [[ "$mode" == "640" || "$mode" == "600" ]] && check "secret:$(basename "$f")" pass "$mode" \
        || check "secret:$(basename "$f")" fail "mode $mode (expected 640 or 600)"
done
[[ "$(perm "$VEYRA_ETC/tls/veyra.key" | cut -d' ' -f1)" == "600" ]] && check tls-key pass "600" \
    || check tls-key fail "TLS key permissions are $(perm "$VEYRA_ETC/tls/veyra.key")"
# Symbolic links (the venv's python and lib64 links) always report mode 777 and are skipped.
if [[ -n "$(find "$VEYRA_PREFIX/current/" -xdev ! -type l \( -user veyra -o -perm -o+w \) -print -quit 2>/dev/null)" ]]; then
    check code-ownership fail "Application code is writable by the service account or others"
else
    check code-ownership pass "Application code is read-only for the service account"
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
