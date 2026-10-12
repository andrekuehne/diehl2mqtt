#!/usr/bin/env bash
# One-line Proxmox launcher. The standalone installer owns all host changes.
set -Eeuo pipefail
umask 077
INSTALLER_RELEASE=v0.8.1
INSTALLER_SHA256=dec2de925268f4028d67d4eb886c3122b888272d0654fcc1900193e6e72be506

for binary in curl python3 sha256sum mktemp pct pveversion; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        printf 'Missing %s. Run this command in the Proxmox node shell.\n' "$binary" >&2
        exit 1
    fi
done
installer_dir=$(mktemp -d "${TMPDIR:-/tmp}/diehl2mqtt-install.XXXXXX")
trap 'rm -rf -- "$installer_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '  i  Downloading diehl2mqtt installer %s\n' "$INSTALLER_RELEASE"
curl -fsSL --proto '=https' --tlsv1.2 --connect-timeout 20 --max-time 120 --retry 2 \
    "https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/$INSTALLER_RELEASE/scripts/install-proxmox.py" \
    -o "$installer_dir/install-proxmox.py"
if ! printf '%s  %s\n' "$INSTALLER_SHA256" "$installer_dir/install-proxmox.py" | sha256sum -c --status; then
    printf 'Installer checksum mismatch; nothing was executed.\n' >&2
    exit 1
fi
# Keep stdin attached to the terminal for dialogs and hidden secret entry.
# --plain supplied by the caller replaces the default dialog UI.
interface=--ui
for argument in "$@"; do
    if [[ "$argument" == --plain ]]; then interface=--plain; fi
done
python3 "$installer_dir/install-proxmox.py" "$interface" "$@"
