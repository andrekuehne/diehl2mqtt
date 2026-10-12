# Changelog

## 0.7.2

- Run the shared SDR/decoder pipeline in UTC, fixing decoder timestamps shifted by the host/HA timezone. HA continues displaying timestamps in its configured local timezone.
- Discover Signal strength as an eleventh, unitless diagnostic sensor. The existing MQTT `rssi_dbm` field is relative RTL-SDR amplitude, not calibrated dBm.
- Clarify that USB error -5 can indicate a missing interface as well as a missing device.

## 0.7.1

- Report specific USB access, busy, disconnect, kernel detach and transfer errors without printing upstream secrets or telegrams.
- Preserve pending error messages when a pipeline process exits, and report its exit code. Receiver retries continue as before.

## 0.7.0

- Configure fast demodulator math and select both, runlength, or time2 algorithms in Configuration. Defaults preserve existing reception behavior.
- Share validated runtime tuning across the add-on, Docker and native Proxmox LXC deployments.

## 0.6.0

- First amd64 Home Assistant add-on, using the same decoder and MQTT interface as Docker and LXC.
- Configuration-tab meter ID, AES key, MQTT credentials, TLS certificates and discovery settings.
- Automatic Supervisor MQTT service or manual broker configuration.
- Private tmpfs decoder configuration, receiver retries after USB failure and process-based watchdog.
- Device name includes the meter ID; sensor display names omit it; entity IDs remain unchanged.
