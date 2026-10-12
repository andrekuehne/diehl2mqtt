# Diehl Hydrus to MQTT

Read a Diehl HYDRUS 2.0 / DME173 meter with an RTL-SDR, decrypt C1 telegrams and publish the complete decoded data to MQTT. Includes automatic discovery of all ten existing Home Assistant sensors.

Linux amd64 / Home Assistant OS. Configure everything, including the AES key and MQTT password, in the Configuration tab. See [Documentation](DOCS.md) for USB passthrough, configuration and migration.
