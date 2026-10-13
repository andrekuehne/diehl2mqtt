# Build, test and release guidance

User installation and configuration instructions are in the [README](../README.md). This guide covers source builds and repository maintenance.

## Build from source

Requires Linux amd64, Docker Engine and the Compose plugin:

```bash
git clone https://github.com/andrekuehne/diehl2mqtt.git
cd diehl2mqtt
docker build --pull -t watermeter:local .
./scripts/test-offline.sh
./scripts/test-mqtt.sh
```

The offline test uses the public synthetic fixture and does not require USB or production credentials. The MQTT test builds a disposable test image with a loopback Mosquitto broker and runs without external networking. It covers settings/secrets, decoder boundaries, process lifecycle, retained messages, discovery, reconnect, authentication and TLS.

Additional host-installer and manifest checks:

```bash
python3 -m unittest discover -s tests/proxmox -v
python3 scripts/check-addon.py
```

The manifest check requires PyYAML. CI also validates the native LXC layout, HA startup/recovery, enforced AppArmor, non-root privileges and image conversion. See [SECURITY.md](../SECURITY.md#local-confinement-tests) for the confinement-test prerequisites.

To deploy from the source checkout, copy `.env.example` to `.env.local`, set your meter/broker options and create the secrets using the README's setup scripts. Use the same Compose overrides as your selected mode:

```bash
docker compose --env-file .env.local \
  -f compose.yaml -f compose.mqtt.yaml -f compose.mqtt.auth.yaml up -d --build --wait
```

To use a published image instead, set `WATERMETER_IMAGE` to its digest, run `pull`, and use `up -d --no-build --wait`. Never commit local configuration, credentials or captured meter data. The synthetic fixture's key is public test data and cannot validate a production key.

## Shared build and dependencies

The Dockerfile builds the decoder sources and hashed Python dependencies once in its shared build definition. Both runtime targets inherit the `runtime` stage; the HA target supplies its own startup adapter and healthcheck. The LXC installer imports the standalone image, and release application bundles are extracted from that tested image for native updates.

- `RTL_WMBUS_REF` and `WMBUSMETERS_REF` are full source commits in `Dockerfile`.
- The Debian base is pinned by digest; available Debian package updates are applied during image builds.
- `requirements.txt` pins Paho MQTT with a wheel hash.
- `/usr/share/watermeter/versions.txt` records source revisions; `packages.txt` records runtime Debian packages.

Inspect the installed versions and read-only dependency update candidates:

```bash
docker run --rm --network none watermeter:local versions
./scripts/check-updates.sh
```

Review upstream changes before updating pins, including CLI/config compatibility, licenses, driver behavior and Paho callbacks/TLS. Paho build metadata is read from the installed package, so dependency updates also update its recorded version. The Paho TLS adapter uses a pinned private API and needs review when upgrading Paho.

After changing dependencies, build without cache and rerun the offline, MQTT and deployment-specific checks. Live reception and destination-host behavior need separate verification. The [implementation notes](implementation-notes.md) describe upstream interfaces; the [verification record](verification.md) holds historical results.

## CI and publication

PR builds have read-only permissions and cannot publish. Main pushes and scheduled builds publish tested images; manual main builds publish only when the `publish` input is enabled. Weekly rebuilds refresh packages while retaining reviewed source/base pins. Dependabot checks Docker base images, GitHub Actions and Python requirements weekly and opens update PRs. GitHub Dependabot vulnerability alerts and security update PRs are also enabled. Updates are reviewed and tested; they are not automatically merged or deployed.

CI saves the tested images and the publication job loads them without rebuilding. Both runtime images are scanned; fixable HIGH/CRITICAL vulnerabilities block publication. The trusted publication job signs image digests and release checksums using GitHub OIDC/Cosign and verifies the signatures. See [SECURITY.md](../SECURITY.md).

## Versioned releases

Choose an unused `vMAJOR.MINOR.PATCH` version and align:

1. `ha-addon/config.yaml` and `HA_ADDON_VERSION` in `Dockerfile`.
2. `DEFAULT_RELEASE` in `scripts/install-proxmox.py`.
3. The release and installer SHA256 pins in `ct/diehl2mqtt.sh`.
4. The changelog and installation examples.

Run the checks, commit to main, then tag and push that commit. CI rejects malformed release tags and commits outside main's history. The tag workflow publishes versioned images and a GitHub release containing deployment, native application and source archives, image metadata, checksums and their signature bundle.

Standalone release tags use `vMAJOR.MINOR.PATCH`; HA image tags omit the `v`. `latest` follows main/weekly publication; a version release does not move it. GHCR package visibility must be public for anonymous pulls. CI never updates deployed hosts automatically.

When redistributing binaries, include corresponding source/build materials in accordance with the dependency licenses. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
