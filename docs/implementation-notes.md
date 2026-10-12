# Implementation decisions (WP01)

Inspected upstream on 2026-10-12. Application sources are pinned to full commits:

- wmbusmeters 3.0.0: `ac4f295369a48ef51cb835e6920b62cbee743bd6` (GPL-3.0-or-later).
- xaelsouth rtl-wmbus 1.1.0: `34684e655df70867ac86e799561ec6512c45be0a` (BSD-2-Clause notice in README).
- Base: Debian bookworm-slim, glibc. Its mutable tag intentionally permits reviewed/security rebuilds; application sources stay fixed. Distro package updates mean builds are repeatable from pinned source, not byte-identical.
- Python Paho MQTT 2.1.0, MQTT 3.1.1, callback API v2.

Upstream references: [build/config/CLI](https://github.com/wmbusmeters/wmbusmeters/tree/3.0.0), [SDR implementation](https://github.com/wmbusmeters/wmbusmeters/blob/3.0.0/src/wmbus_rtlwmbus.cc), [rtl-wmbus build and options](https://github.com/xaelsouth/rtl-wmbus/tree/1.1.0), [Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html), [HA sensors](https://www.home-assistant.io/integrations/sensor.mqtt/), [HA discovery](https://www.home-assistant.io/integrations/mqtt/), [water](https://www.home-assistant.io/docs/energy/water/).

The selected decoder's configure requires pkg-config, C++, libxml2-dev, librtlsdr-dev and libusb-1.0-0-dev. rtl-wmbus is plain C linked to libm. Builder additionally needs make, git and CA certificates. Runtime uses libstdc++6, libxml2, librtlsdr0, libusb-1.0-0, distro rtl-sdr utilities, Python 3, Paho, tini and trust certificates. No build toolchain or source checkout enters runtime. Licenses, commit IDs, base tag, distro package versions and client version are copied into the image. Initial supported build target is linux/amd64; arm64 is not claimed tested.

Native integration correctly omits rtl_wmbus -s when an explicit frequency is supplied, but creates a shell pipeline and background tail process. Its health cannot prove each pipe member remains alive. We choose the plan's explicit-pipeline fallback: the Python supervisor owns and monitors rtl_sdr, rtl_wmbus and wmbusmeters separately, forwards signals to their sessions, and fails on any member exit or decoder EOF. This criterion is exercised with controlled processes. rtl_sdr uses 868.95M at 1600000 samples/s; rtl_wmbus receives no frequency shift. Decoder filters c1 and the exact meter ID. The demodulator decodes T1/C1 together upstream; c1 selects the meter link mode. There is no automatic retuning/detection.

The decoder runs foreground with --useconfig=<private-directory>. Config contains device=stdin:rtlwmbus (live) or stdin:hex (offline), format=json, loglevel=normal, nonet=true, and one meter file. No AES value is passed in argv. stderr is filtered rather than forwarded verbatim, guarding even upstream config errors. Config directory is 0700 and files 0600 on /run/watermeter tmpfs. Sensitive environment variables are removed before children start. Decoder 3.0.0 emits meter=dme173: retain that original field and add/validate driver=dme173 explicitly.

Paho is a small in-process client rather than upstream's shell publisher: it supplies independently reconnecting TLS/auth, retained last will, birth replay, acknowledgements and bounded latest-state caching. The decoder loop never waits for network I/O. A worker owns MQTT publication; at most one state is pending in memory and Paho's queued/inflight messages are bounded. One payload per HA sensor preserves the exact stable discovery identities in the plan.

Docker/Compose were absent at inspection. Host USB inspection found no supported SDR. These are acceptance dependencies, not reasons to describe source-only tests as an image/hardware pass. See verification.md.
