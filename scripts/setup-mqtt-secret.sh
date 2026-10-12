#!/bin/bash
set -eu
set +x
umask 077
mkdir -p secrets
chmod 700 secrets
IFS= read -rsp 'MQTT password: ' mqtt_secret
printf '\n'
if [[ -z $mqtt_secret ]]; then
    printf 'Password cannot be empty\n' >&2
    exit 1
fi
set -o noclobber
printf '%s\n' "$mqtt_secret" > secrets/mqtt_password
unset mqtt_secret
chmod 600 secrets/mqtt_password
printf 'Saved protected runtime secret to secrets/mqtt_password\n'
