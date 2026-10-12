#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Veyra terminal wordmark for the installer (shares the wordmark files used by
# the `veyra` command; see backend/veyra/cli/branding.py).
# shellcheck shell=bash

veyra_banner() {
    local root="$1" title="${2:-}"
    local logo="$root/backend/veyra/cli/logo-unicode.txt"
    local charmap
    charmap="$(locale charmap 2>/dev/null || echo ASCII)"
    if [[ "$charmap" != "UTF-8" || "${TERM:-}" == "linux" || -n "${VEYRA_ASCII:-}" ]]; then
        logo="$root/backend/veyra/cli/logo-ascii.txt"
    fi
    [[ -t 1 ]] || { printf 'Veyra - Open Communications Platform%s\n' "${title:+ - $title}"; return 0; }
    local blue="" teal="" dim="" reset=""
    if [[ -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]]; then
        if [[ "${COLORTERM:-}" == "truecolor" || "${COLORTERM:-}" == "24bit" ]]; then
            blue=$'\033[38;2;0;140;255m'; teal=$'\033[38;2;0;212;180m'
        else
            blue=$'\033[38;5;33m'; teal=$'\033[38;5;43m'
        fi
        dim=$'\033[2m'; reset=$'\033[0m'
    fi
    echo
    local i=0 n line
    n=$(wc -l <"$logo")
    while IFS= read -r line; do
        if (( i < n / 2 )); then printf '%s%s%s\n' "$blue" "$line" "$reset"
        else printf '%s%s%s\n' "$teal" "$line" "$reset"; fi
        i=$((i + 1))
    done <"$logo"
    printf '\n%sOpen Communications Platform%s%s\n' "$dim" "${title:+  -  $title}" "$reset"
}
