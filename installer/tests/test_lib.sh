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
printf 'a=@MISSING@\n' >"$TMP/in2"
t "render_template rejects unrendered placeholders" not bash -c \
    ". '$HERE/../lib/common.sh'; render_template '$TMP/in2' '$TMP/out2'"

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

DRY_RUN=1
t "dry-run does not execute" run touch "$TMP/should-not-exist"
t "dry-run left no file" test ! -e "$TMP/should-not-exist"

echo "installer lib tests: $PASS passed, $FAILED failed"
(( FAILED == 0 ))
