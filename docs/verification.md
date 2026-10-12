# Verification record

Date: 2026-10-12. No AES key has been provided. No credentials searched.

| Package/check | Result | Evidence / remaining requirement |
| --- | --- | --- |
| WP01 upstream inspection | PASS | Public pinned checkouts inspected under /tmp; full commits and source interfaces recorded in implementation-notes.md. |
| Local Git initialization | PASS | New main repository initialized. |
| Docker and Compose availability | NOT RUN | Neither executable is installed on host; actual image/Compose verification requires Docker Engine and Compose. |
| Initial host USB | FAIL | Host-level lsusb lists hubs/fingerprint/camera/Bluetooth; rtl_test -t reports No supported devices found. No host changes made. |
| WP02 pinned native builds | PASS | Both sources configured/compiled on host in /tmp; versions match full commits. ldd resolves decoder libraries. --listdrivers contains dme173; --listfields=dme173 contains total_m3. rtl_wmbus -V and SDR help execute. |
| WP02 actual amd64 image | NOT RUN | Docker unavailable. Dockerfile has mandatory build-time binary/library/driver/client smoke checks. Host build does not establish Debian runtime or image success. |
| WP03 settings/private files/JSON boundary | PASS | 9 unittest cases pass, including CRLF/LF, strict whitespace, file precedence, 0700/0600 permissions/cleanup, child environment scrubbing, finite numeric fields, identity checks and genuine total-volume requirement. |
| WP03 real decoder negative test | PASS | Exact encrypted fixture with an ephemeral wrong key produces no accepted measurement; no secret printed or retained. |
| WP03 correct-key fixture | NOT RUN | Owner must run scripts/setup-secret.sh locally; never provide key in chat. Required acceptance remains pending. |
| WP03 owner-key native fixture | PASS | Owner explicitly provided protected secrets/meter_aes_key via hidden-input script. Pinned native wmbusmeters decrypted the exact fixture on 2026-10-12 at 09:49:01 UTC: ID 12345678, dme173, finite total_m3=0.252, temperature=16.8, status=OK. All original fields retained. This is a host-source build check; image decode still required. |
| WP04 lifecycle/process health | PASS | 11 total unittest cases pass; lifecycle cases cover each pipe member exiting zero, EOF, startup failure, SIGTERM/SIGINT to all members, no surviving children, silence healthy, JSON-only stdout and reception timestamp. |
| WP04 live hardware | NOT RUN | Awaiting connected SDR and Docker. No physical C1 reception claimed. |
| WP05 publication/discovery implementation | PASS | Optional Paho worker, QoS1 acknowledgements, latest-state cache, retained will/state/discovery, birth replay, verified TLS and exact three sensor contracts implemented. 12 unit/lifecycle cases pass. Broker behavior is verified separately in WP06. |
| WP02 amd64 image build/smoke (updated) | PASS | Owner installed Docker Engine 29.9.0 / Compose 5.6.0 and enabled user access. Debian bookworm image builds; all four binaries and runtime libraries, dme173 and Paho execute in build-time smoke check. Pinned source commits reported inside image. |
| WP03 owner-key image fixture (updated) | PASS | scripts/test-offline.sh with explicitly supplied protected key file decrypted exact fixture inside isolated image with no USB/network on 2026-10-12 at 10:00:49 UTC; correct ID/driver and total_m3=0.252. |
| WP06 real Mosquitto integration | PASS | Six isolated loopback broker scenarios pass: retained state/config and QoS acknowledgements; birth replay and identical readings; graceful offline; abrupt death LWT; 2,000-state outage cache, initial absence and broker restart; disabled discovery/overrides; password-file precedence and rejected authentication; trusted TLS, untrusted CA and hostname mismatch. Test broker 2.0.22 built under /tmp; no production broker installed. |
| WP06 Home Assistant UI/statistics | NOT RUN | Official discovery/sensor contracts checked. Owner's Home Assistant UI still needs one device/three sensors, availability and statistics validation; MQTT evidence alone is not a UI test. |
| WP06 hardware-free image tests | PASS | scripts/test-mqtt.sh builds test target, runs 18 tests inside image with --network none, and exits zero. Disposable Mosquitto runs only on container loopback and cleans up. |
| WP07 Compose configurations | PASS | docker compose config --quiet validates JSON-only, anonymous MQTT and authenticated MQTT combinations. Base uses only meter secret; password secret is confined to auth override. |
| WP07 Compose USB/process deployment | PASS | JSON-only Compose starts nonprivileged, receives new meter telegrams (e.g. 10:05:10 UTC, 3.238 m³) and reports healthy. USB major 189 rule and whole-bus mount work on this host. No fixed USB node or privileged mode. Root container chosen for verified host node access; nonroot/rootless deployments need supplemental permissions and are not claimed tested. |
