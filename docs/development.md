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
python3 -m unittest discover -s tests/maintenance -v
python3 scripts/check-addon.py
```

The manifest check requires PyYAML from `requirements-dev.txt`. This CI/host dependency is also tracked by Dependabot and is not installed in runtime images. CI also validates the native LXC layout, HA startup/recovery, enforced AppArmor, non-root privileges and image conversion. See [SECURITY.md](../SECURITY.md#local-confinement-tests) for the confinement-test prerequisites.

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

**Renovate** proposes PRs for the `rtl-wmbus` and `wmbusmeters` commit pins. Its custom regex managers in `renovate.json` track each upstream `master` branch while retaining immutable 40-character commit hashes in Dockerfile. Both build/runtime occurrences are included in each update; CI rejects mismatched pins. Only the custom managers are enabled, so Renovate does not duplicate Dependabot's Docker, GitHub Actions or Python PRs.

Install the [Renovate GitHub app](https://github.com/apps/renovate) for **only this repository** (`andrekuehne/diehl2mqtt`) to activate the configuration. The committed config handles onboarding. Renovate creates a Dependency Dashboard and opens native update PRs during the Monday 00:00–06:00 Europe/Berlin window. To request an update outside the window, use the dashboard's pending-update approval controls. See [Renovate installation](https://docs.renovatebot.com/getting-started/installing-onboarding/) and [Git-ref digest tracking](https://docs.renovatebot.com/modules/datasource/git-refs/).

Automatic merging is disabled. Branch-head updates may be unreleased; review upstream changes, CI results and live reception before merging. A merged PR updates the main build but does not create a numbered release or update an installed deployment. The former native issue watcher is retired; its existing review issues remain historical maintenance notes. Renovate proposes revisions but does not replace a manual assessment of inactive/archived upstream projects.

Monitoring still needs occasional maintainer attention: [Dependabot can pause when update PRs remain untouched for 90 days](https://docs.github.com/en/code-security/reference/supply-chain-security/troubleshoot-dependabot/dependabot-updates-stopped). Check Dependabot and Renovate's dashboard if updates stop. The existing weekly image-build workflow is also subject to [GitHub's scheduled-workflow inactivity rules](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow). Hosted Renovate does not rely on that repository workflow. Weekly images refresh Debian packages within the selected distribution; OS-family changes and existing LXC system packages need separate maintenance.

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

## Fork snapshots and release 0.9.0

Every CI run resolves `andrekuehne/rtl-wmbus`'s `refs/heads/dev` once and passes the resulting full commit as `RTL_WMBUS_DEV_REF` to the standalone, test and HA builds. Local builds use BuildKit's remote Git source at `dev`, allowing source changes to invalidate its cache. The upstream `RTL_WMBUS_REF`, wmbusmeters pin and their Renovate policy are unchanged. No fork hash is maintained in the repository.

Both real binaries must pass reviewed IQ replays and the gateway tuning matrix. Fork source, tests and compiler stay in build stages; runtime contains the binaries, notices and resolved metadata. Versioned release packaging reads the fork commit from the tested image, verifies the reference pins, and archives that exact fork source rather than fetching the branch head again.

Use the existing manual Build and verify workflow to build current dev and optionally publish latest images. HA/native LXC distribution requires a new versioned gateway release: 0.9.0, then 0.9.1 etc. Published release assets and semver image tags cannot be overwritten; rerunning a published version fails. Existing triggers and signing remain in place. Publishing latest tags does not update installed systems.
