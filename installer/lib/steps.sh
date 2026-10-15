#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Installation steps shared by install.sh and upgrade.sh. Each step checks the
# current state first, so running it again is safe.
# Expects: SCRIPT_DIR SOURCE_DIR RELEASE_DIR RELEASE_NAME TELEPHONY_ENGINE
#          SKIP_TELEPHONY ALLOW_PUBLIC LISTEN (array), plus lib/common.sh.
# shellcheck shell=bash
# shellcheck disable=SC2154,SC2153  # variables are set by the sourcing script

CURRENT_STEP="start"

# ERR fires for an unexpected command failure; EXIT fires for every exit,
# including die(), so the failure is recorded there (die bypasses the ERR trap).
on_error() {
    local rc=$?
    fail "Installation failed during step '$CURRENT_STEP' (exit $rc)."
    exit "$rc"
}

on_exit() {
    local rc=$?
    (( rc == 0 )) && return 0
    [[ "$DRY_RUN" == "1" ]] && return 0
    [[ -n "$INSTALL_LOG" ]] && fail "Details: $INSTALL_LOG"
    state_set "${STATE_STATUS_KEY:-status}" "failed:$CURRENT_STEP" || true
    fail "Fix the problem and run the installer again; completed steps are skipped or re-verified."
}

begin() { CURRENT_STEP="$1"; step "$2"; }

do_preflight() {
    begin preflight "Checking this server"
    local rc=0
    "$SCRIPT_DIR/preflight.sh" || rc=$?
    if (( rc == 1 )); then
        die "Preflight found blocking problems. Nothing has been changed."
    elif (( rc == 2 )); then
        confirm "Continue despite the warnings above?" || die "Cancelled. Nothing has been changed."
    fi
}

do_packages() {
    begin packages "Installing system packages"
    local pkgs=(python3 python3-venv python3-dev build-essential libpq-dev postgresql nginx
                openssl ca-certificates rsync curl git)
    if [[ ! -d "$SOURCE_DIR/frontend/out" ]]; then
        pkgs+=(nodejs npm)
    fi
    # asterisk-moh-opsound-wav fills the default music-on-hold class that call
    # queues play (docs/RING_GROUPS_QUEUES.md §7); without it callers wait in silence.
    [[ $SKIP_TELEPHONY == 1 ]] || pkgs+=(asterisk asterisk-modules asterisk-core-sounds-en asterisk-moh-opsound-wav)
    # ffmpeg decodes MP3 and other compressed uploads for the audio library
    # (docs/PAGING_RECORDINGS.md §3); without it only WAV uploads are accepted.
    pkgs+=(ffmpeg)
    # nftables: the Veyra firewall's table (docs/FIREWALL_TRUST.md §3).
    pkgs+=(nftables)
    local missing=()
    local p
    for p in "${pkgs[@]}"; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing+=("$p")
    done
    if (( ${#missing[@]} == 0 )); then
        ok "All required packages are installed"
        return
    fi
    info "Installing: ${missing[*]}"
    run apt-get update -q
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${missing[@]}"
    ok "Packages installed"
}

do_versions() {
    begin versions "Checking component versions"
    local py
    py="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    version_ge "$py" "3.12" || die "Python $py found; 3.12 or newer is required."
    ok "Python $py"
    if [[ ! -d "$SOURCE_DIR/frontend/out" ]]; then
        local node
        node="$(node --version 2>/dev/null | tr -d v || true)"
        local node_msg="Node.js ${node:-is not installed}"
        [[ -n "$node" ]] && node_msg="Node.js $node found"
        version_ge "${node:-0}" "20.9.0" || die "$node_msg; 20.9 or newer is needed to build the web interface. On Ubuntu 24.04 use a release bundle with a prebuilt frontend (see docs/INSTALLATION.md)."
        ok "Node.js $node"
    fi
    local pg
    pg="$(psql --version 2>/dev/null | awk '{print $3}' || true)"
    [[ -n "$pg" ]] && ok "PostgreSQL ${pg}"
    if [[ $SKIP_TELEPHONY == 0 ]] && command -v asterisk >/dev/null 2>&1; then
        ok "Asterisk $(asterisk -V 2>/dev/null | awk '{print $2}')"
    fi
}

do_account() {
    begin account "Creating the service account and directories"
    if id -u "$VEYRA_USER" >/dev/null 2>&1; then
        ok "Service account '$VEYRA_USER' exists"
    else
        run useradd --system --home-dir "$VEYRA_DATA" --no-create-home --shell /usr/sbin/nologin \
            --user-group "$VEYRA_USER"
        ok "Created service account '$VEYRA_USER'"
    fi
    run install -d -m 0755 -o root -g root "$VEYRA_PREFIX" "$VEYRA_PREFIX/releases"
    run install -d -m 0750 -o root -g "$VEYRA_USER" "$VEYRA_ETC"
    run install -d -m 0750 -o root -g "$VEYRA_USER" "$VEYRA_ETC/secrets"
    run install -d -m 0755 -o root -g root "$VEYRA_ETC/trust" "$VEYRA_ETC/trust/official" \
        "$VEYRA_ETC/trust/community" "$VEYRA_ETC/trust/third_party"
    run install -d -m 0700 -o root -g root "$VEYRA_ETC/tls"
    run install -d -m 0750 -o "$VEYRA_USER" -g "$VEYRA_USER" "$VEYRA_DATA" "$VEYRA_DATA/modules" \
        "$VEYRA_DATA/provisioning" "$VEYRA_DATA/provisioning/templates" "$VEYRA_LOG_DIR"
    run install -d -m 0700 -o root -g root "$VEYRA_BACKUP_DIR"
    ok "Directories ready"
}

do_secrets() {
    begin secrets "Generating credentials"
    local f="$VEYRA_ETC/secrets/ari_password"
    if [[ -s "$f" ]]; then
        ok "ARI credential exists (kept)"
    elif [[ "$DRY_RUN" == "1" ]]; then
        info "[dry-run] would generate $f"
    else
        (umask 027; random_secret >"$f")
        chown root:"$VEYRA_USER" "$f"
        chmod 0640 "$f"
        ok "Generated ARI credential"
    fi
    # The installation key encrypts SIP secrets (and later MFA secrets) at
    # rest. It is never regenerated: a new key would make every stored secret
    # unreadable. Back it up with the rest of $VEYRA_ETC (docs/EXTENSIONS.md).
    # The Companion signing key gives the browser extension its stable ID
    # (docs/COMPANION.md §5); the release step creates it on first use and the
    # file is kept with the other secrets (root-only: only the installer signs).
    local c="$VEYRA_ETC/secrets/companion-signing.key"
    if [[ -s "$c" ]]; then
        ok "Companion signing key exists (kept)"
    else
        info "Companion signing key will be created when the extension is packaged"
    fi
    local k="$VEYRA_ETC/secrets/installation.key"
    if [[ -s "$k" ]]; then
        ok "Installation key exists (kept)"
    elif [[ "$DRY_RUN" == "1" ]]; then
        info "[dry-run] would generate $k"
    else
        (umask 027; random_hex_key >"$k")
        chown root:"$VEYRA_USER" "$k"
        chmod 0640 "$k"
        ok "Generated installation key; keep a backup of $k (without it SIP secrets cannot be recovered)"
    fi
}

do_database() {
    begin database "Configuring PostgreSQL"
    run systemctl enable --now postgresql
    if [[ "$DRY_RUN" == "1" ]]; then
        info "[dry-run] would create role and database '$VEYRA_DB_NAME' if missing"
        return
    fi
    local role_exists db_exists
    role_exists="$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$VEYRA_DB_ROLE'")"
    if [[ "$role_exists" != "1" ]]; then
        run runuser -u postgres -- psql -qc "CREATE ROLE $VEYRA_DB_ROLE LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
        ok "Created database role '$VEYRA_DB_ROLE' (peer authentication, no password)"
    fi
    db_exists="$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$VEYRA_DB_NAME'")"
    if [[ "$db_exists" != "1" ]]; then
        run runuser -u postgres -- createdb -O "$VEYRA_DB_ROLE" -E UTF8 "$VEYRA_DB_NAME"
        ok "Created database '$VEYRA_DB_NAME'"
    else
        ok "Database '$VEYRA_DB_NAME' exists (kept)"
    fi
    local listen
    listen="$(runuser -u postgres -- psql -tAc "SHOW listen_addresses")"
    if [[ "$listen" != "localhost" && "$listen" != "127.0.0.1" && "$listen" != "" ]]; then
        warn "PostgreSQL listen_addresses is '$listen'. Veyra does not need network access to PostgreSQL; restrict it unless this is intentional (HA replication is configured in Milestone 16)."
    fi
}

do_release() {
    begin release "Installing Veyra $RELEASE_NAME"
    run install -d -m 0755 "$RELEASE_DIR"
    run rsync -a --delete --exclude '.git' --exclude 'node_modules' --exclude '.venv' \
        --exclude '__pycache__' --exclude '.next' --exclude '*.pyc' \
        "$SOURCE_DIR/backend" "$SOURCE_DIR/frontend" "$SOURCE_DIR/modules" \
        "$SOURCE_DIR/provisioning" "$SOURCE_DIR/docs" "$SOURCE_DIR/installer" \
        "$SOURCE_DIR/companion" "$RELEASE_DIR/"

    info "Creating the Python environment"
    run python3 -m venv "$RELEASE_DIR/backend/.venv"
    run "$RELEASE_DIR/backend/.venv/bin/pip" install -q --upgrade pip
    run "$RELEASE_DIR/backend/.venv/bin/pip" install -q --require-virtualenv \
        -r "$RELEASE_DIR/backend/requirements.txt"
    run "$RELEASE_DIR/backend/.venv/bin/pip" install -q --no-deps --require-virtualenv "$RELEASE_DIR/backend"
    ok "Backend installed"

    if [[ -f "$RELEASE_DIR/frontend/out/index.html" ]]; then
        ok "Using prebuilt web interface"
    else
        info "Building the web interface (this takes a few minutes)"
        run bash -c "cd '$RELEASE_DIR/frontend' && npm ci --no-audit --no-fund && npm run build"
        run rm -rf "$RELEASE_DIR/frontend/node_modules" "$RELEASE_DIR/frontend/.next"
        ok "Web interface built"
    fi
    # The Companion browser extension (docs/COMPANION.md): a prebuilt dist/ in
    # the tree is packaged as a zip that the web interface offers for download;
    # without one it is built here when Node.js is available.
    if [[ ! -f "$RELEASE_DIR/companion/dist/manifest.json" ]] && command -v npm >/dev/null 2>&1; then
        info "Building the Companion browser extension"
        run bash -c "cd '$RELEASE_DIR/companion' && npm ci --no-audit --no-fund && npm run build"
        run rm -rf "$RELEASE_DIR/companion/node_modules"
    fi
    if [[ -f "$RELEASE_DIR/companion/dist/manifest.json" ]]; then
        run python3 - "$RELEASE_DIR/companion/dist" "$RELEASE_DIR/companion/veyra-companion.zip" <<'PY'
import os, sys, zipfile
src, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _dirs, files in os.walk(src):
        for name in sorted(files):
            path = os.path.join(root, name)
            z.write(path, os.path.relpath(path, src))
PY
        ok "Companion extension packaged (companion/veyra-companion.zip)"
        # Signed CRX3 for managed browsers (Google Admin Console, policies), with
        # the stable extension ID derived from the signing key.
        if [[ "$DRY_RUN" == "1" ]]; then
            info "[dry-run] would sign companion/veyra-companion.crx with $VEYRA_ETC/secrets/companion-signing.key"
        else
            local public_host; public_host="$(public_host)"
            (umask 077; "$RELEASE_DIR/backend/.venv/bin/python" "$RELEASE_DIR/installer/bin/crx3-pack.py" \
                --key "$VEYRA_ETC/secrets/companion-signing.key" \
                --host-permission "https://$public_host/*" \
                --src "$RELEASE_DIR/companion/dist" \
                --out "$RELEASE_DIR/companion/veyra-companion.crx" \
                --info "$RELEASE_DIR/companion/crx-info.json") >>"${INSTALL_LOG:-/dev/null}" 2>&1 \
                || die "Signing the Companion extension failed (see ${INSTALL_LOG:-the console})"
            chmod 0644 "$RELEASE_DIR/companion/veyra-companion.crx" "$RELEASE_DIR/companion/crx-info.json"
            ok "Companion extension signed (id $(python3 -c "import json;print(json.load(open('$RELEASE_DIR/companion/crx-info.json'))['id'])"))"
        fi
    else
        warn "Companion extension not built (no prebuilt dist/ and no npm); the download will be unavailable"
    fi
    # Modules shipped with the release (docs/MODULE_DEVELOPMENT.md §6) are
    # signed with this server's own key, which is trusted as official, so
    # they can be installed from Modules. The example module stays unsigned
    # (development only).
    local mkey="$VEYRA_ETC/secrets/bundled-modules.key"
    local mpub="$VEYRA_ETC/trust/official/bundled-modules.pub"
    if [[ "$DRY_RUN" == "1" ]]; then
        info "[dry-run] would sign the bundled modules with $mkey"
    else
        if [[ ! -s "$mkey" || ! -s "$mpub" ]]; then
            local ktmp; ktmp="$(mktemp -d)"
            "$RELEASE_DIR/backend/.venv/bin/veyra" modules keygen bundled-modules --output-dir "$ktmp" >/dev/null \
                || die "Creating the module signing key failed"
            install -m 0600 -o root -g root "$ktmp/bundled-modules.key" "$mkey"
            install -m 0644 -o root -g root "$ktmp/bundled-modules.pub" "$mpub"
            rm -rf "$ktmp"
            ok "Created the module signing key ($mkey)"
        fi
        local mdir signed=0
        for mdir in "$RELEASE_DIR"/modules/*/; do
            [[ -f "$mdir/module.toml" ]] || continue
            case "$(basename "$mdir")" in veyra-example-*) continue ;; esac
            "$RELEASE_DIR/backend/.venv/bin/veyra" modules sign "$mdir" --key-file "$mkey" \
                --key-id bundled-modules >>"${INSTALL_LOG:-/dev/null}" 2>&1 \
                || die "Signing the module in $mdir failed (see ${INSTALL_LOG:-the console})"
            signed=$((signed + 1))
        done
        ok "Bundled modules signed ($signed)"
    fi
    run chown -R root:root "$RELEASE_DIR"
    run chmod -R go-w "$RELEASE_DIR"
}

# The name phones and browsers use for this server (installer.conf overrides).
public_host() { printf '%s' "${VEYRA_PUBLIC_HOST:-$(hostname -f 2>/dev/null || hostname)}"; }
provisioning_http() { [[ "${VEYRA_PROVISIONING_HTTP:-0}" == "1" ]] && printf 1 || printf 0; }

do_activate() {
    begin activate "Activating release"
    local previous=""
    [[ -L "$VEYRA_PREFIX/current" ]] && previous="$(readlink "$VEYRA_PREFIX/current")"
    if [[ "$previous" == "$RELEASE_DIR" ]]; then
        ok "Release $RELEASE_NAME is already active"
    else
        run ln -sfn "$RELEASE_DIR" "$VEYRA_PREFIX/current.new"
        run mv -T "$VEYRA_PREFIX/current.new" "$VEYRA_PREFIX/current"
        [[ -n "$previous" ]] && state_set previous_release "$previous"
        ok "Active release: $RELEASE_NAME"
    fi
    local tmp
    tmp="$(mktemp)"
    render_template "$SCRIPT_DIR/templates/veyra.env.in" "$tmp" \
        "VEYRA_ETC=$VEYRA_ETC" "VEYRA_DATA=$VEYRA_DATA" "VEYRA_LOG_DIR=$VEYRA_LOG_DIR" \
        "VEYRA_PREFIX=$VEYRA_PREFIX" "DB_NAME=$VEYRA_DB_NAME" "TELEPHONY_ENGINE=$TELEPHONY_ENGINE" \
        "PUBLIC_HOST=$(public_host)" "PROVISIONING_HTTP=$(provisioning_http)"
    if [[ -f "$VEYRA_ETC/veyra.env" ]] && ! cmp -s "$tmp" "$VEYRA_ETC/veyra.env"; then
        # Keep a locally configured update source across re-installs.
        local url
        url="$(sed -n 's/^VEYRA_UPDATE_METADATA_URL=//p' "$VEYRA_ETC/veyra.env")"
        [[ -n "$url" ]] && sed -i "s|^VEYRA_UPDATE_METADATA_URL=.*|VEYRA_UPDATE_METADATA_URL=$url|" "$tmp"
    fi
    install_managed_file "$tmp" "$VEYRA_ETC/veyra.env" 0640 "root:$VEYRA_USER"
    rm -f "$tmp"
    install_managed_file "$SCRIPT_DIR/templates/veyra-cli-wrapper.sh" /usr/local/bin/veyra 0755 root:root
    ok "Configuration written to $VEYRA_ETC/veyra.env"
}

do_migrate() {
    begin migrate "Applying database migrations"
    run /usr/local/bin/veyra db upgrade
    ok "Database schema is current"
}

# The Veyra CA (docs/FIREWALL_TRUST.md §6.2) signs the server certificate so
# phones can trust it after the provisioning bootstrap installs the CA. The CA
# key stays root-only; public copies go where the API (bootstrap) and NGINX
# (/downloads/veyra-ca.crt) read them. A certificate the administrator
# installed (anything not issued by Veyra) is never replaced.
do_tls() {
    begin tls "Preparing the certificate authority and the HTTPS certificate"
    local dir="$VEYRA_ETC/tls" host fqdn san addr subject issuer cnf
    host="$(hostname -s)"; fqdn="$(hostname -f 2>/dev/null || echo "$host")"
    local names=("$host" localhost)
    [[ "$fqdn" != "$host" ]] && names+=("$fqdn")
    [[ -n "${VEYRA_PUBLIC_HOST:-}" && " ${names[*]} " != *" $VEYRA_PUBLIC_HOST "* ]] && names+=("$VEYRA_PUBLIC_HOST")
    if [[ -s "$dir/ca.key" && -s "$dir/ca.crt" ]]; then
        ok "Certificate authority exists (kept)"
    else
        cnf="$(mktemp)"
        {
            echo "[req]"; echo "distinguished_name = dn"; echo "[dn]"
            echo "[ca]"
            echo "basicConstraints = critical, CA:TRUE, pathlen:0"
            echo "keyUsage = critical, keyCertSign, cRLSign"
            echo "subjectKeyIdentifier = hash"
            # Only this server's host names: a CA installed on phones and
            # browsers cannot vouch for anyone else (IP addresses are not
            # constrained so phones may use the address).
            printf 'nameConstraints = critical'
            for n in "${names[@]}"; do printf ', permitted;DNS:%s' "$n"; done
            echo
        } >"$cnf"
        run openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
            -subj "/CN=Veyra local CA ($fqdn)/O=Veyra local CA" -config "$cnf" -extensions ca \
            -keyout "$dir/ca.key" -out "$dir/ca.crt"
        rm -f "$cnf"
        run chmod 0600 "$dir/ca.key"
        run chmod 0644 "$dir/ca.crt"
        ok "Created the Veyra certificate authority ($dir/ca.crt, 10 years)"
    fi
    run install -m 0644 -o root -g "$VEYRA_USER" "$dir/ca.crt" "$VEYRA_ETC/veyra-ca.crt"
    run install -m 0644 -o root -g root "$dir/ca.crt" "$VEYRA_PREFIX/veyra-ca.crt"

    local reissue=0
    if [[ -s "$dir/veyra.crt" && -s "$dir/veyra.key" ]]; then
        subject="$(openssl x509 -in "$dir/veyra.crt" -noout -subject 2>/dev/null || true)"
        issuer="$(openssl x509 -in "$dir/veyra.crt" -noout -issuer 2>/dev/null || true)"
        if [[ "$subject" == *"Veyra (self-signed)"* ]]; then
            info "Replacing Veyra's self-signed certificate with one issued by the Veyra CA"
            reissue=1
        elif [[ "$issuer" == *"Veyra local CA"* ]]; then
            if ! openssl x509 -in "$dir/veyra.crt" -noout -checkend $((30 * 86400)) >/dev/null 2>&1; then
                info "The certificate expires within 30 days; renewing it"
                reissue=1
            else
                ok "Certificate issued by the Veyra CA kept ($dir/veyra.crt)"
            fi
        else
            ok "Administrator's certificate kept ($dir/veyra.crt); phones need its CA or a public one"
        fi
    else
        reissue=1
    fi
    (( reissue )) || return 0
    san=""
    for n in "${names[@]}"; do san+="${san:+,}DNS:$n"; done
    san+=",IP:127.0.0.1"
    for addr in $(host_addresses); do san+=",IP:$addr"; done
    cnf="$(mktemp)"
    {
        echo "basicConstraints = critical, CA:FALSE"
        echo "keyUsage = critical, digitalSignature"
        echo "extendedKeyUsage = serverAuth"
        echo "subjectAltName = $san"
        echo "authorityKeyIdentifier = keyid"
    } >"$cnf"
    [[ -s "$dir/veyra.crt" ]] && run cp -a "$dir/veyra.crt" "$dir/veyra.crt.veyra-backup-$(date +%Y%m%d%H%M%S)"
    run openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
        -subj "/CN=$fqdn/O=Veyra" -keyout "$dir/veyra.key.new" -out "$dir/veyra.csr"
    run openssl x509 -req -in "$dir/veyra.csr" -CA "$dir/ca.crt" -CAkey "$dir/ca.key" -CAcreateserial \
        -days 825 -sha256 -extfile "$cnf" -out "$dir/veyra.crt.new"
    rm -f "$cnf" "$dir/veyra.csr"
    # The certificate followed by the CA, so clients get the whole chain.
    if [[ "$DRY_RUN" != "1" ]]; then
        cat "$dir/veyra.crt.new" "$dir/ca.crt" >"$dir/veyra.crt.chain"
        mv -f "$dir/veyra.crt.chain" "$dir/veyra.crt"
        mv -f "$dir/veyra.key.new" "$dir/veyra.key"
        rm -f "$dir/veyra.crt.new"
    fi
    run chmod 0600 "$dir/veyra.key"
    run chmod 0644 "$dir/veyra.crt"
    ok "HTTPS certificate issued by the Veyra CA (825 days). Install veyra-ca.crt in browsers to remove the warning (docs/INSTALLATION.md#tls)."
}

do_telephony() {
    [[ $SKIP_TELEPHONY == 1 ]] && { info "Skipping telephony engine (--skip-telephony)"; return; }
    begin telephony "Configuring Asterisk"
    local password tmp core_changed=0 stub_changed=0
    password="$(cat "$VEYRA_ETC/secrets/ari_password" 2>/dev/null || echo DRYRUN)"
    tmp="$(mktemp)"
    render_template "$SCRIPT_DIR/templates/asterisk/ari.conf.in" "$tmp" \
        "ARI_PASSWORD=$password" "VEYRA_ETC=$VEYRA_ETC"
    MANAGED_FILE_CHANGED=0
    install_managed_file "$tmp" /etc/asterisk/ari.conf 0640 root:asterisk
    rm -f "$tmp"
    install_managed_file "$SCRIPT_DIR/templates/asterisk/http.conf" /etc/asterisk/http.conf 0640 root:asterisk
    install_managed_file "$SCRIPT_DIR/templates/asterisk/manager.conf" /etc/asterisk/manager.conf 0640 root:asterisk
    # Module selection needs a restart to take effect, hence a core file.
    install_managed_file "$SCRIPT_DIR/templates/asterisk/modules.conf" /etc/asterisk/modules.conf 0640 root:asterisk
    core_changed=$MANAGED_FILE_CHANGED
    # The service account sends NOTIFY requests through the Asterisk CLI
    # (docs/DEVICE_PROVISIONING.md §3.5): the control socket must be writable
    # by group asterisk. Edited in place in asterisk.conf with a backup.
    # The package ships the settings commented out under a commented-out
    # [files] header; both must be active.
    if [[ -f /etc/asterisk/asterisk.conf ]] && { ! grep -qE '^astctlpermissions *= *0660' /etc/asterisk/asterisk.conf \
        || ! grep -qE '^\[files\]' /etc/asterisk/asterisk.conf; }; then
        if [[ "$DRY_RUN" != "1" ]]; then
            cp -a /etc/asterisk/asterisk.conf "/etc/asterisk/asterisk.conf.veyra-backup-$(date +%Y%m%d%H%M%S)"
            sed -i -E \
                -e 's/^;\[files\]/[files]/' \
                -e 's/^;?astctlpermissions *=.*/astctlpermissions = 0660/' \
                -e 's/^;?astctlgroup *=.*/astctlgroup = asterisk/' \
                /etc/asterisk/asterisk.conf
            grep -qE '^\[files\]' /etc/asterisk/asterisk.conf \
                || printf '\n[files]\nastctlpermissions = 0660\nastctlgroup = asterisk\n' >>/etc/asterisk/asterisk.conf
        fi
        info "Asterisk control socket opened to group asterisk (asterisk.conf; restart needed)"
        core_changed=1
    fi
    # The CLI reads asterisk.conf; let group asterisk (the service account) read it.
    if [[ -f /etc/asterisk/asterisk.conf && "$(stat -c '%G' /etc/asterisk/asterisk.conf)" != "asterisk" ]]; then
        run chgrp asterisk /etc/asterisk/asterisk.conf
        run chmod 0640 /etc/asterisk/asterisk.conf
    fi
    # Stub files that #tryinclude Veyra's generated configuration. The sample
    # files shipped by the package are backed up beside them.
    MANAGED_FILE_CHANGED=0
    local stub
    for stub in pjsip.conf extensions.conf rtp.conf voicemail.conf queues.conf pjsip_notify.conf musiconhold.conf logger.conf; do
        install_managed_file "$SCRIPT_DIR/templates/asterisk/$stub" "/etc/asterisk/$stub" 0640 root:asterisk
    done
    stub_changed=$MANAGED_FILE_CHANGED
    # The include directory is written by the deployer (veyra) and read by
    # Asterisk (group asterisk); setgid keeps new files in that group.
    run install -d -m 2750 -o "$VEYRA_USER" -g asterisk /etc/asterisk/veyra
    run chown "$VEYRA_USER:asterisk" /etc/asterisk/veyra
    run chmod 2750 /etc/asterisk/veyra
    # Data shared with Asterisk (docs/VOICEMAIL_IVR.md §7): it traverses the
    # data directory, writes prompt recordings (*95) under prompts/<org>/incoming
    # and hands voicemail notifications to the mail queue; Veyra's services own
    # both and the setgid bit keeps new files in the asterisk group.
    run chgrp asterisk "$VEYRA_DATA"
    run chmod 0750 "$VEYRA_DATA"
    # Files Asterisk creates there (queued notifications, *95 recordings) are
    # group asterisk, so the service account must be a member of that group
    # to read, rename and delete them.
    if id -nG "$VEYRA_USER" | tr ' ' '\n' | grep -qx asterisk; then
        ok "Service account '$VEYRA_USER' is in group asterisk"
    else
        run usermod -aG asterisk "$VEYRA_USER"
        ok "Added service account '$VEYRA_USER' to group asterisk (effective when the services restart below)"
    fi
    run install -d -m 2770 -o "$VEYRA_USER" -g asterisk "$VEYRA_DATA/prompts" \
        "$VEYRA_DATA/mailqueue" "$VEYRA_DATA/mailqueue/failed" "$VEYRA_DATA/moh"
    run chmod 2770 "$VEYRA_DATA/prompts" "$VEYRA_DATA/mailqueue" "$VEYRA_DATA/mailqueue/failed" \
        "$VEYRA_DATA/moh"
    # Firmware images uploaded through the API, served by NGINX (www-data reads).
    run install -d -m 0755 -o "$VEYRA_USER" -g "$VEYRA_USER" "$VEYRA_DATA/firmware"
    run systemctl enable asterisk
    if (( core_changed )) || ! systemctl is-active --quiet asterisk; then
        run systemctl restart asterisk
    elif (( stub_changed )); then
        # ARI/HTTP unchanged: a reload is enough and does not disturb calls.
        info "Asterisk configuration files changed; reloading (calls are not interrupted)"
        run asterisk -rx "core reload"
    else
        ok "Asterisk configuration unchanged"
    fi
    if [[ "$DRY_RUN" != "1" ]]; then

        for _ in $(seq 1 20); do
            curl -fsS -u "veyra:$password" http://127.0.0.1:8088/ari/asterisk/info >/dev/null 2>&1 && break
            sleep 1
        done
        curl -fsS -u "veyra:$password" http://127.0.0.1:8088/ari/asterisk/info >/dev/null \
            || die "Asterisk started but ARI is not answering on 127.0.0.1:8088"
        # The default music-on-hold class only registers when its directory has
        # files. When asterisk-moh-opsound-wav arrived after Asterisk started,
        # the class is missing and "moh reload" does nothing because
        # musiconhold.conf itself is unchanged; reloading the module re-scans.
        if ! asterisk -rx "moh show classes" 2>/dev/null | grep -q "Class: default"; then
            info "Music-on-hold class 'default' is not loaded; reloading res_musiconhold"
            run asterisk -rx "module unload res_musiconhold.so"
            run asterisk -rx "module load res_musiconhold.so"
        fi
    fi
    ok "Asterisk is running; ARI available on 127.0.0.1 only; AMI disabled"
}

# Units this installation runs. The deployer only exists with a telephony engine.
veyra_units() {
    local units=(veyra-api veyra-worker veyra-firewall)
    [[ "${TELEPHONY_ENGINE:-none}" != "none" ]] && units+=(veyra-deployer veyra-pager)
    printf '%s\n' "${units[@]}"
}

do_services() {
    begin services "Installing and starting Veyra services"
    local unit tmp units=()
    mapfile -t units < <(veyra_units)
    # Before the units start (it is a ReadWritePaths entry). The firewall service keeps its last ruleset and feed lists here (docs/FIREWALL_TRUST.md §3.3).
    run install -d -m 0750 -o "$VEYRA_USER" -g "$VEYRA_USER" "$VEYRA_DATA/firewall"
    for unit in "${units[@]}"; do
        tmp="$(mktemp)"
        render_template "$SCRIPT_DIR/templates/systemd/$unit.service.in" "$tmp" \
            "VEYRA_PREFIX=$VEYRA_PREFIX" "VEYRA_ETC=$VEYRA_ETC" "VEYRA_DATA=$VEYRA_DATA" \
            "VEYRA_LOG_DIR=$VEYRA_LOG_DIR" "API_PORT=$VEYRA_API_PORT"
        install_managed_file "$tmp" "/etc/systemd/system/$unit.service" 0644 root:root
        rm -f "$tmp"
    done
    if [[ "${TELEPHONY_ENGINE:-none}" == "none" && -f /etc/systemd/system/veyra-deployer.service ]]; then
        run systemctl disable --now veyra-deployer veyra-pager || true
        run rm -f /etc/systemd/system/veyra-deployer.service /etc/systemd/system/veyra-pager.service
    fi
    run systemctl daemon-reload
    run systemctl enable "${units[@]}"
    run systemctl restart "${units[@]}"
    if [[ "$DRY_RUN" != "1" ]]; then

        for _ in $(seq 1 30); do
            curl -fsS "http://$VEYRA_API_ADDR:$VEYRA_API_PORT/api/v1/system/ping" >/dev/null 2>&1 && break
            sleep 1
        done
        curl -fsS "http://$VEYRA_API_ADDR:$VEYRA_API_PORT/api/v1/system/ping" >/dev/null \
            || die "veyra-api did not become ready; see: journalctl -u veyra-api"
    fi
    ok "$(IFS=,; echo "${units[*]}") running"
}

listen_directives() {
    local port="$1" extra="$2" addrs=() addr out=""
    if (( ${#LISTEN[@]} )); then
        addrs=("${LISTEN[@]}")
    else
        addrs=(127.0.0.1)
        for addr in $(host_addresses); do
            if is_private_address "$addr" || [[ $ALLOW_PUBLIC == 1 ]]; then
                addrs+=("$addr")
            else
                warn "Not listening on public address $addr (use --allow-public-admin to override)"
            fi
        done
    fi
    for addr in "${addrs[@]}"; do
        [[ "$addr" == *:* ]] && addr="[$addr]"
        out+="    listen ${addr}:${port}${extra};"$'\n'
    done
    printf '%s' "${out%$'\n'}"
}

do_nginx() {
    begin nginx "Configuring NGINX"
    local tmp
    tmp="$(mktemp)"
    local http_prov=""
    if [[ "$(provisioning_http)" == "1" ]]; then
        http_prov="$(sed -e "s|@VEYRA_DATA@|$VEYRA_DATA|g" -e "s|@VEYRA_ETC@|$VEYRA_ETC|g" \
            "$SCRIPT_DIR/templates/nginx/provisioning-http.conf.in")"
        warn "Phone provisioning is also served over plain HTTP (VEYRA_PROVISIONING_HTTP=1): SIP secrets cross the network unencrypted"
    fi
    render_template "$SCRIPT_DIR/templates/nginx/veyra.conf.in" "$tmp" \
        "LISTEN_HTTP=$(listen_directives 80 '')" "LISTEN_HTTPS=$(listen_directives 443 ' ssl')" \
        "API_PORT=$VEYRA_API_PORT" "VEYRA_ETC=$VEYRA_ETC" "VEYRA_PREFIX=$VEYRA_PREFIX" \
        "VEYRA_DATA=$VEYRA_DATA" "HTTP_PROVISIONING=$http_prov"
    # Veyra listens on specific addresses. A reload cannot bind them while
    # NGINX still holds wildcard sockets (the package default site) on the same
    # ports: it binds 443, fails on 80, retries for ~2 s, then drops the whole
    # new configuration and keeps the old one. So the server is restarted
    # whenever the site changes or a wildcard listener is present, and only
    # reloaded otherwise (upgrades with an unchanged site).
    local restart=0
    cmp -s "$tmp" /etc/nginx/sites-available/veyra.conf || restart=1
    [[ -L /etc/nginx/sites-enabled/veyra.conf ]] || restart=1
    install_managed_file "$tmp" /etc/nginx/sites-available/veyra.conf 0644 root:root
    rm -f "$tmp"
    install_managed_file "$SCRIPT_DIR/templates/nginx/proxy.conf" "$VEYRA_ETC/nginx-proxy.conf" 0644 root:root
    run ln -sfn /etc/nginx/sites-available/veyra.conf /etc/nginx/sites-enabled/veyra.conf
    if [[ -L /etc/nginx/sites-enabled/default ]]; then
        # Only the symlink is removed; /etc/nginx/sites-available/default is untouched.
        run rm /etc/nginx/sites-enabled/default
        info "Disabled the NGINX default site (re-enable by restoring its symlink)"
        restart=1
    fi
    if ss -H -ltn '( sport = :80 or sport = :443 )' 2>/dev/null | awk '{print $4}' \
        | grep -qE '^(0\.0\.0\.0|\[::\]|\*):'; then
        info "NGINX holds wildcard listeners on 80/443; a restart is needed to rebind"
        restart=1
    fi
    run nginx -t
    run systemctl enable nginx
    if (( restart )) || ! systemctl is-active --quiet nginx; then
        run systemctl restart nginx
    else
        run systemctl reload nginx
    fi
    if [[ "$DRY_RUN" != "1" ]]; then
        for _ in $(seq 1 15); do
            curl -fsSk -m 3 https://127.0.0.1/api/v1/system/ping >/dev/null 2>&1 && break
            sleep 1
        done
        curl -fsSk -m 3 https://127.0.0.1/api/v1/system/ping >/dev/null 2>&1 \
            || die "NGINX is running but https://127.0.0.1/ does not answer; see /var/log/nginx/error.log"
    fi
    ok "NGINX serving the Veyra web interface over HTTPS"
}

do_setup_token() {
    begin setup "First-run setup"
    [[ "$DRY_RUN" == "1" ]] && { info "[dry-run] would issue a setup token"; return; }
    local token
    if token="$(/usr/local/bin/veyra setup-token --quiet 2>/dev/null)"; then
        echo
        info "Open the web interface and complete setup with this one-time token (valid 24 hours):"
        echo
        printf '      %s%s%s\n\n' "$C_BOLD" "$token" "$C_RESET"
        local addr
        for addr in $(host_addresses); do
            is_private_address "$addr" || continue
            [[ "$addr" == *:* ]] && addr="[$addr]"
            info "  https://$addr/setup/"
        done
        info "Lost it? Run: sudo veyra setup-token"
    else
        ok "Setup was already completed"
    fi
}
