# Verification record

## Local implementation acceptance

The work packages were implemented and committed separately. On the owner’s Linux amd64 host, the production image/native smoke checks, private runtime configuration, supervised process lifecycle, real-broker MQTT authentication/TLS/reconnect/discovery tests, Compose USB reception and graceful restart were verified. Home Assistant’s three MQTT entities and Energy water selection were owner-confirmed after adding the sensor to the Recorder whitelist. Real meter identifiers, captured telegrams and runtime keys are omitted from public evidence.

## Public examples and privacy

- All image/code/Compose defaults and example identities use dummy ID `12345678`; release deployments require an explicit meter ID. Leading zeros are preserved.
- The encrypted fixture is synthetic, with dummy ID `12345678`, total 0.252 m³, temperature 16.8 °C and public test key `00112233445566778899aabbccddeeff`. It was verified with the pinned native decoder. No owner capture is distributed.
- Production AES/MQTT secrets and real meter settings remain local and ignored. CI uses only the public synthetic key.
- Public Git history was rewritten and force-pushed at the owner’s explicit request, preserving the work-package commit structure while replacing prior ID/telegram references. Older releases/tags, four original CI runs and their artifacts/logs, and 47 affected build caches were deleted. All reachable local Git objects, including application snapshot refs, were checked for prior identity/capture references.
- The owner manually deleted the legacy GHCR versions after the API refused deletion under its public-download limit. Public version listings and anonymous registry requests confirmed the old versions/tags and original release digest are unavailable. GitHub still serves an old Git commit by its previous SHA after the force push; removing that provider-held copy requires GitHub Support. No container image or executable bytes were patched: text was edited, the public fixture was generated anew, and new images were built from source.

## Publication and remaining checks

Repository: https://github.com/andrekuehne/diehl2mqtt. CI targets Linux amd64 only. Trusted main/weekly builds publish tested images to GHCR; version releases contain build-free deployment/source archives and checksums. The exact saved production image is published without rebuilding.

The sanitized main and v0.2.0 release builds passed hosted CI. The local full image test suite passed 23 tests. Published v0.2.0 assets passed SHA256 checks; the exact release image was pulled anonymously and decoded the public synthetic fixture successfully. Its environment defaults use the dummy ID. The downloaded deployment requires a meter ID, preserves leading zeros and contains no build step. Read-only audits of 58 published deployment/project-source files found no prior owner identity or captured telegram. When manual package cleanup also removed the clean v0.2.0 image, its publication job was rerun successfully using the original tested artifact, restoring the same release digest. The existing private live reader remained healthy.

A destination host must still verify its own USB passthrough, real-key decryption and MQTT delivery. arm64, HA restart stability, physical unplug/replug stress and Proxmox/rootless deployment remain unverified.
