# Verification record

## Local implementation acceptance

The work packages were implemented and committed separately. On the owner’s Linux amd64 host, the production image/native smoke checks, private runtime configuration, supervised process lifecycle, real-broker MQTT authentication/TLS/reconnect/discovery tests, Compose USB reception and graceful restart were verified. Home Assistant’s three MQTT entities and Energy water selection were owner-confirmed after adding the sensor to the Recorder whitelist. Real meter identifiers, captured telegrams and runtime keys are omitted from public evidence.

## Public examples and privacy

- All image/code/Compose defaults and example identities use dummy ID `12345678`; release deployments require an explicit meter ID. Leading zeros are preserved.
- The encrypted fixture is synthetic, with dummy ID `12345678`, total 0.252 m³, temperature 16.8 °C and public test key `00112233445566778899aabbccddeeff`. It was verified with the pinned native decoder. No owner capture is distributed.
- Production AES/MQTT secrets and real meter settings remain local and ignored. CI uses only the public synthetic key.
- Public Git history is being rewritten at the owner’s explicit request, preserving the work-package commit structure while replacing prior ID/telegram references. Older releases, CI artifacts/logs and affected build caches are being withdrawn; clean publication is verified separately.

## Publication and remaining checks

Repository: https://github.com/andrekuehne/diehl2mqtt. CI targets Linux amd64 only. Trusted main/weekly builds publish tested images to GHCR; version releases contain build-free deployment/source archives and checksums. The exact saved production image is published without rebuilding.

The original hosted builds and release packaging passed before the privacy revision. The synthetic-fixture revision and replacement release must pass fresh CI and anonymous-pull verification before handoff. A destination host must still verify its own USB passthrough, real-key decryption and MQTT delivery. arm64, HA restart stability, physical unplug/replug stress and Proxmox/rootless deployment remain unverified.
