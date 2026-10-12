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
