# Diehl HYDRUS water meter implementation plan

This is the complete implementation brief for the next agent. Build a standalone Docker project in `/home/andre/Projects/Watermeter-Docker` that reads the owner's Diehl HYDRUS 2.0 / DME173 water meter through an RTL-SDR, decrypts and decodes readings, emits JSON, and optionally publishes to MQTT with Home Assistant automatic discovery. No earlier conversation or attachment is needed.

Prepared on 12 October 2026. Status: planned; no application implementation, image build, decryption test, or hardware test has been performed as part of creating this plan. The project directory has no existing application. This document is the requirements baseline, and should remain in the finished repository.

## Scope and priorities

Deliver the receiver, MQTT publication, and Home Assistant discovery in the first version. The owner's latest request brings MQTT and discovery into scope and supersedes the original brief's instructions to postpone those features. Keep a mode that requires no broker and emits JSON only. MQTT being optional at runtime does not make its implementation or testing optional.

Implement in this order: reproducible image, secure offline decoding, reliable live reception, MQTT, Home Assistant discovery, deployment and CI. Favor upstream functionality and small scripts. A small MQTT client and supervisor is justified when needed to meet the discovery and reconnect requirements; a separate production bridge service is unnecessary.

Included:

- A multi-stage Docker image with `rtl_sdr`, `rtl_test`, `rtl_wmbus`, and `wmbusmeters`.
- Pinned source builds of `rtl-wmbus` and `wmbusmeters`, configurable revisions, and safe version reporting.
- Runtime-only AES secrets, fixed meter defaults, newline-delimited decoded JSON on stdout, and diagnostics on stderr.
- Hardware-free tests, a runtime-key encrypted telegram test, and mandatory verification with the connected physical dongle and live meter on the owner's computer.
- Optional MQTT publication to an existing broker, authentication, verified TLS, retained readings, availability, and Home Assistant discovery.
- Linux Docker Compose deployment without privileged mode, CI, weekly rebuilds, dependency update procedures, and an operational README.
- Documentation for Ubuntu testing and later Proxmox USB passthrough into a Docker guest.

Excluded:

- Installing or administering the user's production MQTT broker or Home Assistant instance. A disposable test broker is included for automated verification.
- Host module, udev, USB, Proxmox, or network changes performed automatically.
- Multiple meters, dashboards, databases, consumption calculations, leak detection, billing logic, and a custom Home Assistant integration.
- Automatic adoption of arbitrary upstream branch heads, unattended deployment, and mandatory registry publishing.

## Meter and hardware requirements

The owner has manually verified that this hardware and software combination decrypts the meter successfully. Use these image defaults; users must not need to re-enter them:

| Variable | Default | Requirement |
| --- | --- | --- |
| `METER_ID` | `12345678` | Keep as an eight-character decimal string; decode only this ID. |
| `METER_DRIVER` | `dme173` | Verify this driver exists in the selected build. |
| `METER_NAME` | `Water` | Human-readable name; must not determine persistent MQTT identity. |
| `WMBUS_FREQUENCY` | `868.95M` | Approximately 868.95 MHz. |
| `WMBUS_MODE` | `c1` | Wireless M-Bus C1. |

Allow environment overrides, validate them before spawning processes, and reject unsupported values clearly. Treat all configuration as data: avoid `eval`, unchecked shell command interpolation, and newline injection into generated config files. Supporting other meters or modes is not an acceptance requirement.

The USB receiver is an RTL2832U with an R820T or R820T2 tuner, accessed through libusb. The initial host is an Ubuntu laptop. Later deployment is Proxmox host → USB passthrough → Linux Docker VM or suitable LXC → Docker Compose → this container. Do not assume Docker runs on the Proxmox VE host.

The owner confirms that the dongle is connected to this computer, that they hold the AES key and meter ID, and that they have already verified reception and decryption manually. Plan actual local hardware verification as required work, not an optional future exercise. Keep `12345678` as the meter default unless the owner explicitly supplies a different ID. The owner will supply the key through the runtime-only procedure when testing starts; possessing the key does not mean it has already been made available to the agent. Previous manual success establishes a working baseline but does not replace testing this project's image and Compose deployment.

Expected decoded data has this approximate shape; these values are meter readings, not secrets:

```json
{
  "_": "telegram",
  "media": "water",
  "driver": "dme173",
  "name": "Water",
  "id": "12345678",
  "flow_temperature_c": 16.8,
  "target_m3": 0.2,
  "target_datetime": "2026-09-30 23:59",
  "total_m3": 0.252,
  "status": "OK"
}
```

Preserve upstream decoded fields and numeric precision. If the pinned upstream uses another driver identity field, normalize or validate that field explicitly and document the compatibility rule. Do not substitute meter detection for proof of successful decryption.

## Receiver and process design

The required data path is RTL-SDR USB → `rtl_sdr` → `rtl_wmbus` → `wmbusmeters` → AES decryption and `dme173` decoding → JSON stdout and optional MQTT.

Prefer `wmbusmeters` native `rtlwmbus` integration if the pinned binaries reliably start and manage both receiver processes with the required frequency and mode. Otherwise supervise an explicit pipeline. Verify flags using the actual built binaries and source; the illustrative invocation from the original brief is not a verified command.

Upstream currently documents native pipeline management, config-file operation, and MQTT through an external shell publisher. Its generic `rtlwmbus` default uses 868.625 MHz with simultaneous modes; it must not silently replace the requested tuning. See the [wmbusmeters documentation](https://github.com/wmbusmeters/wmbusmeters). Select the runtime form only after checking the pinned implementation. In particular, do not combine a direct 868.95 MHz receiver with a frequency-shift option intended for simultaneous reception at 868.625 MHz.

Use a foreground reader with a runtime-generated protected meter config, so the key is not placed in process arguments. For MQTT, the baseline is one small Python supervisor/client with a pinned Paho MQTT dependency in the same image. It consumes reader JSON, writes validated readings to stdout immediately, and handles the MQTT connection independently. Use a simpler upstream solution only if it demonstrates all the same secret, lifecycle, retry, discovery, and testing behavior. Record that choice in `docs/implementation-notes.md`. The [Paho client documentation](https://eclipse.dev/paho/files/paho.mqtt.python/html/) is the API reference; do not implement the MQTT protocol manually.

Required runtime behavior:

1. Validate config and secrets, verify required executables, and print safe image/source revisions to stderr.
2. Start the receiver and decoder in the foreground under a process arrangement that reaps children and forwards SIGTERM and SIGINT through the whole process tree.
3. Emit exactly one JSON object per line for accepted decoded telegrams, flushing promptly. All startup, version, retry, and shutdown messages go to stderr. Docker Compose logs may add their own prefixes; direct container stdout must remain parseable JSON.
4. Validate meter identity and decoding success before emitting a reading or publishing it. Ignore other meters and malformed output with a safe diagnostic; never turn an undecoded packet into an empty or zero reading.
5. Treat unexpected decoder EOF, decoder exit, or receiver/pipeline failure as a failure of the container. Terminate remaining children and exit non-zero, even if a component unexpectedly exits with status zero. Container restart policy provides recovery.
6. A broker outage must not stop reading, block stdout, or create an unbounded queue. Preserve only the latest accepted state for replay after reconnect; the product is a current-state publisher, not a durable event archive.
7. Stop within the Compose shutdown grace period, publishing offline availability when possible. Test both signals and child cleanup; shell `pipefail` alone does not prove supervision works.
8. Record the last accepted telegram timestamp in runtime storage. Add a gateway `received_at` field in UTC ISO 8601 format to accepted JSON for stdout/MQTT if upstream does not already provide that exact field. Preserve upstream meter timestamps separately. Stamp once on receipt, and never refresh it when replaying cached state.

## Secret handling

No AES key has been supplied. Never search unrelated files or environment variables for credentials, request a key in chat, or create a real secret file without a runtime-provided key.

- Support `METER_AES_KEY` for convenient manual tests and `METER_AES_KEY_FILE` for normal deployment. A nonempty file setting takes precedence. A missing, unreadable, empty, or invalid explicitly configured file is an error; do not silently fall back to the environment key.
- Remove a terminal LF or CRLF from file input, then require exactly 32 hexadecimal characters. Reject whitespace, extra lines, and other invalid content. Do not trim arbitrary content into validity.
- Never print, partially reveal, hash, log, or place the key in command arguments. Disable shell tracing and avoid environment dumps, rendered secret config, verbose upstream modes that expose secrets, and exception messages containing config contents.
- Generate the decoder config only at runtime under a private directory on container tmpfs, using `umask 077`, directory mode 0700, and file mode 0600. Use the pinned upstream's verified config interface. Remove generated files on exit; tmpfs also prevents persistence across container removal or abrupt failure.
- Remove key environment variables from child environments once the private config is created. Document that environment-based Docker secrets are less private than secret files because container metadata may contain supplied environment values. The file mode is the production recommendation.
- Neither build arguments nor build secrets are needed for the meter key. Image layers, build caches, repository files, fixtures, documentation, example env files, CI definitions, logs, and Git history must contain no AES key value.
- Treat MQTT passwords and private TLS client keys similarly. Support password files with precedence over password environment variables, and never include credentials in connection URLs, command arguments, MQTT payloads, or diagnostics.
- `.gitignore` must include `.env`, `.env.local`, `secrets/`, and `*.key`, plus generated private runtime and test output. `.dockerignore` must exclude these and VCS/tool credential directories. Prefer explicit build-context copies; do not rely on Git ignore rules to protect Docker builds.
- `.env.example` contains only nonsecret options and secret file paths. Do not put a fake 32-character AES value anywhere in examples or test fixtures. Secret-validation tests may generate ephemeral values in memory without printing or persisting them.

Compose secrets grant file access inside a container; the local source file still needs host permissions and protection. Follow the [Docker Compose secrets guidance](https://docs.docker.com/compose/how-tos/use-secrets/).

## MQTT configuration and behavior

The following names and defaults are the public configuration contract. Expand the image with MQTT support, but keep `MQTT_ENABLED=false` as the default so an AES key alone remains sufficient for the basic reader. Provide an MQTT Compose override or equally simple documented activation command.

| Variable | Default or rule |
| --- | --- |
| `MQTT_ENABLED` | `false`; accept documented boolean forms and reject other values. |
| `MQTT_HOST` | No default; required when MQTT is enabled. Use a broker reachable from the container. |
| `MQTT_PORT` | `1883` for plaintext, `8883` when TLS is enabled; explicit override allowed. |
| `MQTT_USERNAME` | Optional; empty means no username. |
| `MQTT_PASSWORD` / `MQTT_PASSWORD_FILE` | Optional runtime credentials; configured file takes precedence and fails clearly if unreadable. |
| `MQTT_TLS` | `false`; when enabled require certificate and hostname verification. |
| `MQTT_CA_FILE` | Optional mounted CA file; use system trust if absent. |
| `MQTT_CLIENT_CERT_FILE` / `MQTT_CLIENT_KEY_FILE` | Optional mounted pair for mutual TLS; require both together. |
| `MQTT_TOPIC_PREFIX` | `watermeter`; strip only terminal separators, reject empty roots and wildcards. |
| `MQTT_CLIENT_ID` | Derived default `watermeter_12345678`; derive from overridden meter ID. |
| `HA_DISCOVERY_ENABLED` | `true` when MQTT is enabled; ineffective when MQTT is disabled. |
| `HA_DISCOVERY_PREFIX` | `homeassistant`. |
| `HA_STATUS_TOPIC` | `homeassistant/status`; configurable independently of discovery prefix. |

Use MQTT 3.1.1 initially, QoS 1 for state, discovery, and availability, a 60-second keepalive, and reconnect backoff bounded between 1 and 60 seconds. Keep these as documented implementation constants unless exposing them is necessary. Configure a retained offline last will before connecting. Do not introduce an insecure TLS bypass.

For the default meter, publish:

| Topic | Payload | Retained |
| --- | --- | --- |
| `watermeter/12345678/state` | Accepted decoded JSON object, including original measurement fields. | Yes |
| `watermeter/12345678/availability` | `online` or `offline`. | Yes |

Derive the topic meter segment from `METER_ID`; changing the friendly name must not change topics or unique IDs. Use a distinct client ID per running publisher and document that two containers for the same meter require an explicit client-ID override.

After a successful connection: subscribe to the Home Assistant status topic if discovery is enabled, publish discovery, replay the latest accepted state if one exists in memory, then announce online once the receiver process tree is alive. Check publish results and acknowledgements without blocking the decoder loop. Resend discovery and cached state on reconnect and on an `online` Home Assistant birth message. Suppress repeated identical configuration messages during normal reading. There is no state publication before the first valid decoded reading.

Availability means the receiver service is running and connected to MQTT. It does not assert that the meter has transmitted recently. A disconnected client is handled through its last will; graceful shutdown or reader failure publishes offline with a bounded acknowledgement wait before disconnecting. Do not promise instantaneous offline detection during broker or network failure.

Log connection/authentication/TLS failures safely and retry with bounded memory use. Do not treat transient broker failure as a receiver crash. Report MQTT connection status separately from process health. Last-known retained readings are deliberately historical until replaced; the README must explain this behavior.

Document broker ACLs for publishing the state/availability topics and this device's discovery topics, and subscribing to the configured Home Assistant status topic. Broker credentials, addresses, and Home Assistant access will be provided by the owner at deployment; automated tests use an isolated broker.

## Home Assistant discovery contract

Use one retained sensor discovery message per entity for this first version, with a shared device identifier. This supported format is simple to inspect and remove for three sensors. Device discovery is also supported by Home Assistant, but changing discovery formats is outside the initial implementation. Discovery topic structure, retained configuration, birth messages, and availability are described in the [Home Assistant MQTT documentation](https://www.home-assistant.io/integrations/mqtt/).

| Reading | Discovery topic under `homeassistant/sensor/` | `unique_id` | Unit | Device class | State class |
| --- | --- | --- | --- | --- | --- |
| `total_m3` | `diehl_hydrus_12345678_total_m3/config` | `diehl_hydrus_12345678_total_m3` | `m³` | `water` | `total_increasing` |
| `flow_temperature_c` | `diehl_hydrus_12345678_flow_temperature_c/config` | `diehl_hydrus_12345678_flow_temperature_c` | `°C` | `temperature` | `measurement` |
| `status` | `diehl_hydrus_12345678_status/config` | `diehl_hydrus_12345678_status` | None | None | None |

All three use `watermeter/12345678/state` and `watermeter/12345678/availability`, adjusted for configured prefixes/ID. Device metadata: identifiers `["diehl_hydrus_12345678"]`, manufacturer `Diehl Metering`, model `HYDRUS 2.0 / DME173`, and device name from `METER_NAME`. Mark status as a diagnostic entity. Software revision metadata, if included, must describe the reader software without implying it is the meter firmware.

Generate discovery payloads as structured JSON. Include a human-readable entity name, stable `unique_id`, state topic, extraction template, availability topic and payload values, QoS, and shared device metadata. IDs must be deterministic across application restarts, source upgrades, container recreation, and friendly-name changes. No hand-written Home Assistant sensor YAML should be needed after the MQTT integration is configured.

For numeric sensors, use templates such as `{{ value_json.get('total_m3') }}` so absent/null values become unknown rather than zero. Preserve missing status as unknown. Validate finite numeric measurements before publishing; JSON NaN/Infinity and malformed values must not reach statistical sensors. The [MQTT sensor reference](https://www.home-assistant.io/integrations/sensor.mqtt/) specifies templates, unknown numeric states, and discovery properties.

Publish absolute `total_m3`, never a computed delta. Repeated telegrams must not increment consumption. Do not add rounding, offsets, or reset heuristics. The cumulative water sensor should be eligible for Home Assistant water usage statistics; verify the pinned implementation's output meets the [sensor state-class rules](https://developers.home-assistant.io/docs/core/entity/sensor/) and [water usage integration requirements](https://www.home-assistant.io/docs/energy/water/).

Leave `target_m3` and `target_datetime` in state JSON without creating initial discovery entities; their period/time semantics do not need to be assumed. Do not configure `expire_after` until the actual transmission interval is established. Explain how users distinguish old retained data from new reception using timestamps and status diagnostics.

Document removal by publishing zero-length retained payloads to the exact three discovery topics, and clearing state/availability if retiring a device. Never clear a broad wildcard namespace. Changing an ID or topic prefix requires cleaning up old retained topics. Normal stop must keep discovery configuration so entities survive restarts.

## Image and deployment requirements

Use mainstream Debian or Ubuntu slim with glibc and a multi-stage build. Install only dependencies established from current build instructions and actual build results. Likely candidates are a C/C++ toolchain, Git, pkg-config, libusb/librtlsdr headers, and any required autoconf, automake, or XML development packages; this is not an authoritative package list.

Build from these required upstreams:

- [xaelsouth rtl-wmbus](https://github.com/xaelsouth/rtl-wmbus).
- [wmbusmeters](https://github.com/wmbusmeters/wmbusmeters).

The distro's rtl-sdr/librtlsdr packages may provide `rtl_sdr` and `rtl_test`. Runtime must include all four required binaries, their shared libraries, CA certificates for MQTT TLS, and only the extra runtime needed for the chosen client. Avoid installing a daemon or systemd service in the container. Include required upstream license notices and source provenance when distributing the image.

Expose `RTL_WMBUS_REF` and `WMBUSMETERS_REF` build arguments with checked-in pinned defaults. Prefer useful stable tags; otherwise select full commit hashes. Record resolved commit hashes even when tags are used, plus base-image identity and client dependency versions in an image version file and appropriate OCI labels. Normal builds must not default to unpinned `main`/`master`. Describe rebuilds as repeatable from pinned application sources; base refreshes and distro package updates can still change the resulting image.

Compose requirements:

- Service name `watermeter`, `restart: unless-stopped`, sensible log rotation, and an explicit stop grace period, initially 20 seconds.
- Secret file mapping `./secrets/meter_aes_key` → `/run/secrets/meter_aes_key`, with `METER_AES_KEY_FILE` set to that container path. No committed secret file or literal key. Keep `compose.mqtt.yaml` usable for an anonymous test broker without a password file. Supply a small additional authentication override or documented Compose secret snippet for password-protected brokers; set `MQTT_PASSWORD_FILE` only when that secret is actually mounted. Neither JSON-only nor anonymous MQTT deployment may require an unused password file.
- Mount `/dev/bus/usb:/dev/bus/usb` and apply `device_cgroup_rules: ['c 189:* rmw']`; verify this actually works on the target Linux Docker setup. Never require a changing `/dev/bus/usb/001/004` path. Do not add `privileged: true` as the normal solution.
- Mount private runtime directories as tmpfs. Prefer a non-root container user with verified USB access and supplemental host groups where practical; document any narrower limitation that requires container root. Do not compensate with world-writable USB permissions.
- Consider `no-new-privileges` and dropping unused capabilities when verified compatible. Do not sacrifice working USB access to untested hardening settings.
- The healthcheck reports the supervised reader/process tree state. Do not launch `rtl_test` from the healthcheck because it would compete with the live reader. A dead process is a failure even if a PID file remains. A short absence of telegrams is not a health failure; MQTT connectivity and last reception age are separate diagnostics.

Explain that rootless Docker, LXC device controls, and host node permissions may need additional setup. A `/dev/bus/usb` mount and cgroup allow rule do not override Unix permissions. Document the broader access granted to USB major 189 and the expected reconnect behavior.

## Offline fixture and validation

Commit the following encrypted telegram as `tests/fixtures/dme173_12345678.hex`. It is permitted test data and contains no AES key:

```text
2e44a5117856341263077a010020058e866b032a72d116bb2c979bf7bfed79b69bb6473c943f838b1f807f26e4e85a
```

With the correct runtime key, the owner observed driver `dme173`, ID `12345678`, and approximately temperature 16.8 °C, total volume 0.252 m³, and status `OK`.

`scripts/test-offline.sh` must decode this fixture inside the built image without USB access or an MQTT broker. Use the same key-loading and private-config code as live operation, with the verified upstream offline-input interface and a finite timeout. A successful test requires parseable JSON, correct meter ID and driver, and evidence of decrypted measurement data, including a finite numeric `total_m3`. Do not accept a header-only JSON result as successful decryption. Use tolerant checks only where needed to distinguish successful decoding; exact field sets, temperatures, target dates, and status wording are not permanent golden-output assertions.

Failure cases: missing/invalid key, wrong runtime key, corrupted telegram, wrong configured ID or driver, malformed JSON, no output, or timeout. Do not commit a key to make negative tests possible. Generate temporary test values at runtime and keep all diagnostics free of their contents. The supplied fixture test explicitly uses the fixed original ID and driver even if live environment overrides exist.

## Intended repository deliverables

Adapt names only when the alternative has a clear technical benefit and is reflected in the README. Keep the implementation compact.

```text
.
├── IMPLEMENTATION_PLAN.md
├── Dockerfile
├── compose.yaml
├── compose.mqtt.yaml
├── .dockerignore
├── .gitignore
├── .env.example
├── README.md
├── requirements.txt                 # pinned MQTT dependency if Python is used
├── scripts/
│   ├── entrypoint.sh
│   ├── test-sdr.sh
│   ├── test-offline.sh
│   ├── test-mqtt.sh
│   ├── healthcheck.sh
│   └── check-updates.sh
├── src/                            # small supervisor/client if needed
├── tests/
│   ├── fixtures/dme173_12345678.hex
│   ├── fixtures/reading.json        # synthetic decoded measurements, no key
│   └── ...                         # config, lifecycle, MQTT and discovery tests
├── docs/
│   ├── implementation-notes.md
│   └── verification.md
└── .github/
    ├── dependabot.yml
    └── workflows/build.yml
```

Do not create a real `secrets/` directory containing a key during scaffolding. A documented directory-creation command is sufficient. Test-only broker configuration may live under `tests/`; no broker belongs in the normal production Compose service graph.

## Work packages and execution order

Every package must leave its outputs reviewable and record commands, outcomes, and limitations in `docs/verification.md` without secret values. Label checks PASS, FAIL, or NOT RUN with a reason. The dongle and owner-held key are planned inputs to required local verification in WP08. If runtime secret access or hardware access is temporarily unavailable, arrange that access with the owner through the documented safe procedure and continue independent work; do not silently skip hardware acceptance. A missing production broker, remote, or Home Assistant instance is a separate external validation dependency, not evidence of a pass. State briefly what each major step verified.

### WP01 Inspect upstream and select the runtime approach

Dependencies: none.

Steps:

1. Check relevant repository guidance and local Docker/Compose availability without inspecting unrelated credentials. Do not assume a configured Git remote or registry.
2. Inspect current upstream READMEs, build files, releases/tags, native SDR device handling, meter config, `dme173`, offline input, and MQTT capabilities.
3. Select pinned source revisions and a glibc slim base. List actual build and runtime dependencies, architecture support, and a candidate native receiver form.
4. Write `docs/implementation-notes.md` with source references, version choices, private-config design, and MQTT client rationale. Revisit CLI decisions after binaries exist.

Definition of Done: both source revisions and base choice are concrete; dependencies and risks are recorded; the native-versus-explicit receiver decision has a testable criterion; no command syntax is presented as verified solely because it appeared in a tutorial or this plan.

### WP02 Build and verify the container image

Dependencies: WP01.

Steps:

1. Create ignores before Docker context copying. Add a minimal multi-stage Dockerfile and pinned dependency inputs.
2. Build the image locally, fix real dependency/linking/build failures, and inspect required executables and dynamic libraries.
3. Run each executable's supported safe help/version or smoke command without hardware. Verify the configured driver, native device options, offline input, config-file location, and stderr logging against the installed build.
4. Record resolved revisions and licenses; add startup version reporting that cannot expose runtime secrets.

Definition of Done: an amd64 image builds successfully without secrets; all four binaries run without missing shared libraries; pinned revisions can be overridden intentionally and are recorded accurately; no compilers/source tree are carried into runtime without a reason.

### WP03 Implement runtime secrets and offline decoding

Dependencies: WP02.

Steps:

1. Implement common settings validation, key precedence, protected tmpfs config creation, safe errors, and cleanup.
2. Add the exact encrypted fixture and offline script using the built image and verified syntax.
3. Test validation and failure paths without hardware. Arrange owner-assisted runtime key input and run actual decryption of the supplied encrypted fixture. If key input cannot happen yet, record this check as pending and carry it forward as a required prerequisite of WP08.
4. Check logs, arguments, environment propagation, build context, and generated files for unintended secret exposure without printing or hashing a secret during the check.

Definition of Done: missing/malformed keys and broken file precedence fail safely; offline decode has a bounded timeout and structural/identity/measurement checks; the owner's runtime-provided correct key produces real decrypted JSON. This package's decryption acceptance remains incomplete until that check passes. No key value is stored in the repository, image, or test output.

### WP04 Implement and test live receiver supervision

Dependencies: WP03.

Steps:

1. Implement the verified native `rtlwmbus` receiver at the requested tuning/mode; use an explicit supervised pipeline if native behavior fails the criteria.
2. Keep stdout clean, implement process/EOF failure detection and signal propagation, and add receive timestamps and a process healthcheck.
3. Exercise lifecycle cases with controlled fake child processes, including no telegrams, reader crash, receiver crash, SIGTERM, SIGINT, and startup failure.
4. Add the USB test script and prepare the container USB/live commands for mandatory physical verification in WP08. Perform early hardware checks where useful; do not run `rtl_test` while the reader owns the dongle.

Definition of Done: all supervision tests pass, failure exits non-zero and leaves no child processes, intentional shutdown completes within the grace period, and silence alone is healthy. The USB/live test interface is ready, and real C1 reception remains a required acceptance check in WP08 rather than being inferred from simulated process tests.

### WP05 Implement MQTT publication and discovery

Dependencies: WP04; hardware-free MQTT work need not wait for physical reception.

Steps:

1. Add the MQTT settings, protected password handling, authentication, TLS trust/client certificates, last will, QoS 1, and bounded reconnect logic.
2. Publish validated readings and stdout independently, with latest-state caching rather than an unlimited offline backlog.
3. Generate the three discovery payloads and shared device metadata from the contract above. Support discovery disabled independently of MQTT.
4. Implement discovery/state replay on connection and Home Assistant birth, plus bounded graceful offline publication and client shutdown.

Definition of Done: JSON-only mode works without broker settings or network attempts; MQTT mode publishes correct retained JSON and availability; all three discovery entities have stable IDs and correct semantics; invalid measurements never become fabricated consumption. Secrets cannot appear in messages or exceptions. Broker outage does not interrupt decoding or stdout.

### WP06 Verify MQTT and Home Assistant behavior

Dependencies: WP05.

Steps:

1. Run an isolated disposable Mosquitto broker and the same production publication path with synthetic decoded readings. The encrypted fixture remains a separate test requiring the owner's key.
2. Test retained state/config via a newly connected subscriber, QoS acknowledgement, reconnect after initial broker absence and later restart, birth-message replay, graceful offline, abrupt death/last will, and client-ID behavior.
3. Test disabled discovery, nondefault prefixes/ID/name, missing/null/invalid fields, duplicate readings, password-file precedence, rejected authentication, trusted/untrusted TLS, and hostname mismatch. Exercise the production boundary, not just JSON construction helpers.
4. Validate discovery payloads against official schema/documentation. On an owner-provided Home Assistant instance, verify one device with three sensors, restart stability, availability, units, and cumulative water statistics eligibility. Do not create a production installation merely to perform this check.

Definition of Done: automated broker integration and failure tests pass without SDR/AES credentials and clean up containers/networks. Actual Home Assistant validation has evidence, or is explicitly pending with exact manual steps. Schema checks alone are not described as a successful Home Assistant UI test.

### WP07 Finish Compose and host deployment instructions

Dependencies: WP04 and WP05.

Steps:

1. Create the base secret/USB Compose deployment and optional MQTT override, log rotation, tmpfs, shutdown settings, and tested healthcheck.
2. Validate both Compose configurations and test commands for one-off offline and SDR checks without inadvertently starting another reader or requiring unrelated secrets.
3. Test USB access without privileged mode, document host permissions and reconnect behavior, and provide optional hardening only after verification.
4. Explain Ubuntu DVB conflicts and each Proxmox passthrough layer without changing the host.

Definition of Done: the base deployment needs only the AES secret; MQTT deployment needs a reachable broker and any required credentials; Compose builds, starts, logs, stops, and restarts as documented. No fixed USB bus/device address or default privileged service exists. The final physical-host and live Compose checks are performed in WP08.

### WP08 Verify the connected dongle and live meter

Dependencies: WP03 through WP07. Run on the owner's computer, outside hardware-free CI. The dongle is already connected and the owner holds the known-working key and meter ID.

Steps:

1. Establish safe runtime secret input with the owner using the implemented hidden-input procedure or an explicitly identified protected secret file. Do not ask for the key in chat, search for it, or put it in a tool argument. Confirm the nonsecret meter ID against the configured default. Stop only this project's reader before exclusive SDR checks; if another application owns the dongle, identify it and arrange its release without killing unrelated processes automatically.
2. Check host USB visibility with `lsusb` and host SDR access with `rtl_test -t` when available. Run the image's SDR visibility test against the physical dongle without privileged mode. Record the actual device/tuner and permission results. Diagnose failures before proceeding; do not change host kernel modules or USB permissions automatically.
3. Run the encrypted fixture test inside the built image with the runtime-provided key and require correct ID/driver plus genuine decrypted measurement data before starting live acceptance.
4. Start the real receiver in JSON-only mode at `868.95M`, C1, using this project's image. Use a bounded observation window, initially 15 minutes, and record its duration; this is a test timeout, not an assumed transmission interval or health threshold. Require at least one newly received, successfully decrypted telegram for the configured meter, with finite `total_m3` and valid JSON stdout. Historical example values such as 0.252 m³ are not expected live values. Extend the observation window based on observed or owner-supplied transmission timing if needed; a timeout is not a pass.
5. Stop cleanly, start through the final Compose configuration, and require a new valid live reading after startup. Verify graceful shutdown releases the dongle and that a subsequent restart receives again. Observe repeated reception when timing permits. If practical, test physical unplug/replug recovery with the owner's participation; record this additional result separately from mandatory startup/restart checks.
6. Enable MQTT and prove a newly received physical-meter reading reaches a subscriber through the production publication path. Use an isolated local test broker if production broker access has not been supplied. Check that ID, measurement values, and `received_at` match the live JSON, and that discovery and availability accompany the state. Synthetic readings and cached retained messages do not satisfy this live check.
7. Record image/source versions, safe commands, host/container USB results, observation windows, reception times, decoded nonsecret field checks, restart behavior, and live MQTT evidence in `docs/verification.md`. Clean up test containers and runtime secrets as appropriate. If a check fails, fix and rerun the affected path; report any required owner action precisely.

Definition of Done: the physical dongle is accessible inside the nonprivileged container; the supplied fixture decrypts with the owner's runtime key; a real live telegram for the configured meter decodes through the image and final Compose deployment; reception resumes after a clean stop/restart; and a newly received live reading is observed through MQTT. Safe evidence is recorded and no AES value is exposed. Hardware acceptance cannot be marked complete using only mocks, fixture replay, the owner's earlier manual test, or a NOT RUN entry. Production Home Assistant UI verification may remain separately pending if access is unavailable.

### WP09 Add CI and reviewed updates

Dependencies: WP02 through WP07 automated checks.

Steps:

1. Add GitHub Actions for PR/push/manual builds using BuildKit/buildx and cache, at least amd64, with binaries/version, settings/security, lifecycle, and hardware-free broker/discovery tests.
2. Allow encrypted fixture decoding only in a trusted execution context when an optional GitHub Actions AES secret is configured. Reference the secret by name; never store its value or pass it to an image build. Skip clearly when absent. Never expose it to untrusted PR code or `pull_request_target` execution of PR code.
3. Support GHCR publishing only from an appropriate trusted event with required package permissions, and no push for PRs. Local builds and tests must not require GHCR. Add arm64 only if it can actually be built and smoke-tested with little additional complexity.
4. Schedule a weekly rebuild with current pinned application revisions and a pulled base image. Ensure the schedule reruns actual build/test steps; application build cache must not silently hide build breakage. Digest-pinned bases need a reviewed digest-update path.
5. Configure Dependabot for Docker and Actions where practical, and add a read-only update checker or exact procedure covering upstream tags/commits, base-image refresh, and the MQTT dependency. Propose reviewed updates; do not auto-track branch heads.

Definition of Done: CI definitions validate and all locally runnable checks pass; no hardware is required in default CI; encrypted decode skips cleanly without a secret; weekly runs refresh the base as configured and exercise builds/tests; publication permissions and events are constrained. Real hosted CI/GHCR results are only claimed after execution in a configured repository.

### WP10 Finish documentation and perform acceptance review

Dependencies: all prior packages.

Steps:

1. Write the README for an owner starting on Ubuntu with this repository alone. Cover purpose, architecture, defaults, build, secret setup, offline/live tests, USB permissions, DVB troubleshooting, Compose, logs, health, MQTT/TLS/ACLs, Home Assistant discovery/removal, updates, CI/GHCR, and Proxmox guest deployment.
2. Provide exact working commands from the implemented interface for build, offline decode, SDR visibility, live foreground run, JSON-only Compose, MQTT Compose, logs, stop, cleanup, and version updates. Use image/service names consistently.
3. Run the complete relevant test sequence once after final changes, and check the file tree, build context, security requirements, and README commands. Repeat tests only when changes or failures justify it.
4. Complete `docs/verification.md` with versions, commands, safe outcomes, and remaining external checks. Summarize the same limitations in the final handoff.

Definition of Done: a new agent or operator can reproduce the build and run tests using only repository documentation; every included feature has implementation and evidence; no external validation dependency is mislabeled as passed; the final response includes the file tree, exact operational/update commands, and outstanding host requirements.

## Required test coverage

Use targeted tests for behavior with meaningful failure risks. Avoid a large framework or tests that merely mirror formatting logic.

| Area | Required evidence |
| --- | --- |
| Image | Real amd64 build, binaries execute, libraries resolve, driver available, revisions recorded. |
| Key handling | Absent, wrong length, nonhex, newline, CRLF, extra whitespace, file precedence, invalid file, private permissions, no key in logs/arguments/artifacts. |
| Offline decoding | Exact encrypted fixture, required success using the owner's runtime-provided key, failure on wrong key/ID/driver/corruption, bounded timeout, real measurements. |
| Lifecycle | SIGTERM/SIGINT forwarding, no orphans, EOF and component death, safe startup failure, silence remains healthy. |
| JSON output | Only accepted configured meter, one valid object per line, diagnostics separate, flush during broker outage. |
| MQTT | Disabled mode, authentication and TLS failures, retained payloads, acknowledgements, initial outage, restart/reconnect, bounded queue, last will and graceful offline. |
| Discovery | Three correct configs, stable IDs, name/prefix/ID overrides, shared device, HA birth replay, missing values, exact-topic removal instructions. |
| USB and live | Mandatory WP08: host/container dongle access, runtime-key fixture decode, actual live C1 decoded telegram through image and Compose, stop/restart reception, and live MQTT observation; physical unplug/replug recovery when practical. |
| Operations | Both Compose variants, shutdown/restart, log rotation, process healthcheck, copy-pasteable documentation. |
| CI and updates | Hardware-free jobs, absent-secret skip, trusted secret use, publication restrictions, weekly base refresh and rebuild, reviewed update path. |

## Owner procedures to include in the README

Use these safe patterns and fill in the exact implemented test/run commands. Never ask users to type the key directly into a command line or publish it in chat.

For temporary environment-based tests:

```bash
read -rsp "AES key: " METER_AES_KEY; echo
export METER_AES_KEY
# Run the documented offline or live test; pass the variable by name to Docker.
unset METER_AES_KEY
```

For production, document an equally safe hidden-input procedure that writes the runtime-provided key to `./secrets/meter_aes_key` under restrictive host permissions. Do not generate a sample secret as part of the repository. Explain local Compose secret-file limitations and never ask the owner to commit this file.

Host troubleshooting must include `lsusb`, `rtl_test -t`, checking whether `dvb_usb_rtl28xxu`, `rtl2832`, or `rtl2830` claim the device, and exact optional temporary unload/persistent blacklist instructions. Explain the impact of changing modules on other DVB uses, and the undo procedure. Instructions are for the owner to execute; the agent must not modify host modules automatically. Describe VM USB passthrough and LXC's additional device/permission constraints separately.

Home Assistant setup must explain adding/configuring its MQTT integration against the same broker, enabling discovery, locating the Diehl device and sensors, checking total-volume statistics eligibility, broker reachability from Docker, and retained-topic cleanup. Do not assume `localhost` inside the container reaches the host broker. Production broker/HA details are optional inputs for manual acceptance, not blockers for building and testing the software.

## Final Definition of Done

Implementation is complete when all included deliverables exist, the actual image and hardware-free tests pass, mandatory local hardware verification in WP08 passes, the README commands match the tested implementation, and the requirements in the MQTT/discovery/security contracts are met. File generation alone does not satisfy this plan.

Production deployment acceptance additionally requires a live decoded reading to reach the owner's selected broker and Home Assistant to discover the three sensors with correct units and persistent identity. A local test broker can complete WP08 but cannot establish production broker or Home Assistant UI acceptance. If access is unavailable, finish independent work and explicitly report the remaining checks as pending. Required local hardware verification also remains incomplete if runtime key or dongle access cannot be established; do not downgrade it to optional work or claim end-to-end success until the required observations exist.

The final implementation handoff must contain:

- Final file tree and actual image/source versions.
- Exact Docker build, offline decode, SDR check, live reader, JSON-only/MQTT Compose, logs, stop, and cleanup commands.
- Exact procedure for checking and reviewing upstream/base/client dependency updates.
- Test results with any unavailable AES/USB/MQTT/Home Assistant/CI checks identified individually.
- Remaining host USB, permission, kernel-driver, or Proxmox guest requirements, with no secret values.
