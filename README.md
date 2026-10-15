# Diehl HYDRUS water meter gateway

Diehl2MQTT reads a **Diehl HYDRUS 2.0 / DME173** water meter using an RTL-SDR USB receiver. It decrypts Wireless M-Bus C1 telegrams and publishes the complete decoded data as JSON to MQTT, with automatic discovery of **eleven Home Assistant sensors**. It can also run without MQTT and output newline-delimited JSON.

Install it as a Home Assistant app, a native Proxmox LXC, or a Docker Compose service. All three use the same application, decoder sources and MQTT interface.

## Requirements

- An **amd64/x86-64** host. ARM64 is not currently supported.
- An RTL-SDR receiver supported by `rtl-sdr`, with an antenna suitable for **868.95 MHz**.
- A Diehl HYDRUS 2.0 / DME173 meter transmitting Wireless M-Bus **C1**.
- Your meter's **eight-digit Wireless M-Bus ID** and **32-character hexadecimal AES key**.
- An MQTT broker for MQTT/Home Assistant use, such as Mosquitto. Home Assistant's MQTT integration must connect to the same broker.

Use the AES key supplied for your meter, without spaces or a `0x` prefix. Preserve leading zeros in the meter ID. The meter ID is separate from the USB receiver's serial number or vendor/product ID. Examples below use the dummy ID `12345678`; replace it with your own. Other meter drivers and radio modes are not supported by this gateway.

The receiver needs exclusive access to its USB dongle. If installing in a VM, pass the dongle through to that VM.

## Install in Home Assistant

Requires **Home Assistant OS on amd64**. The app is currently **experimental**. Connect the RTL-SDR to the HA host; for a Proxmox VM, use **VM → Hardware → Add → USB Device**.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fandrekuehne%2Fdiehl2mqtt)

1. Click the button and confirm **Add** in your Home Assistant instance. If prompted, enter your local Home Assistant URL.
2. Find **Diehl Hydrus to MQTT** in the app store and select **Install**. Refresh the store if needed.
3. Open **Configuration** and enter your meter ID and AES key. All settings, passwords and keys are supplied here; no terminal setup is needed.
4. For a running Supervisor MQTT service such as Mosquitto, keep `mqtt_auto: true`. For another broker, disable it and enter its hostname, port, credentials and TLS settings. Supply the hostname/IP without `mqtt://` or a port suffix.
5. Save and **Start**. Enable **Start on boot** and **Watchdog**. Check the **Log** and the MQTT device's **Last received** sensor.

To add the repository manually, open **Settings → Apps → App store → ⋮ → Repositories** and add:

```text
https://github.com/andrekuehne/diehl2mqtt
```

Older Home Assistant versions call apps **add-ons**. Update using Home Assistant's normal app update button; configuration persists. Keep protection mode enabled: the app uses a custom AppArmor profile and runs its receiver without root privileges.

See [Home Assistant configuration and troubleshooting](ha-addon/DOCS.md) for all options, TLS certificates and USB diagnostics.

## Install on Proxmox VE

Requires **Proxmox VE 9.1+** on amd64. The installer creates an unprivileged LXC that runs the application directly, **without nested Docker**. Proxmox application-container support is a technology preview.

Connect the RTL-SDR to the node, then run as root in the **Proxmox node shell**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/main/ct/diehl2mqtt.sh)"
```

The interactive installer asks for your meter ID, AES key and MQTT settings. Secret input is hidden. Review the summary before creating the container.

Default resources are **1 CPU, 512 MiB RAM and 2 GiB disk**, with DHCP on `vmbr0`. Choose **Advanced** to customize resources, networking and demodulator settings, or specify RAM and disk directly:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/main/ct/diehl2mqtt.sh)" -- --memory 256 --disk 2
```

The installer configures USB passthrough and a host monitor for automatic startup and USB reconnect recovery. Keep the dongle on the selected physical USB port.

To open a shell inside the container, run on the Proxmox node, replacing `CTID` with its number:

```bash
pct exec CTID -- /bin/bash
```

Run application updates **inside the LXC**:

```bash
update --check
update
update --status
```

Updates preserve settings and secrets and provide automatic rollback if startup validation fails. They update the application, compiled decoders and Python dependencies; Debian package maintenance is separate.

See the [Proxmox guide](docs/proxmox.md) for console access, tuning, maintenance, rollback and removal. Use its maintenance procedure to stop the host monitor before shutting down the LXC; otherwise the monitor starts it again.

## Install with Docker Compose

Requires **Docker Engine with the Compose plugin on Linux amd64**. Follow [Docker's installation instructions](https://docs.docker.com/engine/install/) for your distribution and connect the RTL-SDR to that host or Linux VM.

Check that Docker is running and accessible:

```bash
docker version
docker compose version
```

Download the **v0.9.0** deployment archive. It includes Compose files, setup scripts and a release-specific image digest; no source checkout, local build or registry login is needed. See [GitHub Releases](https://github.com/andrekuehne/diehl2mqtt/releases) for available versions and [signature verification](SECURITY.md#verify-release-provenance) to authenticate release checksums before using them.

```bash
mkdir diehl2mqtt-install
cd diehl2mqtt-install
curl -fLO https://github.com/andrekuehne/diehl2mqtt/releases/download/v0.9.0/diehl2mqtt-v0.9.0-deploy.tar.gz
curl -fLO https://github.com/andrekuehne/diehl2mqtt/releases/download/v0.9.0/SHA256SUMS
sha256sum --ignore-missing --check SHA256SUMS
tar -xzf diehl2mqtt-v0.9.0-deploy.tar.gz
cd diehl2mqtt-v0.9.0
cp .env.example .env
chmod 600 .env
nano .env
```

Set your meter ID and broker details in `.env`, for example:

```dotenv
METER_ID=12345678
METER_NAME=Water
MQTT_HOST=192.0.2.10
MQTT_PORT=1883
MQTT_USERNAME=mqtt
MQTT_TLS=false
```

Keep the archive's `WATERMETER_IMAGE` digest, `METER_DRIVER=dme173` and `WMBUS_MODE=c1`. Use a broker hostname/IP reachable from the container; `localhost` refers to the container itself and `.local` mDNS names may not resolve there.

Supply the AES key and broker password using the hidden-input scripts:

```bash
./scripts/setup-secret.sh
./scripts/setup-mqtt-secret.sh
```

The scripts create `secrets/meter_aes_key` and `secrets/mqtt_password` with mode 0600 inside a mode-0700 directory. Existing files are not overwritten. Keep passwords and keys out of `.env` and command arguments. Compose mounts these files read-only.

Start with authenticated MQTT and Home Assistant discovery:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml pull
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d --wait
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml logs --tail 20 -f
```

Ctrl-C stops following logs while the service keeps running. Use the same Compose file list for subsequent commands.

| Mode | Compose files | Secret files |
| --- | --- | --- |
| MQTT with password | `compose.yaml`, `compose.mqtt.yaml`, `compose.mqtt.auth.yaml` | AES key and MQTT password |
| MQTT without password | `compose.yaml`, `compose.mqtt.yaml` | AES key |
| JSON only | `compose.yaml` | AES key |

For a broker without authentication, leave `MQTT_USERNAME` empty and omit the password setup. JSON-only operation does not require a broker or network access. Without MQTT, direct container stdout contains one decoded JSON object per line regardless of log level. With MQTT, decoded readings appear only in `debug` logs. Set `LOG_LEVEL` to `debug`, `info`, `warning`, `error` or `critical` (default `info`) to filter diagnostics on stderr, then recreate the container. The Home Assistant add-on exposes the same choice as `log_level` in Configuration; see [logging and storage](ha-addon/DOCS.md#logging).

To stop and remove the deployment's containers/network:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml down
```

For an upgrade, extract the new release into a separate directory, copy your protected `secrets/` and nonsecret meter/broker settings, and keep the **new** archive's image digest. Shut down the current deployment, then use the new directory's `pull` and `up -d --wait` commands. Keep the previous directory for rollback.

### Docker TLS configuration

Set `MQTT_TLS=true` and the broker's TLS port explicitly, normally `8883`. Certificate and hostname verification are mandatory. System trust is used by default.

For a custom CA or mutual TLS, save a local `compose.tls.local.yaml` override and append `-f compose.tls.local.yaml` to your Compose file list:

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

Place your PEM files in `secrets/tls/` and protect the private key. Omit the client certificate/key settings if the broker does not require mutual TLS. Omit the CA setting if the broker uses a publicly trusted certificate. Client keys must be unencrypted files.

## MQTT and Home Assistant sensors

Default topics are:

```text
watermeter/<meter-id>/state
watermeter/<meter-id>/availability
homeassistant/sensor/diehl_hydrus_<meter-id>_<field>/config
```

The gateway publishes retained state, availability and discovery messages with QoS 1. Its broker account needs publish permission for those device topics and subscribe permission for `homeassistant/status`. It republishes discovery and the latest cached state on reconnect or Home Assistant startup.

The state message contains **every field emitted by the decoder**, plus gateway `driver` and `received_at` fields. The legacy `meter` field is retained as an alias of `driver` for compatibility. The Status sensor exposes the complete JSON as attributes. Missing optional readings remain unknown; they are not replaced with zero.

Home Assistant groups the sensors under **Diehl Hydrus 2.0 ID 12345678**, using your meter ID. Sensor display names omit the ID; default entity IDs include it, for example `sensor.diehl_hydrus_12345678_total_m3`.

| Sensor | JSON field | Unit / meaning |
| --- | --- | --- |
| Total water | `total_m3` | m³; cumulative usage, suitable for Energy |
| Flow temperature | `flow_temperature_c` | °C |
| Billing period water | `target_m3` | m³; stored value |
| Billing period date | `target_datetime` | Meter-local date/time, displayed as text |
| Water at set date | `total_at_set_date_m3` | m³; stored value |
| Set date | `set_date` | Date |
| Backward water | `total_backward_m3` | m³ |
| Status | `status` | Diagnostic status and complete JSON attributes |
| Decoder timestamp | `timestamp` | Radio reception time, UTC, second precision |
| Last received | `received_at` | Gateway acceptance time, UTC, millisecond precision |
| Signal strength | `rssi_dbm` | Relative RTL-SDR amplitude; unitless, not calibrated dBm |

Available fields depend on the meter's telegram. Home Assistant displays UTC timestamps in its configured local timezone. Automatic receiver gain affects signal-strength comparisons.

Find the device under **Settings → Devices & services → MQTT**. To use water statistics, add **Total water** under **Energy → Water consumption**. If Recorder uses an include whitelist, include that entity. Total water has unit `m³`, device class `water` and state class `total_increasing`; stored historical volumes do not accumulate usage statistics.

Availability indicates that the receiver is running and connected to MQTT. It does not indicate a recent radio reading; use **Last received** to check freshness. Retained readings survive restarts. MQTT outages do not stop reception, and the latest reading is replayed when the broker reconnects.

### MQTT settings

Docker and LXC use the environment settings below. The HA app exposes corresponding fields in its Configuration tab.

| Setting | Default / purpose |
| --- | --- |
| `METER_NAME` | `Water`; label in decoded JSON |
| `WMBUS_FREQUENCY` | `868.95M` |
| `MQTT_HOST` | Broker hostname/IP without a URL scheme |
| `MQTT_PORT` | Compose default `1883`; set explicitly for TLS |
| `MQTT_USERNAME` | Empty for anonymous access |
| `MQTT_PASSWORD_FILE` | Protected password-file path |
| `MQTT_TLS` | `false`; enable verified TLS |
| `MQTT_CA_FILE` | Optional custom CA file |
| `MQTT_CLIENT_CERT_FILE`, `MQTT_CLIENT_KEY_FILE` | Optional mutual-TLS pair |
| `MQTT_TOPIC_PREFIX` | `watermeter` |
| `MQTT_CLIENT_ID` | `watermeter_<meter-id>` |
| `HA_DISCOVERY_ENABLED` | `true` when MQTT is enabled |
| `HA_DISCOVERY_PREFIX` | `homeassistant` |
| `HA_STATUS_TOPIC` | `homeassistant/status` |

Only one publisher should use a meter's state/availability topics. Keep the meter ID and topic prefixes stable to reuse existing Home Assistant entities. Home Assistant preserves user-customized names and existing entity IDs.

## Select the RTL-WMBus decoder

Version 0.9.0 bundles two decoders: `reference` is the existing pinned xaelsouth upstream build (default); `dev` is a snapshot of [andrekuehne/rtl-wmbus dev](https://github.com/andrekuehne/rtl-wmbus/tree/dev), built when the gateway image is built. Only the selected decoder runs. Both use the same C1/T1 processing flags, frequency, fast-math and algorithm settings; MQTT topics and Home Assistant entities keep their identities.

- **Docker:** set `WMBUS_DECODER=dev` in `.env` and recreate with your existing Compose `up -d --wait` command.
- **HA app:** select `dev` under **RTL-WMBus decoder**, save and restart.
- **Native LXC:** use `--decoder dev` during installation, or follow the [existing-LXC switching instructions](docs/proxmox.md#decoder-selection).

Switch back with `reference`. Startup diagnostics identify the selected decoder and commit; `docker compose run --rm watermeter versions` reports both bundled commits without needing a meter key. The fork is fetched only during builds. Updating an installation supplies a newer bundled snapshot; restarting alone does not download changes. Docker source builds track `dev` automatically; `docker build --build-arg RTL_WMBUS_DEV_REF=<full-commit> .` reproduces a selected snapshot.

For field testing, keep frequency, math and algorithm settings identical and compare CPU use, fresh readings and reception gaps over alternating reference/dev periods. Replay tests do not prove unchanged RF sensitivity. Before rolling back to a gateway older than 0.9.0, select `reference` first.

## Reduce SDR CPU use

The receiver continuously processes **1.6 million samples per second**, including between telegrams. Most CPU use comes from the `rtl_wmbus` demodulator. Two runtime settings allow tuning without recompiling:

| Docker/LXC setting | HA Configuration key | Values | Default |
| --- | --- | --- | --- |
| `WMBUS_FAST_MATH` | `fast_math` | `true`, `false` | `false` |
| `WMBUS_ALGORITHM` | `algorithm` | `both`, `runlength`, `time2` | `both` |

Start with fast math enabled and both algorithms. Approximate math reduces CPU use; selecting one algorithm can reduce it further but also reduces reception diversity. Compare fresh readings and reception gaps on your installation and restore defaults if reception worsens.

- **HA app:** change Configuration, save and restart.
- **Docker:** set these values in `.env`, then recreate with the same Compose `up -d --wait` command. A plain restart does not reload `.env`.
- **LXC:** select the options during Advanced setup or follow the [LXC tuning instructions](docs/proxmox.md#demodulator-tuning).

The startup log reports the selected settings.

## Troubleshooting

- **No SDR or USB access error:** confirm the receiver is visible on the deployment host/VM and available exclusively to the gateway. Check the runtime log for access, busy-device or disconnect diagnostics. See [HA USB troubleshooting](ha-addon/DOCS.md#updates-and-troubleshooting) or the [Proxmox guide](docs/proxmox.md#usb-access-and-automatic-restart).
- **Receiver runs but no readings arrive:** check the meter ID, AES key, antenna, frequency and reception range. A healthy process or visible USB device does not establish successful decryption.
- **All HA sensors unavailable:** check the receiver and MQTT connection logs. Ensure another publisher is not using the same MQTT client ID or availability topic.
- **Device deleted in HA:** restart the gateway to replay discovery, or publish `online` to `homeassistant/status`.
- **Total water missing from Energy:** check for a numeric state and the attributes listed above. Check Home Assistant's Statistics page and Recorder filters, then allow a statistics cycle before reopening Energy settings.

## Security and documentation

The HA app keeps protection mode enabled and confines its non-root receiver with AppArmor. Standalone Docker and native LXC have different permission models; see the [security policy](SECURITY.md). Runtime decoder secrets are stored temporarily on private tmpfs. HA configuration backups and LXC backups contain persistent credentials and should be protected.

Release images and checksum files are signed. See [signature verification](SECURITY.md#verify-release-provenance), [Home Assistant documentation](ha-addon/DOCS.md), [Proxmox documentation](docs/proxmox.md), and [build, test and release guidance](docs/development.md).

The gateway uses [rtl-wmbus](https://github.com/xaelsouth/rtl-wmbus), [wmbusmeters](https://github.com/wmbusmeters/wmbusmeters) and [Eclipse Paho MQTT](https://github.com/eclipse-paho/paho.mqtt.python). Dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); releases include corresponding source/build materials and the image records dependency versions under `/usr/share/watermeter/`.
