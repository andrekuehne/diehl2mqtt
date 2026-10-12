# Security

Report suspected vulnerabilities through this repository's GitHub **Security → Report a vulnerability** when available; otherwise contact the maintainer privately before disclosing credentials or exploit details. Never include meter AES keys, MQTT passwords or complete private configuration in public issues.

## Home Assistant app

The app remains **experimental**. This developer-selected lifecycle label is separate from Home Assistant's permission-based security score. With AppArmor available and the supplied profile installed, the expected score is **8/8**; that score is not an independent security audit.

The app keeps protection mode enabled and requests raw USB plus the optional Supervisor MQTT service. It requests no added Linux capabilities, broad Supervisor/Home Assistant API rights, host networking, host namespaces, host folders, Docker API or full hardware access. The health endpoint is on the private app network, with no published host port and no configuration/credential response.

`ha-addon/apparmor.txt` restricts execution to tini, Python and the three receiver binaries, makes Configuration read-only, and permits generated files only below `/tmp/watermeter`. Library/code paths are read-only. USB bus numbers remain dynamic for hotplug; raw USB access covers the USB bus exposed by Supervisor, not exclusively one vendor/product. The profile does not permit shells, package managers, mounts or arbitrary device access. MQTT/DNS and Supervisor service lookup require network access; AppArmor's rules do not restrict these connections to a particular broker hostname.

The image starts tini and a short Python bootstrap as root to read Supervisor-owned `/data/options.json` and transfer ownership of its private tmpfs directory. Before certificate/config generation, broker lookup, receiver startup or health serving, Python changes to **UID 10001, primary GID 0, no supplementary groups**, clears all Linux capabilities including the bounding set, and enables `no_new_privs`. Receiver children inherit these restrictions. Tini remains root solely as the process reaper/signal forwarder. Failed privilege reduction stops startup; it never falls back to running the receiver as root.

GID 0 permits read/write of standard HAOS `root:root` USB nodes with group-write permissions (normally mode 0664), including newly enumerated nodes after reconnect. Group membership does not grant root UID or capabilities, but can access other group-accessible files allowed by AppArmor. We do not chmod/chown host USB nodes or install host udev rules. Custom host permissions that omit group-write access can prevent reception; use the classified error in the app log to diagnose this rather than disabling protection.

Configuration-tab AES/MQTT secrets remain in Supervisor-managed persistent options and Home Assistant backups by design. Generated decoder/TLS files use private tmpfs directories and mode 0600. Tokens and credentials are not passed through child process environments or command arguments; the Supervisor token is used only for the declared MQTT service lookup. The app does not expose a web UI.

## Builds and vulnerability policy

Base image digests, native source commits, Python dependency hashes and GitHub Action commits are pinned. Debian packages receive available updates during image builds; installed versions are recorded in the image. Runtime images omit pip/setuptools. Dependabot proposes Docker/Action pin changes, and weekly uncached builds refresh packages and scan against the current vulnerability database.

CI scans **both exact runtime images**, including OS and Python packages, on PRs, main pushes, tags, manual runs and weekly builds. Full JSON reports, including unfixed and lower-severity findings, are available as the `image-vulnerability-reports` workflow artifact for 30 days. Fixable HIGH/CRITICAL vulnerabilities fail the test job and block publication. Scanner/database failures also fail CI. Unfixed vulnerabilities are reported but do not automatically block releases; a passing gate does not imply an image is vulnerability-free. No blanket CVE suppressions are configured.

Only trusted main/tag/scheduled publication jobs can write GHCR/releases or request an OIDC token. PR jobs have read-only permissions and cannot sign or publish. Publishing uses the exact images built and tested by CI, without rebuilding.

## Verify release provenance

From v0.8.0, CI signs standalone and HA image **digests** using Cosign's keyless GitHub OIDC identity and verifies each signature before completing publication. It also signs `SHA256SUMS`, covering the release archives, and publishes `SHA256SUMS.sigstore.json`. No long-lived signing key is stored in repository secrets. Signatures and workflow identity are public in Sigstore's transparency log.

Install [Cosign](https://docs.sigstore.dev/cosign/system_config/installation/) using Sigstore's official instructions. After downloading the checksum file, its bundle and the desired archives from the **same release**, verify before extracting/executing:

```sh
version=v0.8.1
identity="https://github.com/andrekuehne/diehl2mqtt/.github/workflows/build.yml@refs/tags/$version"
cosign verify-blob --bundle SHA256SUMS.sigstore.json \
  --certificate-identity "$identity" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com SHA256SUMS
# Check the downloaded archive(s) against the now authenticated checksum file.
sha256sum --ignore-missing -c SHA256SUMS
```

To verify an image, obtain its full `ghcr.io/andrekuehne/diehl2mqtt@sha256:…` digest and use the exact release identity above:

```sh
cosign verify --certificate-identity "$identity" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com "$IMAGE"
```

`IMAGE` must be the full digest reference, not an example placeholder. Main/weekly images use the same workflow identity with `@refs/heads/main` instead of a tag. Home Assistant currently does not enforce these Cosign signatures automatically; verification is a separate consumer check. Native LXC updates still use their existing HTTPS/checksum verification and do not automatically verify the Cosign bundle.

## Local confinement tests

`python3 scripts/test-apparmor.py` needs Docker, AppArmor and passwordless sudo for the AppArmor parser, as provided on CI runners. `--loader docker` instead uses a temporary helper with MAC_ADMIN and a securityfs mount. Both modes load a unique disposable profile, verify bus-directory access and positive libusb enumeration when USB root hubs exist, run real decoder/libusb binaries against public/synthetic data, assert denied shell execution and writes, verify UID/capabilities and health/signals, then remove the profile and test volume. They do not attach USB or contact a production broker. The test helper's privileges are not requested by the installed app.

Actual HAOS USB streaming, host reboot, physical reconnect and updating an existing installation remain destination acceptance checks.
