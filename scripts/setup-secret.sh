#!/bin/bash
# Run interactively on the host. No secret is echoed or used in argv.
set -eu
set +x
umask 077
mkdir -p secrets
chmod 700 secrets
IFS= read -rsp 'AES key: ' meter_secret
printf '\n'
if [[ ! $meter_secret =~ ^[[:xdigit:]]{32}$ ]]; then
    unset meter_secret
    printf 'Expected exactly 32 hexadecimal characters\n' >&2
    exit 1
fi
# Refuse symlink redirection or overwriting a supplied key accidentally.
set -o noclobber
printf '%s\n' "$meter_secret" > secrets/meter_aes_key
unset meter_secret
chmod 600 secrets/meter_aes_key
printf 'Saved protected runtime secret to secrets/meter_aes_key\n'
