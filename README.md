# Diehl HYDRUS water meter gateway

Read one Diehl HYDRUS 2.0 / DME173 through an RTL-SDR, decrypt Wireless M-Bus C1, and emit newline-delimited JSON. Optional MQTT publishes retained readings and automatically discovers three Home Assistant sensors. The actual image, connected R820T dongle, fixture, Compose restarts and authenticated live MQTT delivery were tested on the owner's Ubuntu host. See [verification](docs/verification.md) for evidence and remaining external checks.

```
RTL2832U USB → rtl_sdr (868.95 MHz / 1.6 Msps) → rtl_wmbus
            → wmbusmeters (dme173 + runtime AES config)
            → Python supervisor → JSON stdout
                                → optional Paho MQTT → Home Assistant
```

Defaults: ID `12345678` (eight-character string), driver `dme173`, name `Water`, frequency `868.95M`, mode `c1`. No autodetection or retuning replaces these defaults. MQTT defaults off. An AES secret alone is sufficient for JSON-only operation. Only this meter driver and C1 mode are supported; the ID, name and frequency may be overridden with validated environment values.

## Files

```
IMPLEMENTATION_PLAN.md                original requirements baseline
Dockerfile                           pinned Debian multi-stage build; final/test targets
compose.yaml                         JSON-only secret/USB deployment
compose.mqtt.yaml                     optional broker/discovery settings
compose.mqtt.auth.yaml                optional password-file secret
.env.example                         nonsecret settings only
requirements.txt                     pinned, hashed Paho dependency
scripts/
  entrypoint.sh  healthcheck.sh  smoke-image.sh
  setup-secret.sh  setup-mqtt-secret.sh
  test-offline.sh  test-offline-negative.py  test-sdr.sh  test-mqtt.sh
  check-updates.sh  security-audit.py
src/watermeter/                       settings, private config, offline decoder,
                                     supervisor, health, JSON boundary, MQTT,
                                     discovery and live MQTT observer
tests/                               encrypted/synthetic fixtures and meaningful
                                     settings, lifecycle and real-broker tests
docs/implementation-notes.md          upstream interfaces, pins and decisions
docs/verification.md                  PASS/FAIL/NOT RUN evidence
.github/workflows/build.yml           trusted builds/tests and optional publication
.github/dependabot.yml                reviewed Docker/Action update proposals
```

`secrets/` and `.env.local` are local, ignored inputs; they are excluded from Docker context and Git. No key is included in examples, fixtures, images, builds or commits.

## Ubuntu quick start

Install Docker Engine and the Compose plugin from [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Docker must be running and your account must have daemon access. Docker-group membership is root-equivalent; use your usual approved Docker access arrangement. Re-login after changing group membership. USB commands below require Linux Docker Engine, not an assumed USB forwarding layer in Docker Desktop.

```bash
cd /home/andre/Projects/Watermeter-Docker
docker build --pull -t watermeter:local .
./scripts/setup-secret.sh
METER_AES_KEY_FILE="$PWD/secrets/meter_aes_key" ./scripts/test-offline.sh
./scripts/test-sdr.sh
```

`setup-secret.sh` prompts invisibly, validates the input, and creates `secrets/` mode 0700 and `secrets/meter_aes_key` mode 0600. It refuses to overwrite an existing file. Keep it outside Git, backups that are not intended for credentials, and chat. Compose secrets are local bind-mounted files, not a vault; host permissions remain essential.

Stop this project's reader before the exclusive SDR check:

```bash
docker compose stop watermeter
./scripts/test-sdr.sh
```

`rtl_test -t` identifies the R820T/R820T2; its E4000-only test may end with `No E4000 tuner found, aborting` on this hardware. Actual decoding is the functional reception test. A visibility result never proves AES decryption.

Run live in the foreground, with no broker/network requirement:

```bash
docker run --rm --name watermeter-foreground --network none \
  --tmpfs /run/watermeter:mode=0700 \
  --mount "type=bind,src=$PWD/secrets/meter_aes_key,dst=/run/secrets/meter_aes_key,readonly" \
  --mount type=bind,src=/dev/bus/usb,dst=/dev/bus/usb \
  --device-cgroup-rule 'c 189:* rmw' \
  -e METER_AES_KEY_FILE=/run/secrets/meter_aes_key \
  watermeter:local
```

Ctrl-C shuts down all three processes. Stdout contains only accepted decoded JSON, one object per line; diagnostics and revisions use stderr. To save parseable readings, append `> readings.jsonl` to the command. Do not run a second reader or `rtl_test` while this process owns the dongle.

Start the normal JSON-only deployment:

```bash
docker compose up -d --build
docker compose logs -f watermeter
docker compose exec -T watermeter healthcheck.sh
docker compose stop watermeter
docker compose start watermeter
```

Logs include startup diagnostics as well as measurements; Compose adds prefixes. Direct container stdout is the NDJSON interface. The service rotates three 10 MB log files, restarts unless stopped, and has a 20-second shutdown grace period. There is no `privileged: true` or fixed changing USB bus/device address. The image's tini reaps children; the supervisor monitors every pipeline member and fails even if a member unexpectedly exits zero.

The container runs as root for verified access to host USB nodes and the protected secret. It is nonprivileged and has only the configured USB device cgroup access. Nonroot/rootless/LXC operation needs separately verified node permissions, supplemental groups, readable secret mounts and a tmpfs writable by that UID; it is not claimed tested. The major-189 cgroup rule and whole USB bus mount grant access to USB devices beyond this particular SDR. They do not override Unix node permissions. No unverified capability dropping or world-writable device workaround is applied.

## Runtime secrets and offline checks

`METER_AES_KEY_FILE` takes precedence whenever nonempty. Missing, unreadable, empty or malformed explicitly configured files fail; they do not fall back to the environment. File input permits one final LF or CRLF, then requires exactly 32 hexadecimal characters. Arbitrary whitespace, extra lines and environment newlines are rejected. Runtime-generated decoder files have mode 0600 inside a private 0700 directory on `/run/watermeter` tmpfs, and are removed on exit. The application refuses secret use without this tmpfs. Key/password environment settings are removed before child processes start. No key is used in process arguments. Upstream diagnostic text is suppressed because a configuration error could otherwise echo a secret; safe categories still identify missing devices, USB access and decryption trouble.

For a temporary environment test, use hidden input and pass the variable by name:

```bash
read -rsp 'AES key: ' METER_AES_KEY; echo
export METER_AES_KEY
./scripts/test-offline.sh
unset METER_AES_KEY
```

Environment-based Docker secrets can be visible in container metadata. Files are recommended. Set `METER_AES_KEY_FILE` to an absolute host path to use the offline script's protected bind-mount mode; remove that setting if intentionally testing the environment mode.

The fixture is the exact encrypted telegram in the plan. The offline command disables networking and needs neither USB nor MQTT. It pins the original fixture ID/driver independently of live overrides, has a ten-second decoder timeout, and requires real finite `total_m3` with matching identity. Header-only packets are rejected. Optional fields are preserved; no current reading is expected to equal the historical fixture value.

Correct-key negative checks, after setup:

```bash
docker run --rm --network none --tmpfs /run/watermeter:mode=0700 \
  --mount "type=bind,src=$PWD/secrets/meter_aes_key,dst=/run/secrets/meter_aes_key,readonly" \
  --mount "type=bind,src=$PWD/scripts/test-offline-negative.py,dst=/test-negative.py,readonly" \
  -e METER_AES_KEY_FILE=/run/secrets/meter_aes_key \
  --entrypoint python watermeter:local /test-negative.py
```

This first proves the fixture decrypts, then rejects an ephemeral wrong key, wrong ID, unsupported driver and corrupted ciphertext. It prints no secret. The upstream `meter=dme173` identity is retained and normalized with `driver=dme173`. Original numeric fields are retained without offsets, rounding or consumption calculations. Some upstream legacy period/date fields in this meter's fixture look unusual; they are preserved without creating discovery entities or assigning billing meaning.

## MQTT and Home Assistant

Configure Home Assistant's MQTT integration and this gateway against the same reachable broker. `localhost` inside Docker means the container itself. `.local` mDNS may resolve on Ubuntu but fail in Docker's DNS; use a stable LAN IP or a DNS name available to containers. On this host the owner's resolved broker address is in ignored `.env.local`; it is not part of the portable deployment.

Anonymous broker activation:

```bash
export MQTT_HOST=broker.example.internal
docker compose -f compose.yaml -f compose.mqtt.yaml up -d
```

For authenticated deployment, create the password with hidden input and use the extra secret override:

```bash
./scripts/setup-mqtt-secret.sh
export MQTT_USERNAME=mqtt
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d
```

The owner's tested local configuration can be started without entering credentials again:

```bash
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml logs -f watermeter
```

No password file is required by the JSON-only or anonymous MQTT configurations. `MQTT_PASSWORD_FILE` takes precedence over `MQTT_PASSWORD` and fails safely when explicitly invalid. A password requires a username. Plaintext MQTT is supported as requested; use TLS on networks where transport privacy is required.

| Setting | Default / rule |
| --- | --- |
| `MQTT_ENABLED` | `false` |
| `MQTT_HOST` | Required if enabled; hostname/IP, without URL scheme or port |
| `MQTT_PORT` | Application: 1883, or 8883 with TLS; Compose override: 1883 unless explicitly changed |
| `MQTT_USERNAME` | Empty means anonymous |
| `MQTT_PASSWORD`, `MQTT_PASSWORD_FILE` | Optional runtime password; file wins |
| `MQTT_TLS` | `false`; CA and hostname verification always required when enabled |
| `MQTT_CA_FILE` | Optional mounted CA; otherwise system trust |
| `MQTT_CLIENT_CERT_FILE`, `MQTT_CLIENT_KEY_FILE` | Optional mounted mutual-TLS pair; both required together |
| `MQTT_TOPIC_PREFIX` | `watermeter`; only trailing `/` removed; empty/wildcard/control values rejected |
| `MQTT_CLIENT_ID` | `watermeter_12345678`, derived from configured meter ID |
| `HA_DISCOVERY_ENABLED` | True when MQTT enabled; independent disable supported |
| `HA_DISCOVERY_PREFIX` | `homeassistant` |
| `HA_STATUS_TOPIC` | `homeassistant/status`, independent of discovery prefix |

Booleans accept case-insensitive true/false, yes/no, on/off and 1/0. MQTT 3.1.1, QoS 1, retained publication, 60-second keepalive and 1–60-second retry backoff are implementation constants. Set a distinct `MQTT_CLIENT_ID` for each simultaneous publisher; two clients with the same ID evict one another. Friendly-name changes do not change IDs or topics.

TLS example: save this **local** override as `compose.tls.local.yaml`, put CA/client files under ignored `secrets/tls/`, and add it to the Compose command. The CA can be omitted when using public system trust; the client certificate/key pair can be omitted when the broker does not require mutual TLS.

```yaml
services:
  watermeter:
    environment:
      MQTT_TLS: "true"
      MQTT_PORT: "8883"
      MQTT_CA_FILE: /run/tls/ca.crt
      MQTT_CLIENT_CERT_FILE: /run/tls/client.crt
      MQTT_CLIENT_KEY_FILE: /run/tls/client.key
    volumes:
      - ./secrets/tls:/run/tls:ro
```

There is no insecure-certificate bypass. Client private keys must be unencrypted protected files; interactive key-password prompts are disabled. TLS trust loading errors fail safely; transient connection/auth/TLS handshake failures retry without stopping the decoder or stdout. Decoder state is not an event archive: one latest accepted state is cached; obsolete disconnected states are discarded and Paho's outgoing/inflight counts are bounded. On connection: subscribe to HA birth, publish discovery, replay cached state if available, then announce online while the receiver is alive. Reconnect and an `online` HA birth replay discovery and cached state. Normal readings do not republish unchanged discovery. Every publication checks QoS acknowledgements in the MQTT worker; stdout never waits for the broker.

Default broker ACLs must permit this client to **publish**:

```
watermeter/12345678/state
watermeter/12345678/availability
homeassistant/sensor/diehl_hydrus_12345678_total_m3/config
homeassistant/sensor/diehl_hydrus_12345678_flow_temperature_c/config
homeassistant/sensor/diehl_hydrus_12345678_status/config
```

And **subscribe** to `homeassistant/status`. Adjust exact paths for configured prefixes/ID/status topic. A separate observation client additionally needs read access to these five device topics. No broad wildcard publish permission is needed.

The shared device is Diehl Metering / HYDRUS 2.0 / DME173 with identifier `diehl_hydrus_12345678`. Discovery creates:

| Sensor | Unique ID suffix | Unit | Device class | State class |
| --- | --- | --- | --- | --- |
| Total water | `_total_m3` | m³ | water | total_increasing |
| Flow temperature | `_flow_temperature_c` | °C | temperature | measurement |
| Status (diagnostic) | `_status` | — | — | — |

Absolute totals are published, so repeats never fabricate consumption increments. Invalid/nonfinite numbers are rejected; absent/null optional values are unknown, not zero. No `expire_after` is inferred from a short test. `target_m3`, `target_datetime` and other fields remain in state JSON without initial discovery entities.

Availability means the receiver is alive and connected to MQTT. It does not establish recent RF reception. Graceful shutdown/failure publishes offline with a bounded acknowledgement wait; abrupt loss relies on the retained last will and broker keepalive detection. Offline detection is not instantaneous during network/broker failure. Retained states deliberately remain historical until replaced. `received_at` is gateway receipt time in UTC, stamped once and unchanged on replay; original upstream timestamps remain separate. Runtime health includes last receipt and MQTT connection status at `/run/watermeter/health.json`; health success depends on live process identities/heartbeat, not reception age or broker connectivity.

In Home Assistant, open Settings → Devices & services → MQTT, locate the Water/Diehl device and check all three sensors. Enable diagnostic Status if hidden/disabled. Verify Total water's `water` device class, `m³` unit and `total_increasing` state class, then select it under Energy → Water consumption. See [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/), [MQTT sensor behavior](https://www.home-assistant.io/integrations/sensor.mqtt/) and [water usage](https://www.home-assistant.io/docs/energy/water/). Restart the gateway/HA and confirm stable entity identity and availability. Schema and subscriber checks do not by themselves prove the HA UI/statistics flow.

If Total water appears under MQTT but is missing from Energy's water selector, inspect its actual entity in Developer Tools → States (Settings → Tools → States in newer versions). It must have a numeric state, `device_class: water`, `state_class: total_increasing` and `unit_of_measurement: m³` with the superscript `³`. Then check Developer Tools → Statistics for that entity and any reported issue. Statistics update every five minutes; after initial discovery, allow a statistics cycle and reopen the Energy configuration. If it is still missing, check that Recorder is enabled and that its include/exclude filters allow this entity. Record the entity ID, state, attributes, Statistics result and Home Assistant version before changing discovery or creating another sensor. See the official [missing-entity checklist](https://www.home-assistant.io/docs/energy/faq/#troubleshooting-missing-entities), [statistics behavior](https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes) and [Recorder filters](https://www.home-assistant.io/integrations/recorder/#configure-filter).

A separate subscriber can require a newly received live reading, all configs and online availability, bounded to 15 minutes:

```bash
docker run --rm \
  --mount "type=bind,src=$PWD/secrets/mqtt_password,dst=/run/secrets/mqtt_password,readonly" \
  -e MQTT_ENABLED=true -e MQTT_HOST -e MQTT_PORT -e MQTT_USERNAME \
  -e MQTT_PASSWORD_FILE=/run/secrets/mqtt_password \
  --entrypoint python watermeter:local -m watermeter.observe
```

Export the nonsecret broker variables first. For TLS, mount/pass the same TLS files/options as the reader. The observer uses a distinct client ID and publishes nothing. Old retained messages cannot satisfy its receipt-time requirement.

To retire a device, stop its publisher first, then publish a **zero-length retained QoS 1 payload** to each of the exact three discovery topics listed above. Also clear the exact state/availability topics if retiring the device entirely. Use your broker UI or an authenticated client configured with a protected password file; never put a password in command arguments. For an anonymous broker, for example:

```bash
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n \
  -t homeassistant/sensor/diehl_hydrus_12345678_total_m3/config
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n \
  -t homeassistant/sensor/diehl_hydrus_12345678_flow_temperature_c/config
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n \
  -t homeassistant/sensor/diehl_hydrus_12345678_status/config
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n -t watermeter/12345678/state
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n -t watermeter/12345678/availability
```

Never clear a wildcard namespace. Clean up the old exact topics after changing ID or prefixes. Normal shutdown preserves discovery so entities survive restarts.

## Host USB troubleshooting and Proxmox

These are instructions for the owner; the project never changes modules, permissions or Proxmox configuration automatically.

```bash
lsusb
rtl_test -t
lsmod | grep -E 'dvb_usb_rtl28xxu|rtl2832|rtl2830'
ls -l /dev/bus/usb/*/*
```

If another application owns the SDR, stop that application intentionally. Do not kill unrelated SDR users automatically. Existing distro RTL-SDR udev rules and membership of their assigned USB group may already suffice. A mode-0660 owner-controlled udev rule can target vendor `0bda`, product `2838` and group `plugdev`; verify your actual device and group before installing it. Reload udev and reconnect the receiver. Do not use chmod 777. The tested distro libusb driver can temporarily detach and reattach its kernel driver without changing loaded modules.

If a DVB module prevents access, an optional temporary unload is:

```bash
sudo modprobe -r dvb_usb_rtl28xxu rtl2832 rtl2830
```

This affects other devices using those modules and may fail while DVB applications use them. To make an intentional dedicated-SDR setup persistent:

```bash
printf '%s\n' 'blacklist dvb_usb_rtl28xxu' 'blacklist rtl2832' 'blacklist rtl2830' \
  | sudo tee /etc/modprobe.d/watermeter-rtl-sdr.conf
sudo update-initramfs -u
```

Reboot as appropriate. To undo, remove only that dedicated file, rebuild initramfs and reload the DVB driver/reboot:

```bash
sudo rm /etc/modprobe.d/watermeter-rtl-sdr.conf
sudo update-initramfs -u
sudo modprobe dvb_usb_rtl28xxu
```

On Proxmox, run Docker **inside a Linux guest**, not implicitly on the VE host. For a VM, add the SDR in VM Hardware → USB Device, selecting the device/physical port appropriate to your setup, then confirm `lsusb` and permissions inside the guest before Docker. Avoid unstable changing bus/device-number assignments. The guest's kernel/udev/USB nodes and Docker cgroups each have to permit access.

LXC adds host-to-LXC bind mounts, USB major-189 cgroup allowances and unprivileged UID/GID mapping constraints before Docker's own controls. Hotplug nodes must remain visible and accessible at every layer. A Linux VM is the simpler isolation boundary for nested Docker/USB. VM/LXC/rootless passthrough and physical unplug/replug stress have not been verified here. The supervised reader exits on component failure; Docker restart then retries device opening. Reconnect changes bus/device numbers, so mount the bus and verify node access again.

## Tests, CI and reviewed updates

```bash
./scripts/test-mqtt.sh
```

This builds the test target, adds a disposable Mosquitto only to that image, runs with `--network none` on loopback, and cleans up. It tests secrets, identity/decryption boundaries, silence/failure/EOF/signals/descendants, JSON flushing during broker outage, retained/QoS/birth/LWT/reconnect/auth/TLS behavior and stable discovery. It does not need the dongle, real AES key or production broker. Correct-key fixture and live acceptance remain separate mandatory owner-input checks. See [verification](docs/verification.md).

The GitHub workflow handles PR/push/manual builds on amd64, caches normal builds, and performs a Monday 04:17 UTC rebuild with `pull: true` and build cache disabled. The base digest stays pinned until reviewed updates are merged. Dependabot proposes Docker digest/Action changes. Paho and decoder revisions are changed explicitly; no branch head is adopted automatically. Optional GitHub Actions `METER_AES_KEY` is used only by trusted main/non-PR runtime decoding, never builds or untrusted PR execution. Absent secret is a clear skip. No `pull_request_target` runs PR code. Explicit main-branch manual publication may push GHCR after tests with limited package permissions. Without a GitHub remote these definitions are locally validated, not claimed executed/published. arm64 is not claimed supported/tested.

Inspect installed versions and read-only update candidates:

```bash
docker run --rm --network none watermeter:local versions
./scripts/check-updates.sh
```

Review upstream release notes and the exact full commits, driver/CLI/config changes, licenses, and Paho callback/TLS behavior. Change the checked-in `RTL_WMBUS_REF`, `WMBUSMETERS_REF` and base digest in `Dockerfile`. To intentionally test alternate refs before accepting them:

```bash
docker build --pull -t watermeter:candidate \
  --build-arg RTL_WMBUS_REF="$RTL_WMBUS_REF" \
  --build-arg WMBUSMETERS_REF="$WMBUSMETERS_REF" .
```

Set both variables to reviewed immutable commits first. Resolve any tag to a full commit with `git ls-remote` and verify provenance. `versions.txt` records actual resolved hashes. To update Paho, fetch its release wheel and SHA256 from PyPI, update the exact version/hash in `requirements.txt` and the matching provenance version in Dockerfile, then rerun real TLS tests; the small Paho 2.1.0 TLS adapter uses a pinned private API and must be reviewed when upgrading. Dependency hashes are public integrity metadata, never hashes of runtime credentials.

After a reviewed change:

```bash
docker build --pull --no-cache -t watermeter:local .
./scripts/test-mqtt.sh
METER_AES_KEY_FILE="$PWD/secrets/meter_aes_key" ./scripts/test-offline.sh
docker compose up -d --force-recreate
```

Use the full MQTT Compose file list when updating that mode. Recheck a new live state, stop/restart and HA behavior before accepting a new revision. Weekly CI rebuilds do not deploy anything automatically.

Upstream notices and source commits are in `/usr/share/watermeter/`, including licenses and runtime distro package versions. Sources are unmodified pinned [wmbusmeters (GPL-3.0-or-later)](https://github.com/wmbusmeters/wmbusmeters) and [rtl-wmbus (BSD-2-Clause)](https://github.com/xaelsouth/rtl-wmbus); Paho includes its license notices. If redistributing binaries, provide corresponding source/build materials in accordance with their licenses, not just an unreviewed binary upload.

## Stop and cleanup

Use the same file list/settings as startup for an MQTT deployment:

```bash
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml stop watermeter
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml down
```

For JSON-only use `docker compose stop` / `docker compose down`. Stop preserves retained discovery/state; down removes this project's containers/network. Neither removes local runtime secrets or unrelated containers/broker data. Remove the explicitly identified local secret files only when retiring the installation; do not use broad Docker/system pruning. The temporary Docker socket ACL used during this session can be removed with `sudo setfacl -x u:andre /var/run/docker.sock` once a fresh login has Docker group membership.

An optional audit compares the explicitly supplied local secrets in memory against tracked files/Git history, selected logs, image metadata and saved image layers without printing or hashing them:

```bash
python3 scripts/security-audit.py \
  --meter-key-file "$PWD/secrets/meter_aes_key" \
  --mqtt-password-file "$PWD/secrets/mqtt_password" \
  --image watermeter:local
```

Add `--container <this-project-container-name>` to check live reader arguments and child environment removal, and repeat `--log /absolute/path/to/selected.log` for files you intentionally want checked. This command never searches unrelated credential files.

If the MQTT password text already occurs in the original requirements baseline, the audit reports its substring scan as non-diagnostic instead of confusing pre-existing words with credential insertion. AES scanning, explicit file/argv/environment rules and authenticated production tests still apply; no secret value is printed.
