# Deploy diehl2mqtt (Linux amd64)

Install Docker Engine with Compose, connect the RTL-SDR to this Linux host (or pass it through to your Linux VM), then extract this deployment archive. No source checkout or local image build is needed. arm64 is deferred.

From this directory:

```bash
cp .env.example .env
./scripts/setup-secret.sh
./scripts/setup-mqtt-secret.sh
```

Edit `.env` before starting. Set these nonsecret options (replace the example ID and broker address):

```dotenv
METER_ID=12345678
METER_NAME=Water
MQTT_HOST=192.0.2.10
MQTT_PORT=1883
MQTT_USERNAME=mqtt
MQTT_TLS=false
```

`METER_ID` is the water meter's **eight-digit Wireless M-Bus ID**, not the SDR's USB serial/vendor/product ID. Preserve leading zeros, for example `00123456`. It is deliberately blank in the release's example settings and must be supplied. Keep `METER_DRIVER=dme173` and `WMBUS_MODE=c1`; the supported meter is Diehl HYDRUS 2.0 / DME173. The image is already pinned to this release's registry digest, so retain `WATERMETER_IMAGE`. Use a broker address reachable from Docker; `.local` mDNS may fail inside containers.

All source defaults and test IDs are dummy examples. Use your own meter ID here; the synthetic fixture's public test key is never a production key.

`setup-secret.sh` prompts for the AES key supplied for your meter: **exactly 32 hexadecimal characters** (16 bytes), without spaces or a `0x` prefix. Input is hidden and saved only to `secrets/meter_aes_key`. The password script similarly creates `secrets/mqtt_password`. The directory uses mode 0700 and files mode 0600; existing files are not overwritten. Compose mounts the key read-only at `/run/secrets/meter_aes_key` and supplies its path through `METER_AES_KEY_FILE`. Keep both secrets out of `.env`, command arguments, GitHub and the image. The ID itself belongs in `.env`.

For authenticated MQTT and Home Assistant discovery:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml pull
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d --wait
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml logs --tail 20 -f
```

For anonymous MQTT, omit `compose.mqtt.auth.yaml` and the password setup. For JSON-only operation, use only `compose.yaml` and the AES secret. Public GHCR images require no registry login.

The default broker connection uses no TLS. For TLS configuration, USB permissions, Proxmox passthrough, health, cleanup and troubleshooting, see the full [project README](https://github.com/andrekuehne/diehl2mqtt#readme). The receiver needs exclusive access to the dongle. Run only one instance for this meter/MQTT client identity.

MQTT publishes the complete decoded telegram as retained JSON. Home Assistant discovers ten sensors for current/stored readings, dates and diagnostics; every name ends with your meter ID. New entity IDs place it immediately after `diehl_hydrus`, for example `sensor.diehl_hydrus_12345678_total_m3`. Status exposes the complete JSON as attributes. Optional values remain unknown when absent. Existing entity identities are preserved; Home Assistant only applies default entity IDs when first registering an entity.

In Home Assistant, find the Water device under MQTT. Total water uses `m³`, `water` and `total_increasing`. If your Recorder has an include whitelist, include this sensor before adding it under Energy → Water consumption. Check States and Statistics if it does not appear.

For direct **Proxmox VE 9.1+ without Docker**, connect the SDR to the node and run this as root in the **Proxmox node shell**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/andrekuehne/diehl2mqtt/main/ct/diehl2mqtt.sh)" -- --memory 256 --disk 2
```

The dialog setup asks for your meter ID, broker settings and hidden AES/MQTT secrets. This command requests 256 MiB RAM and 2 GiB disk; omitting those options uses the conservative 512 MiB RAM default. You can also launch the included wrapper with `bash ct/diehl2mqtt.sh --memory 256 --disk 2`, or use `python3 scripts/install-proxmox.py --plain` for plain prompts. Run `update` inside the installed LXC for application updates. See the [Proxmox instructions](https://github.com/andrekuehne/diehl2mqtt/blob/main/docs/proxmox.md) for preflight, verification and operations.

To stop:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml down
```

For upgrades, download the next release into a separate directory, copy your protected `secrets/` and nonsecret broker/meter settings into it, and retain the new release's `WATERMETER_IMAGE` digest. Stop the old deployment before starting the new one. Keep the previous directory and digest for rollback. Updates are intentional; CI never updates your host automatically.

Each release also supplies checksums and pinned native source/build materials. The full verification record and license notices live in the source repository.
