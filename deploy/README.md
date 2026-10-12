# Deploy diehl2mqtt (Linux amd64)

Install Docker Engine with Compose, connect the RTL-SDR to this Linux host (or pass it through to your Linux VM), then extract this deployment archive. No source checkout or local image build is needed. arm64 is deferred.

From this directory:

```bash
cp .env.example .env
./scripts/setup-secret.sh
./scripts/setup-mqtt-secret.sh
```

Edit `.env`: set your eight-digit meter ID/name and MQTT broker hostname/IP, port and username. The image is already pinned to this release's registry digest. Use a broker address reachable from Docker; `.local` mDNS may fail inside containers. Keep the AES key and MQTT password in the protected files created by the scripts, never in `.env` or command arguments. The supported meter driver is `dme173` in C1 mode.

For authenticated MQTT and Home Assistant discovery:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml pull
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d --wait
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml logs --tail 20 -f
```

For anonymous MQTT, omit `compose.mqtt.auth.yaml` and the password setup. For JSON-only operation, use only `compose.yaml` and the AES secret. Public GHCR images require no registry login.

The default broker connection uses no TLS. For TLS configuration, USB permissions, Proxmox passthrough, health, cleanup and troubleshooting, see the full [project README](https://github.com/andrekuehne/diehl2mqtt#readme). The receiver needs exclusive access to the dongle. Run only one instance for this meter/MQTT client identity.

In Home Assistant, find the Water device under MQTT. Total water uses `m³`, `water` and `total_increasing`. If your Recorder has an include whitelist, include this sensor before adding it under Energy → Water consumption. Check States and Statistics if it does not appear.

To stop:

```bash
docker compose -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml down
```

For upgrades, download the next release into a separate directory, copy your protected `secrets/` and nonsecret broker/meter settings into it, and retain the new release's `WATERMETER_IMAGE` digest. Stop the old deployment before starting the new one. Keep the previous directory and digest for rollback. Updates are intentional; CI never updates your host automatically.

Each release also supplies checksums and pinned native source/build materials. The full verification record and license notices live in the source repository.
