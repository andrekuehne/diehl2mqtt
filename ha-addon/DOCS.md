# Installation

Requires Home Assistant OS on amd64 (for example your Proxmox HA VM) and a single supported RTL-SDR. arm64 is deferred. This is initially marked experimental until actual HA OS reception, reboot and USB reconnect have been verified.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fandrekuehne%2Fdiehl2mqtt)

1. Stop any previous reader, including its automatic startup/monitoring. For our LXC, run on the **Proxmox node**, replacing `CTID`:

   ```bash
   systemctl disable --now diehl2mqtt-lxc@CTID.timer
   systemctl stop diehl2mqtt-lxc@CTID.service
   pct shutdown CTID
   ```

2. In Proxmox, pass the RTL-SDR through to the **Home Assistant VM** (VM → Hardware → Add → USB Device). Remove the old reader's competing USB assignment as appropriate. The HA VM must actually see the device; VM USB reattachment after reconnect is handled by Proxmox.
3. Click the button above, enter your local Home Assistant URL if prompted, and confirm **Add** in the prefilled repository dialog. Alternatively, open **Settings → Apps** (older versions: **Add-ons**) → **App/Add-on store → ⋮ → Repositories** and add `https://github.com/andrekuehne/diehl2mqtt` manually.
4. Install **Diehl Hydrus to MQTT**. Open **Configuration**, enter your own meter ID and AES key, configure MQTT, and save.
5. Start the add-on. Enable **Start on boot** and **Watchdog**. Check **Log**, then the MQTT device and a fresh **Last received** timestamp.

The device is `Diehl Hydrus 2.0 ID <meter ID>`. Sensor names are `Total water`, `Flow temperature`, etc. Entity IDs still include the ID, such as `sensor.diehl_hydrus_12345678_total_m3`. Do not delete existing entities when migrating: the same broker, meter ID and topic settings reuse the same discovery identities. Existing manual name overrides remain under your control. Recorder whitelists must include Total water for Energy statistics.

# Configuration

Everything is configured in the Configuration tab, including passwords and the AES key. No terminal secret setup scripts are needed. Password fields mask the values in the form; these values are stored in persistent add-on options and included with its configuration in backups. Decoder-generated files are private and temporary in `/tmp/watermeter` on tmpfs. Keys/passwords and the Supervisor token are not passed to the radio/decoder children or logged.

Required: `meter_id` is **text containing exactly eight digits**, preserving leading zeros. `aes_key` is exactly **32 hexadecimal characters**. There is no preset real ID or AES key. The driver and radio mode are fixed to `dme173` / C1, with default `frequency: 868.95M`. `meter_name` only labels the decoded JSON.

**CPU tuning** (0.7.0+): `fast_math: true` enables approximate atan at runtime. `algorithm` selects `both` (default), `runlength`, or `time2`; a single algorithm reduces CPU and reception diversity. No recompilation is required. Defaults remain `fast_math: false` and `algorithm: both`, including when upgrading older options. Start with fast math and both algorithms, compare fresh readings/reception gaps, and revert if reception worsens. A short desktop test used about 11% of one core with fast math versus 19% with defaults; only two distinct telegrams were compared, so weak-signal behavior needs local verification. See [CPU measurements](https://github.com/andrekuehne/diehl2mqtt#reduce-sdr-cpu-use). Save and restart the add-on after changes; the startup log shows the selected options.

**Automatic MQTT** (`mqtt_auto: true`, default) uses the MQTT service registered with Supervisor, normally the Mosquitto add-on. Have the broker running before starting the reader. Its host, port, username/password and TLS flag replace the manual broker fields; topic/discovery options still apply. If no service is registered, use manual mode.

**Manual MQTT**: disable `mqtt_auto`, then set `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` and `mqtt_tls`. Host is a hostname/IP without `mqtt://`. For anonymous MQTT leave both username and password blank. TLS verifies the broker hostname and certificate. System CAs are used unless you supply `mqtt_ca_certificate`. Optional mutual TLS uses `mqtt_client_certificate` and `mqtt_client_key` together. Paste PEM values in Configuration's YAML editor with `|` block syntax; the client key must be unencrypted. Restart the add-on after saving configuration changes.

Example **manual** configuration (dummy values; replace them):

```yaml
meter_id: "12345678"
aes_key: "REPLACE_WITH_YOUR_32_HEX_CHARACTER_KEY"
meter_name: Water
frequency: 868.95M
fast_math: false
algorithm: both
mqtt_auto: false
mqtt_host: "192.0.2.10"
mqtt_port: 1883
mqtt_username: mqtt
mqtt_password: "REPLACE_WITH_YOUR_PASSWORD"
mqtt_tls: false
mqtt_ca_certificate: ""
mqtt_client_certificate: ""
mqtt_client_key: ""
mqtt_topic_prefix: watermeter
mqtt_client_id: ""
ha_discovery: true
ha_discovery_prefix: homeassistant
ha_status_topic: homeassistant/status
```

The default MQTT interface is unchanged:

```text
watermeter/<meter-id>/state
watermeter/<meter-id>/availability
homeassistant/sensor/diehl_hydrus_<meter-id>_<field>/config
```

Complete decoded JSON, QoS 1, retained state/discovery, online/offline availability, Home Assistant birth replay and all ten sensors work as before. An empty `mqtt_client_id` derives `watermeter_<meter ID>`. Run only one publisher for that meter; even different client IDs would still conflict on shared state/availability topics. Changing prefixes deliberately creates different topic paths.

# Updates and troubleshooting

Update through Home Assistant's normal app/add-on update button. Options persist across image replacement. The native LXC `update` command is not used here. `0.7.0` is the add-on image tag; `v0.7.0` is the standalone Docker/LXC image tag in the same public GHCR package. CI tests each image before publishing.

The add-on requests raw USB access, keeps protection mode enabled and does not request full hardware access, host networking, host PID or broad Supervisor API access. Only the configured Supervisor MQTT service is consumed. No web UI or host network port is exposed. A private-network `/health` endpoint drives Watchdog; it checks the pipeline processes and heartbeat, independently of reception gaps and broker outages.

- **No SDR / permission / claimed driver:** check Proxmox VM passthrough and the add-on Log. Only one program may use the dongle. If the guest's DVB driver claims it, inspect the HA OS host driver binding; do not disable protection mode or add broad privileges as a first step.
- **USB removed:** the receiver cleans up and retries every five seconds. Reconnect must make the device visible again to the HA VM, not just to Proxmox. Enable Watchdog to recover a hung pipeline.
- **All sensors unavailable:** inspect MQTT reconnect/receiver diagnostics and verify no old Docker or LXC reader is still publishing.
- **Nothing discovered after deleting a device:** restart the add-on or publish `online` to `homeassistant/status` to replay discovery.
- **Broker outage:** reception continues and the latest state is cached for replay on reconnect. Startup in automatic mode needs the Supervisor MQTT service to be available.

The local/CI checks use synthetic meter data and an isolated broker. Actual HA OS installation, USB permissions, live decryption, VM reboot and physical USB reconnect require verification on your destination VM.
