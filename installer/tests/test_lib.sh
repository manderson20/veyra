#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Unit tests for installer helpers. Run: installer/tests/test_lib.sh
# shellcheck disable=SC2034  # variables below are read by the sourced library
# No root required; nothing outside a temporary directory is touched.
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export NO_COLOR=1
# shellcheck source=installer/lib/common.sh
. "$HERE/../lib/common.sh"

PASS=0; FAILED=0
t() { # description command...
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then PASS=$((PASS + 1)); else FAILED=$((FAILED + 1)); echo "FAIL: $desc"; fi
}
not() { ! "$@"; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

t "version_ge equal"            version_ge 26.04 26.04
t "version_ge greater"          version_ge 3.14 3.12
t "version_ge numeric not lexical" version_ge 3.12 3.9
t "version_ge less"             not version_ge 20.8.1 20.9.0

for ip in 127.0.0.1 10.1.2.3 172.16.2.250 172.31.255.1 192.168.1.10 100.64.0.1 ::1 fd00::1 fe80::1; do
    t "private $ip" is_private_address "$ip"
done
for ip in 8.8.8.8 172.32.0.1 172.15.0.1 100.128.0.1 2001:db8::1 1.1.1.1; do
    t "public $ip" not is_private_address "$ip"
done

printf 'a=@ONE@ b=@TWO@\n' >"$TMP/in"
render_template "$TMP/in" "$TMP/out" ONE=1 "TWO=x y"
t "render_template substitutes" grep -qx 'a=1 b=x y' "$TMP/out"
# The NGINX site renders with every placeholder, including the multi-line
# optional HTTP provisioning block (docs/DEVICE_PROVISIONING.md §3.3).
render_template "$HERE/../templates/nginx/veyra.conf.in" "$TMP/nginx.conf" \
    "LISTEN_HTTP=    listen 127.0.0.1:80;" "LISTEN_HTTPS=    listen 127.0.0.1:443 ssl;" \
    API_PORT=8100 VEYRA_ETC=/etc/veyra VEYRA_PREFIX=/opt/veyra VEYRA_DATA=/var/lib/veyra HTTP_PROVISIONING= \
    "CSP_SCRIPT_SRC= 'sha256-abc='"
t "nginx template renders script hashes into the CSP" grep -q "script-src 'self' 'sha256-abc=';" "$TMP/nginx.conf"
t "nginx template sets Permissions-Policy" grep -q 'Permissions-Policy' "$TMP/nginx.conf"
t "nginx template has the provisioning location" grep -q 'location /provisioning/ {' "$TMP/nginx.conf"
t "nginx template includes the HA listen files" grep -q 'include /etc/veyra/nginx-ha-listen-https.conf;' "$TMP/nginx.conf"
t "nginx template serves firmware from the data directory" grep -q 'alias /var/lib/veyra/firmware/;' "$TMP/nginx.conf"
t "nginx template has no HTTP provisioning by default" not grep -q 'Provisioning over plain HTTP' "$TMP/nginx.conf"
block="$(sed -e 's|@VEYRA_DATA@|/var/lib/veyra|g' -e 's|@VEYRA_ETC@|/etc/veyra|g' "$HERE/../templates/nginx/provisioning-http.conf.in")"
render_template "$HERE/../templates/nginx/veyra.conf.in" "$TMP/nginx-http.conf" \
    "LISTEN_HTTP=    listen 127.0.0.1:80;" "LISTEN_HTTPS=    listen 127.0.0.1:443 ssl;" \
    API_PORT=8100 VEYRA_ETC=/etc/veyra VEYRA_PREFIX=/opt/veyra VEYRA_DATA=/var/lib/veyra "HTTP_PROVISIONING=$block" \
    "CSP_SCRIPT_SRC= 'unsafe-inline'"
t "nginx template includes the HTTP provisioning block when enabled" grep -q 'Provisioning over plain HTTP' "$TMP/nginx-http.conf"
t "HTTP provisioning block is rendered" not grep -q '@VEYRA_DATA@' "$TMP/nginx-http.conf"
render_template "$HERE/../templates/veyra.env.in" "$TMP/env" VEYRA_ETC=/etc/veyra VEYRA_DATA=/var/lib/veyra \
    VEYRA_LOG_DIR=/var/log/veyra VEYRA_PREFIX=/opt/veyra DB_NAME=veyra TELEPHONY_ENGINE=asterisk \
    PUBLIC_HOST=pbx.example.invalid PROVISIONING_HTTP=0 PROVISIONING_HTTP_MODE=bootstrap
t "env template carries the public host" grep -qx 'VEYRA_PUBLIC_HOST=pbx.example.invalid' "$TMP/env"
t "env template carries the HTTP provisioning flag" grep -qx 'VEYRA_PROVISIONING_HTTP=0' "$TMP/env"
t "env template carries the HTTP provisioning mode" grep -qx 'VEYRA_PROVISIONING_HTTP_MODE=bootstrap' "$TMP/env"
printf 'a=@MISSING@\n' >"$TMP/in2"
t "render_template rejects unrendered placeholders" not bash -c \
    ". '$HERE/../lib/common.sh'; render_template '$TMP/in2' '$TMP/out2'"

# veyra-mailqueue (Milestone 7): queues standard input as one .eml file.
mkdir -p "$TMP/mq"
printf 'From: a@example.org\nTo: b@example.org\nSubject: t\n\nbody\n' | "$HERE/../bin/veyra-mailqueue" "$TMP/mq"
t "mailqueue writes one .eml"       test "$(find "$TMP/mq" -name '*.eml' | wc -l)" -eq 1
t "mailqueue leaves no temp file"   test -z "$(find "$TMP/mq" -name '.*.tmp')"
t "mailqueue file is group rw"      test "$(stat -c %a "$TMP"/mq/*.eml)" = "660"
t "mailqueue keeps the content"     grep -q '^body$' "$TMP"/mq/*.eml
t "mailqueue refuses empty input"   not bash -c "printf '' | '$HERE/../bin/veyra-mailqueue' '$TMP/mq'"
t "mailqueue refuses a missing dir" not bash -c "printf 'x' | '$HERE/../bin/veyra-mailqueue' '$TMP/nope'"
t "mailqueue still has one file"    test "$(find "$TMP/mq" -name '*.eml' | wc -l)" -eq 1

OS_RELEASE_FILE="$TMP/os-release"
printf 'ID=ubuntu\nVERSION_ID="26.04"\n' >"$OS_RELEASE_FILE"
t "os_release_value ID" test "$(os_release_value ID)" = ubuntu
t "os_release_value VERSION_ID" test "$(os_release_value VERSION_ID)" = 26.04

STATE_FILE="$TMP/state.json"
state_set status in_progress
state_set version 1.2.3
t "state roundtrip" test "$(state_get version)" = 1.2.3
t "state keeps keys" test "$(state_get status)" = in_progress

s1="$(random_secret)"; s2="$(random_secret)"
t "random_secret length" test "${#s1}" -ge 32
t "random_secret unique" test "$s1" != "$s2"

k1="$(random_hex_key)"; k2="$(random_hex_key)"
t "random_hex_key is 64 hex characters" grep -qxE '[0-9a-f]{64}' <<<"$k1"
t "random_hex_key unique" test "$k1" != "$k2"

# Release archives carry REVISION instead of .git (docs/SOFTWARE_UPDATES.md §1.1).
mkdir -p "$TMP/rel"
t "source_revision without git or file" test "$(source_revision "$TMP/rel")" = local
printf 'abc123def0\n' >"$TMP/rel/REVISION"
t "source_revision from REVISION" test "$(source_revision "$TMP/rel")" = abc123def0
printf '../evil;rm\n' >"$TMP/rel/REVISION"
t "source_revision keeps hex only" test "$(source_revision "$TMP/rel")" = e
t "upgrade unit template renders" render_template "$HERE/../templates/systemd/veyra-upgrade@.service.in" \
    "$TMP/up.service" VEYRA_PREFIX=/opt/veyra VEYRA_ETC=/etc/veyra
t "upgrade unit runs the verified runner" grep -q '^ExecStart=/opt/veyra/current/backend/.venv/bin/veyra updates run %i$' "$TMP/up.service"
if command -v node >/dev/null 2>&1; then
    rule_js="$TMP/rule.js"
    { echo 'var polkit={Result:{YES:"yes",NOT_HANDLED:"no"},addRule:function(f){this.f=f}};'
      cat "$HERE/../templates/polkit/50-veyra-services.rules"
      echo 'function q(u,v,user){return polkit.f({id:"org.freedesktop.systemd1.manage-units",lookup:function(k){return k==="unit"?u:v}},{user:user||"veyra"})}'
      echo 'var r=[q("veyra-upgrade@0.18.0.service","start"),q("veyra-upgrade@0.18.0.service","stop"),q("veyra-upgrade@x;y.service","start"),q("veyra-upgrade@0.18.0.service","start","www-data"),q("veyra-api.service","restart"),q("asterisk.service","restart"),q("veyra-backup@run.service","start"),q("veyra-backup@delete-0f0e0d0c-0b0a-0908-0706-050403020100.service","start"),q("veyra-backup@restore.service","start"),q("veyra-backup@run.service","stop")];'
      echo 'process.stdout.write(r.join(","))'; } >"$rule_js"
    t "polkit: start upgrade and backups only, restart Veyra units only" test "$(node "$rule_js")" = "yes,no,no,no,yes,no,yes,yes,no,no"
fi

# High availability (Milestone 16): the agent unit renders and runs as root
# with the runtime directory for its socket; the role helper reads node.json.
render_template "$HERE/../templates/systemd/veyra-ha-agent.service.in" "$TMP/ha.service" \
    VEYRA_PREFIX=/opt/veyra VEYRA_ETC=/etc/veyra
t "ha-agent unit runs the agent" grep -q 'ExecStart=/opt/veyra/current/backend/.venv/bin/veyra ha agent' "$TMP/ha.service"
t "ha-agent unit keeps /run/veyra" grep -qx 'RuntimeDirectory=veyra' "$TMP/ha.service"
t "ha-agent unit is root" grep -qx 'User=root' "$TMP/ha.service"
. "$HERE/../lib/steps.sh" 2>/dev/null || true
VEYRA_DATA="$TMP/data"
t "ha_role without node.json is standalone" test "$(ha_role)" = standalone
mkdir -p "$TMP/data/ha"
echo '{"role": "secondary", "epoch": 3}' >"$TMP/data/ha/node.json"
t "ha_role reads node.json" test "$(ha_role)" = secondary
echo 'not json' >"$TMP/data/ha/node.json"
t "ha_role tolerates a broken node.json" test "$(ha_role)" = standalone
t "install.sh accepts --role secondary with --join and --token" grep -q -- '--join) JOIN_URL=' "$HERE/../install.sh"
t "preflight refuses --role primary" grep -q 'primary) record fail role' "$HERE/../preflight.sh"
render_template "$HERE/../templates/systemd/veyra-backup@.service.in" "$TMP/bk.service" \
    VEYRA_PREFIX=/opt/veyra VEYRA_ETC=/etc/veyra
t "backup unit runs the backup runner" grep -q 'ExecStart=/opt/veyra/current/backend/.venv/bin/veyra backup unit %i' "$TMP/bk.service"
t "backup unit umask keeps backups private" grep -qx 'UMask=0077' "$TMP/bk.service"

DRY_RUN=1
t "dry-run does not execute" run touch "$TMP/should-not-exist"
t "dry-run left no file" test ! -e "$TMP/should-not-exist"

echo "installer lib tests: $PASS passed, $FAILED failed"
(( FAILED == 0 ))
