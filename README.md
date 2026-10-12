# Diehl HYDRUS water meter gateway

Read one Diehl HYDRUS 2.0 / DME173 through an RTL-SDR, decrypt Wireless M-Bus C1, and emit newline-delimited JSON. Optional MQTT publishes the complete decoded telegram and automatically discovers ten Home Assistant sensors for readings, stored values, dates and diagnostics. The actual image, connected R820T dongle, fixture, Compose restarts and authenticated live MQTT delivery were tested on the owner's Ubuntu host. See [verification](docs/verification.md) for evidence and remaining external checks.

## Install as a Home Assistant add-on (amd64)

Requires **Home Assistant OS on amd64** and a supported RTL-SDR. For a Proxmox HA VM, pass the dongle through under **VM → Hardware → Add → USB Device**. Stop any previous Docker/LXC reader and its automatic monitoring before moving the dongle; see the [migration commands](ha-addon/DOCS.md#installation).

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fandrekuehne%2Fdiehl2mqtt)

1. Click the button above. My Home Assistant opens your local instance with this repository URL prefilled. If prompted, enter your Home Assistant URL, then confirm **Add** in Home Assistant.
2. In the app/add-on store, find **Diehl Hydrus to MQTT** and select **Install**. Refresh the store if it does not appear immediately.
3. Open **Configuration**. Enter your own **eight-digit meter ID** (preserve leading zeros) and **32-hex-character AES key**. All settings, passwords and keys are entered here; no terminal secret setup is needed.
4. For a running Supervisor MQTT service such as Mosquitto, keep `mqtt_auto: true`. For another broker, disable it and enter the hostname, port, username/password and TLS settings. Keep the existing topic prefixes when migrating.
5. Save, then **Start**. Enable **Start on boot** and **Watchdog**. Check **Log** and confirm a fresh **Last received** timestamp on the MQTT device in Home Assistant.

Manual alternative: open **Settings → Apps** (called **Add-ons** in older versions) → **App/Add-on store → ⋮ → Repositories**, paste the URL below and select **Add**, then continue at step 2:

```text
https://github.com/andrekuehne/diehl2mqtt
```

Update through Home Assistant's normal app/add-on update button. The add-on keeps the same MQTT paths, device identity and all ten sensor entity IDs. Keep the same broker, meter ID and topic settings to reuse existing entities. See the [add-on documentation](ha-addon/DOCS.md) for full configuration, CPU tuning and troubleshooting. The add-on is experimental pending actual HA OS USB/reboot validation; arm64 remains deferred.

## Install on Proxmox VE 9.1+ (no Docker)

For **Proxmox VE 9.1+ without nested Docker**, use the interactive [direct LXC installer](docs/proxmox.md). It imports the published image into an unprivileged LXC and sets up the selected SDR, runtime secrets and host monitoring. RAM/disk allocation is configurable, and new installations include an internal `update` command with automatic rollback. Proxmox application-container support is a technology preview; destination-node testing is still required.

Run this as root in the **Proxmox node shell**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/main/ct/diehl2mqtt.sh)"
```

This installs the current **v0.7.1** release. Connect the RTL-SDR to that Proxmox node first. Run the command on the node itself, not on your desktop or inside another guest.

The setup offers Default/Advanced settings, dialog inputs and hidden secret fields. Default allocation is **1 CPU, 512 MiB RAM and 2 GiB disk**, with DHCP on `vmbr0`. **256 MiB RAM is a reasonable smaller allocation** based on a simulated runtime/update-staging check (about 73 MiB running, 105 MiB peak); actual reception on your node still needs verification. Choose Advanced to set RAM to 256 MiB and customize disk/networking, or supply the allocation directly:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/main/ct/diehl2mqtt.sh)" -- --memory 256 --disk 2
```

During setup, supply your **eight-digit Wireless M-Bus meter ID** (keep leading zeros), MQTT broker address/port/username and, in hidden fields, your **32-character hexadecimal AES key** and MQTT password. No real meter ID or secret is preset. Review the CT summary before confirming creation.

After installation, open a shell inside the new LXC from the Proxmox node (replace `CTID` with its number):

```bash
pct exec CTID -- /bin/bash
```

Inside the LXC, application updates use:

```bash
update --check
update
update --status
```

Check the reader's console and a fresh MQTT/Home Assistant reading using the [Proxmox verification instructions](docs/proxmox.md#check-the-deployment). Application updates preserve the CT and secrets; OS refreshes and older installations are covered in that guide.

## Install with Docker Engine + Compose (Linux amd64)

For another Linux **amd64** host, install [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin and connect or pass through the RTL-SDR. arm64 is deferred. The deployment archive contains build-free Compose files, a release-specific image digest, example settings and hidden-input secret setup scripts.

For Ubuntu, follow [Docker's official Engine and Compose installation commands](https://docs.docker.com/engine/install/ubuntu/) first. Confirm Docker is running and your user can access it:

```bash
docker version
docker compose version
```

Download, verify and unpack the current **v0.7.1** release into a new directory (see [GitHub Releases](https://github.com/andrekuehne/diehl2mqtt/releases) for later versions):

```bash
mkdir diehl2mqtt-install
cd diehl2mqtt-install
curl -fLO https://github.com/andrekuehne/diehl2mqtt/releases/download/v0.7.1/diehl2mqtt-v0.7.1-deploy.tar.gz
curl -fLO https://github.com/andrekuehne/diehl2mqtt/releases/download/v0.7.1/SHA256SUMS
sha256sum --ignore-missing --check SHA256SUMS
tar -xzf diehl2mqtt-v0.7.1-deploy.tar.gz
cd diehl2mqtt-v0.7.1
cp .env.example .env
chmod 600 .env
nano .env
```

Edit `.env` with your meter and broker details. For example (replace the ID and broker address with your own):

```dotenv
METER_ID=12345678
METER_NAME=Water
MQTT_HOST=192.0.2.10
MQTT_PORT=1883
MQTT_USERNAME=mqtt
MQTT_TLS=false
```

`METER_ID` is the water meter's **eight-digit Wireless M-Bus ID**. Preserve leading zeros, for example `00123456`. It is separate from the RTL-SDR USB serial/vendor/product IDs. The release requires you to set it explicitly. Source/image defaults use dummy ID `12345678`, never an owner ID. Keep `METER_DRIVER=dme173`, `WMBUS_MODE=c1` and the release's `WATERMETER_IMAGE` digest from the example file. The supported meter is Diehl HYDRUS 2.0 / DME173; changing the ID does not add support for a different driver. Use a broker address reachable from containers; `.local` mDNS may not resolve there.

Supply the meter's AES key and MQTT password interactively:

```bash
./scripts/setup-secret.sh
./scripts/setup-mqtt-secret.sh
```

The first script prompts for **exactly 32 hexadecimal characters** (16 bytes), with input hidden. It saves `secrets/meter_aes_key`; the second saves `secrets/mqtt_password`. Use the key supplied for your meter, without spaces or a `0x` prefix. Do not put either secret in `.env`, command arguments, GitHub or the image. The scripts create a mode-0700 secret directory and mode-0600 files and refuse to overwrite existing files. Compose mounts the AES file read-only at `/run/secrets/meter_aes_key` and sets `METER_AES_KEY_FILE` for the reader.

Start authenticated MQTT with Home Assistant discovery:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml pull
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d --wait
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml ps
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml logs --tail 20 -f
```

No registry login or local build is needed. Stop following logs with Ctrl+C; the container keeps running. Use the same Compose file list with `down` to stop/remove it. For anonymous MQTT omit the auth override and password setup; for JSON-only use just the base file and AES key. If Home Assistant Recorder has an include whitelist, include Total water before adding it to Energy.

The public image is `ghcr.io/andrekuehne/diehl2mqtt`. Releases use version tags such as `v0.7.1`; `latest` follows tested main/weekly builds. Prefer the digest supplied in each release's deployment archive for deliberate upgrades and rollback. AES keys and MQTT passwords are created locally on each deployment host; they are never part of the image, release archive or CI configuration. Docker upgrades use a new release's image digest and `pull`/`up`; the LXC's `update` command is for native LXC installations only.

### Deploy from a source checkout

If using this source checkout's Compose files instead, copy `.env.example` to `.env.local`, set `WATERMETER_IMAGE` to the published digest plus your broker/meter options, and run the secret setup scripts. Then:

```bash
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml pull
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d --no-build --wait
```

The standalone release archive omits the Compose build section entirely. For anonymous MQTT omit the auth override; for JSON-only use the base file. Keep only one receiver running for a given dongle and MQTT client identity. If Recorder has an include whitelist, include Total water so it can appear in Home Assistant Energy.

```
RTL2832U USB → rtl_sdr (868.95 MHz / 1.6 Msps) → rtl_wmbus
            → wmbusmeters (dme173 + runtime AES config)
            → Python supervisor → JSON stdout
                                → optional Paho MQTT → Home Assistant
```

Defaults: ID `12345678` (eight-character string), driver `dme173`, name `Water`, frequency `868.95M`, mode `c1`. No autodetection or retuning replaces these defaults. MQTT defaults off. An AES secret alone is sufficient for JSON-only operation. Only this meter driver and C1 mode are supported; the ID, name and frequency may be overridden with validated environment values.

### Reduce SDR CPU use

The radio processes 1.6 million samples per second continuously, even between telegrams. Most CPU time is in `rtl_wmbus`. Version v0.7.0 exposes two **runtime** settings; no recompilation is needed:

| Setting | Values | Default |
| --- | --- | --- |
| `WMBUS_FAST_MATH` | `true` uses approximate atan; `false` uses accurate math | `false` |
| `WMBUS_ALGORITHM` | `both`, `runlength`, or `time2` | `both` |

Start by enabling fast math while keeping both algorithms. A short live test on a 13th-generation Intel desktop reduced total pipeline CPU from about 19% to 11% of one core. Fast math plus runlength alone used about 9%. In a separate 65-second comparison the tested settings recovered the same two distinct CRC-valid telegrams. This small sample does not establish weak-signal performance; compare fresh readings and reception gaps on your installation. Both algorithms with accurate math remain the defaults. `time2` alone is selectable but was not part of that reception comparison. These algorithms are demodulation methods; meter driver and C1 mode stay fixed.

**Docker:** add to the deployment's `.env` (or your source checkout's `.env.local`):

```dotenv
WMBUS_FAST_MATH=true
WMBUS_ALGORITHM=both
```

Recreate the container with the same Compose file list and `up -d --wait` (source checkout: also use `--env-file .env.local` and `--no-build`). A plain `docker restart` does not reload `.env`. When upgrading an older deployment, use v0.7.0 or newer Compose files as well as its image; older files do not pass these settings through.

**LXC:** the installer offers these options under Advanced, or accepts `--fast-math true --algorithm both`. For an existing LXC, first update the app to v0.7.0 or newer, then set these environment values in its Proxmox configuration and restart it. See [LXC tuning commands](docs/proxmox.md#demodulator-tuning).

**Home Assistant add-on:** update to 0.7.0 or newer, then set **Fast demodulator math** and **Demodulator algorithms** in Configuration, save and restart. The YAML keys are `fast_math` and `algorithm`. Existing options without these keys keep the original defaults.

The startup log shows the selected algorithm and math setting. MQTT topics, sensor identities and decoded JSON remain the same.

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

`secrets/` and `.env.local` are local, ignored inputs; they are excluded from Docker context and Git. No production key is included in examples, fixtures, images, builds or commits. The encrypted fixture uses dummy ID `12345678` and public test key `00112233445566778899aabbccddeeff`; never use that test key for a real meter.

## Build from source on Ubuntu (optional)

Install Docker Engine and the Compose plugin from [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Docker must be running and your account must have daemon access. Docker-group membership is root-equivalent; use your usual approved Docker access arrangement. Re-login after changing group membership. USB commands below require Linux Docker Engine, not an assumed USB forwarding layer in Docker Desktop.

```bash
git clone https://github.com/andrekuehne/diehl2mqtt.git
cd diehl2mqtt
docker build --pull -t watermeter:local .
./scripts/setup-secret.sh
./scripts/test-offline.sh
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

The bundled telegram is entirely synthetic: dummy meter ID `12345678`, a public test key, a total of 0.252 m³ and temperature 16.8 °C. No captured owner telegram is distributed. Run `./scripts/test-offline.sh` to decode it without USB, a broker or production secrets. Offline mode pins the synthetic ID/driver, has a ten-second timeout and requires a finite total with matching identity. To test your real key, configure your own `METER_ID` and use live reception; the synthetic fixture cannot validate a production key.

Additional negative checks:

```bash
docker run --rm --network none --tmpfs /run/watermeter:mode=0700 \
  --mount "type=bind,src=$PWD/scripts/test-offline-negative.py,dst=/test-negative.py,readonly" \
  --entrypoint python watermeter:local /test-negative.py
```

These checks decode the synthetic fixture and reject a random wrong key, wrong ID, unsupported driver and corrupted ciphertext. Production readings preserve upstream fields and precision without offsets, rounding or consumption calculations.

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
homeassistant/sensor/diehl_hydrus_12345678_target_m3/config
homeassistant/sensor/diehl_hydrus_12345678_target_datetime/config
homeassistant/sensor/diehl_hydrus_12345678_total_at_set_date_m3/config
homeassistant/sensor/diehl_hydrus_12345678_set_date/config
homeassistant/sensor/diehl_hydrus_12345678_total_backward_m3/config
homeassistant/sensor/diehl_hydrus_12345678_timestamp/config
homeassistant/sensor/diehl_hydrus_12345678_received_at/config
```

And **subscribe** to `homeassistant/status`. Adjust exact paths for configured prefixes/ID/status topic. A separate observation client additionally needs read access to these twelve device topics. No broad wildcard publish permission is needed. Broker ACLs written for v0.2.0's three discovery topics need the seven additional exact discovery topics above.

The shared device is Diehl Metering / HYDRUS 2.0 / DME173 with identifier `diehl_hydrus_12345678`. Discovery creates:

The discovered device is named `Diehl Hydrus 2.0 ID 12345678` using your configured meter ID. Sensor names are simply `Total water`, `Flow temperature`, etc. Entity IDs keep the meter ID, for example `sensor.diehl_hydrus_12345678_total_m3`. `METER_NAME` controls the decoder label in telegram JSON, independently of Home Assistant naming. Existing Home Assistant name overrides take precedence; reset an override to use the published name.

| Sensor | Unique ID suffix | Unit | Device class | State class |
| --- | --- | --- | --- | --- |
| Total water | `_total_m3` | m³ | water | total_increasing |
| Flow temperature | `_flow_temperature_c` | °C | temperature | measurement |
| Status (diagnostic) | `_status` | — | — | — |
| Billing period water | `_target_m3` | m³ | water | — |
| Billing period date | `_target_datetime` | — | — | — |
| Water at set date | `_total_at_set_date_m3` | m³ | water | — |
| Set date | `_set_date` | — | date | — |
| Backward water | `_total_backward_m3` | m³ | water | — |
| Decoder timestamp (diagnostic) | `_timestamp` | — | timestamp | — |
| Last received (diagnostic) | `_received_at` | — | timestamp | — |

Sensor display names omit the meter ID; the shared device name contains it. Newly discovered entities place the meter ID immediately after `diehl_hydrus`, for example `sensor.diehl_hydrus_12345678_total_m3`; leading zeros are preserved. Existing unique IDs and discovery topics are unchanged, so upgrades update the same entities. Home Assistant preserves an existing entity ID or user-customized name: rename an older entity in its entity settings without deleting it if you want the new ID format. The [MQTT sensor reference](https://www.home-assistant.io/integrations/sensor.mqtt/#default_entity_id) explains that the default entity ID is applied on first registration only.

The retained state JSON contains **every field emitted by the pinned decoder**, including meter metadata, original timestamps and additional future fields, plus gateway `driver` and `received_at`. Status also exposes this complete JSON as Home Assistant attributes. No raw RF/hex dump or invented fields are added. Decoder fields that are absent from a telegram remain absent in JSON and unknown in their sensors. Some meter telegram variants do not carry every optional value.

Absolute totals are published, so repeats never fabricate consumption increments. Invalid/nonfinite numbers are rejected; absent/null optional values are unknown, not zero. No `expire_after` is inferred from a short test. Historical volumes and backward volume have no statistical state class; Total water remains the cumulative water-usage sensor. The decoder's meter-local `target_datetime` is displayed unchanged as text because it has no timezone. No timezone or billing-period interpretation is invented for stored set-date values.

Availability means the receiver is alive and connected to MQTT. It does not establish recent RF reception. Graceful shutdown/failure publishes offline with a bounded acknowledgement wait; abrupt loss relies on the retained last will and broker keepalive detection. Offline detection is not instantaneous during network/broker failure. Retained states deliberately remain historical until replaced. `received_at` is gateway receipt time in UTC, stamped once and unchanged on replay; original upstream timestamps remain separate. Runtime health includes last receipt and MQTT connection status at `/run/watermeter/health.json`; health success depends on live process identities/heartbeat, not reception age or broker connectivity.

In Home Assistant, open Settings → Devices & services → MQTT, locate the Water/Diehl device and check the ten sensors. Enable diagnostic sensors if hidden/disabled. Verify Total water's `water` device class, `m³` unit and `total_increasing` state class, then select it under Energy → Water consumption. See [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/), [MQTT sensor behavior](https://www.home-assistant.io/integrations/sensor.mqtt/) and [water usage](https://www.home-assistant.io/docs/energy/water/). Restart the gateway/HA and confirm stable entity identity and availability. Schema and subscriber checks do not by themselves prove the HA UI/statistics flow.

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

To retire a device, stop its publisher first, then publish a **zero-length retained QoS 1 payload** to each of the exact ten discovery topics listed above. Also clear the exact state/availability topics if retiring the device entirely. Use your broker UI or an authenticated client configured with a protected password file; never put a password in command arguments. For an anonymous broker, for example (replace the dummy ID):

```bash
for field in total_m3 flow_temperature_c status target_m3 target_datetime \
  total_at_set_date_m3 set_date total_backward_m3 timestamp received_at; do
  mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n \
    -t "homeassistant/sensor/diehl_hydrus_12345678_${field}/config"
done
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n -t watermeter/12345678/state
mosquitto_pub -h "$MQTT_HOST" -p "${MQTT_PORT:-1883}" -q 1 -r -n -t watermeter/12345678/availability
```

Never clear a wildcard namespace. Clean up the old exact topics after changing ID or prefixes. Normal shutdown preserves discovery so entities survive restarts.

## Host USB troubleshooting and Proxmox

These manual troubleshooting steps apply to the Docker deployment. The explicitly invoked [Proxmox installer](docs/proxmox.md) creates/configures a new LXC and may detach the selected SDR's DVB driver; it does not blacklist modules globally.

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

For Docker nested inside LXC, host-to-LXC USB mounts, cgroup allowances and unprivileged UID/GID mapping constraints precede Docker's own controls. A Linux VM is the simpler isolation boundary for that deployment. On Proxmox VE 9.1+, the [direct OCI/LXC installer](docs/proxmox.md) instead maps a single SDR device and uses a host timer to refresh its address and restart the reader. Actual Proxmox boot, reception and unplug/replug behavior still require destination-node validation.

## Tests, CI and reviewed updates

```bash
./scripts/test-mqtt.sh
```

This builds the test target, adds a disposable Mosquitto only to that image, runs with `--network none` on loopback, and cleans up. It tests secrets, identity/decryption boundaries, silence/failure/EOF/signals/descendants, JSON flushing during broker outage, retained/QoS/birth/LWT/reconnect/auth/TLS behavior and stable discovery. It does not need the dongle, real AES key or production broker. The positive synthetic fixture is also verified with its public test key; real-key/live reception remains a separate destination-host check. See [verification](docs/verification.md).

The GitHub workflow handles PR/push/manual builds on amd64, caches normal builds, and performs a Monday 04:17 UTC rebuild with `pull: true` and build cache disabled. The base digest stays pinned until reviewed updates are merged. Dependabot proposes Docker digest/Action changes. Paho and decoder revisions are changed explicitly; no branch head is adopted automatically. CI decrypts only the synthetic fixture with its public test key. No production AES key or MQTT password is uploaded to GitHub or needed by any CI event. No `pull_request_target` runs PR code. PR tests have read-only permissions and cannot publish.

Successful main pushes and scheduled builds automatically publish `latest` to GHCR. A manual main run publishes only when its `publish` input is enabled. The separate publish job loads the exact production image saved by the successful test job, then tags and pushes it without rebuilding. Each publication also gets a unique full-commit/run/attempt tag. Images include source-repository/revision labels. Only the publication job can write packages/releases; test jobs remain read-only.

To create a versioned release after merging and verifying main, choose a new `vMAJOR.MINOR.PATCH` tag, then push it:

```bash
git tag v0.7.1
git push origin v0.7.1
```

When changing the installer release, update `DEFAULT_RELEASE` in `scripts/install-proxmox.py` and the release/SHA256 pins in `ct/diehl2mqtt.sh` together. Host tests enforce matching pins.

Use a new version for subsequent releases. CI rejects malformed version tags and commits outside main's history. After passing the same tests, it publishes the version tag and creates a GitHub release with a build-free deployment archive pinned to the actual registry digest, pinned unmodified native source archives plus project build materials/runtime package versions, an image reference, a native LXC application update bundle and `SHA256SUMS`. A version release does not move `latest`; that follows main. The package must be public in GitHub's package settings for anonymous pulls (package visibility is separate from repository visibility). Hosted results are recorded in [verification](docs/verification.md). arm64 is not claimed supported/tested.

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
./scripts/test-offline.sh
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
