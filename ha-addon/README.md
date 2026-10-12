# Diehl Hydrus to MQTT

Read a Diehl HYDRUS 2.0 / DME173 meter with an RTL-SDR, decrypt C1 telegrams and publish the complete decoded data to MQTT. Includes automatic discovery of all eleven Home Assistant sensors.

Requires Home Assistant OS on amd64 with the RTL-SDR connected or passed through to its VM.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fandrekuehne%2Fdiehl2mqtt)

1. Click the button and confirm adding the repository in your local Home Assistant instance.
2. Install **Diehl Hydrus to MQTT** from the app/add-on store.
3. In **Configuration**, enter your eight-digit meter ID, 32-hex-character AES key and MQTT settings. Automatic MQTT uses the Supervisor MQTT service; disable it for a manual broker.
4. Save and start. Enable **Start on boot** and **Watchdog**, then check the Log and a fresh MQTT reading.

The receiver needs exclusive access to its USB dongle. Everything, including passwords and keys, is configured in the Configuration tab. See [Documentation](DOCS.md) for manual repository setup, USB passthrough, configuration and troubleshooting. The app is currently experimental; keep protection mode enabled.
