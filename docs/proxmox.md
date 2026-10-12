# Direct LXC installation on Proxmox VE 9.1+

Run the interactive installer **as root on the Proxmox node with the SDR attached**. It uses Proxmox's OCI image importer to run the published diehl2mqtt image directly as an **unprivileged LXC**. No Docker daemon, nested Docker, compilation, or login to GHCR is needed. The app is PID 1 under `tini`, rather than a service inside a full Debian system container.

Proxmox introduced OCI application containers in [VE 9.1](https://www.proxmox.com/en/about/company-details/press-releases/proxmox-virtual-environment-9-1) and currently classifies application-container support as a [technology preview](https://raw.githubusercontent.com/proxmox/pve-docs/master/pct.adoc). The installer has automated host-logic and OCI-conversion tests; actual boot, USB reception, reboot and reconnect tests must still be completed on a Proxmox node. It targets amd64 and a single Realtek `0bda:2832` or `0bda:2838` RTL-SDR on the node.

## Install

In the node's shell, download the standalone script:

```bash
curl -fLo install-proxmox.py \
  https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/main/scripts/install-proxmox.py
python3 install-proxmox.py --check
python3 install-proxmox.py --release v0.2.0
```

`--check` verifies the host/version and lists Realtek USB ports without changing the host. `--dry-run` prompts for nonsecret options and shows the installation plan without installing anything or asking for keys. The installer is currently distributed from the source repository; v0.2.0 supplies the existing tested application image. Future deployment archives also include the standalone installer under `scripts/`.

The installer prompts for:

- An unused, cluster-wide CT ID, hostname and active root-disk storage.
- Linux bridge (default `vmbr0`), optional VLAN and DHCP or static IPv4 settings.
- The connected SDR's USB port.
- Your **eight-digit Wireless M-Bus meter ID**, preserving leading zeros. There is no default owner ID.
- MQTT mode: authenticated, anonymous, or off; broker address, port, TLS and username as applicable.
- After showing the plan and confirming creation, the **32-character hexadecimal AES key** and, for authenticated MQTT, password, both with hidden input.

The default allocation is 1 core, 512 MiB RAM and a 2 GiB root disk. The script refuses to overwrite an existing VM/CT or managed configuration. Failed installations leave any newly created CT for inspection; they never delete a guest. A failure before completion may require inspecting/removing that incomplete CT explicitly before retrying with the same ID.

The application image comes from the selected release's checksum-verified `image.txt`, pinned by registry digest. The host installs `skopeo` from its configured Debian repositories if needed, converts the public image to an OCI archive, and passes it to `pct create`. The temporary archive contains no keys and is removed after import. No existing guest is modified.

If an older installer failed while canonicalizing `/var/lib/lxc/CTID/rootfs` with `Permission denied`, download the current script again. The original installer passed its private umask to `pct`, creating root-owned directories that the unprivileged extractor could not traverse. The corrected version runs only `pct` children with umask 022; secret files and monitor configuration remain private. Inspect the failed CT in Proxmox and remove it only if it is the incomplete installation. Proxmox may already have removed its configuration/disk; remaining root-owned directories from that attempt can require inspection before reusing the ID. Choosing a different unused CT ID avoids reusing those paths. Do not recursively change permissions on `/var/lib/lxc` or existing guests.

AES/MQTT secrets are written directly into `/etc/diehl2mqtt/secrets/` in the new guest: directory mode 0700, file mode 0600, owned by its mapped root UID/GID. They do not appear in command arguments, host-monitor configuration or image layers. Decoder-generated secret files live in a dedicated `/run/watermeter` tmpfs. CT backups **include the secret files** and must be protected accordingly.

The installer enables Home Assistant discovery through the existing MQTT defaults. Publicly trusted TLS uses the image's system CA store. Custom CA/client certificates and mTLS are not interactive installer options; configure those separately if required. Prefer a broker IP or DNS name reachable from the guest; `.local` mDNS may not resolve there.

## USB access and automatic restart

Proxmox's `dev0` option maps **only the selected USB character device**, with guest-root ownership and mode 0600. The LXC remains unprivileged. The installer does not expose the whole USB bus, make devices world-writable, enable nesting, or disable AppArmor. If the selected dongle is bound to the host's `dvb_usb_rtl28xxu` or `rtl2832_sdr` driver, the monitor unbinds only that dongle's interface; it does not unload or globally blacklist host drivers.

A host systemd timer runs every approximately 20 seconds. It checks the saved USB port/vendor/product/serial identity, refreshes the changing bus/device address, starts a stopped reader, and restarts it after a failed or timed-out health check (with a 60-second startup grace). When the dongle is missing or replaced by a different device, the reader is stopped until the selected dongle returns. Keep it connected to the same physical USB port. Moving it to another port requires updating the monitor's saved port after intentionally stopping monitoring.

**Automatic startup uses the host timer**, so the CT's Proxmox `onboot` flag is deliberately off. A manual `pct stop` alone is temporary: the timer starts the CT again. Disable monitoring first for maintenance or removal. The ownership marker tag prevents the monitor from acting on a different guest that later reuses the CT ID. Preserve that generated tag while the monitor is enabled.

Host files:

```text
/usr/local/libexec/diehl2mqtt-proxmox.py
/etc/diehl2mqtt-lxc/CTID.json
/etc/systemd/system/diehl2mqtt-lxc@.service
/etc/systemd/system/diehl2mqtt-lxc@.timer
```

## Check the deployment

Replace `CTID` below with the number chosen during setup:

```bash
pct status CTID
pct exec CTID --keep-env 0 -- /usr/bin/env PYTHONPATH=/opt/watermeter \
  /opt/venv/bin/python -m watermeter.health
journalctl -u diehl2mqtt-lxc@CTID.service --since '10 minutes ago'
pct console CTID
```

The console shows the reader's startup diagnostics and decoded readings. Detach using **Ctrl-A, Q**. To get a shell use `pct exec CTID -- /bin/bash`; this application container has no login service or in-guest systemd. Inspect the configured network with `pct config CTID` if MQTT is unreachable. A healthy process check alone does not prove decryption or MQTT delivery.

Acceptance on the destination node:

1. Confirm a live reading for your meter, and MQTT/Home Assistant state updates.
2. Reboot the CT and node; confirm the host timer starts the reader and reception returns.
3. Unplug/replug the dongle into the same port; confirm a new USB address is mapped and reception returns.
4. Confirm a broker restart reconnects and discovery/state are replayed.

## Stop, resume, update or remove

For maintenance:

```bash
systemctl disable --now diehl2mqtt-lxc@CTID.timer
systemctl stop diehl2mqtt-lxc@CTID.service
pct shutdown CTID
```

Resume:

```bash
systemctl enable --now diehl2mqtt-lxc@CTID.timer
```

Updates are deliberate. For a new application release, first stop monitoring and shut down the old CT, then run the installer with a **new CT ID** and `--release vMAJOR.MINOR.PATCH`. Re-enter its runtime settings/secrets, verify reception/MQTT, and retain the old stopped CT for rollback. This initial installer does not replace an existing CT's rootfs or use `apt upgrade` to update the image's application binaries. Do not run two readers against the same dongle or MQTT client identity.

To retire the installation, stop it using the maintenance commands, then delete the chosen CT through Proxmox after deciding whether its data/backups are still needed. Remove only its `/etc/diehl2mqtt-lxc/CTID.json` monitor configuration. Shared helper/unit files may serve other instances. USB-attached readers are tied to the node holding that hardware; automatic migration/HA is not configured by this installer.
