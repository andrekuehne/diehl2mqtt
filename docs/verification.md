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
