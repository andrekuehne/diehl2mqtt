# Changelog

## 0.7.0

- Configure fast demodulator math and select both, runlength, or time2 algorithms in Configuration. Defaults preserve existing reception behavior.
- Share validated runtime tuning across the add-on, Docker and native Proxmox LXC deployments.

## 0.6.0

- First amd64 Home Assistant add-on, using the same decoder and MQTT interface as Docker and LXC.
- Configuration-tab meter ID, AES key, MQTT credentials, TLS certificates and discovery settings.
- Automatic Supervisor MQTT service or manual broker configuration.
- Private tmpfs decoder configuration, receiver retries after USB failure and process-based watchdog.
- Device name includes the meter ID; sensor display names omit it; entity IDs remain unchanged.
