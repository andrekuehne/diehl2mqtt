# Third-party software

The image builds source snapshots with recorded provenance:

- wmbusmeters, b58d96758e71ba7a4c1d9674c7fcd05eb36fceea: GPL-3.0-or-later. https://github.com/wmbusmeters/wmbusmeters
- xaelsouth rtl-wmbus 1.1.0, 34684e655df70867ac86e799561ec6512c45be0a: BSD-2-Clause; copyright and full notice in upstream README. https://github.com/xaelsouth/rtl-wmbus
- andrekuehne rtl-wmbus dev snapshot: BSD-2-Clause; exact commit in versions.txt and source release archive, full notice in licenses/rtl-wmbus-dev.txt. https://github.com/andrekuehne/rtl-wmbus
- Eclipse Paho MQTT Python 2.1.0: EPL-2.0 / EDL-1.0 distribution notices included in wheel. https://github.com/eclipse-paho/paho.mqtt.python
- Debian rtl-sdr/libusb and other runtime packages: package metadata/individual distribution licenses apply.

Upstream notices are copied into /usr/share/watermeter/licenses and resolved source/base/client versions into /usr/share/watermeter/versions.txt. Runtime Debian packages are enumerated in packages.txt. Redistributors must satisfy corresponding-source obligations for covered binaries and carry applicable notices. Preserve this repository's Dockerfile, dependency pins and build instructions alongside corresponding upstream source when distributing.

Versioned GitHub releases attach a native source/build archive containing the exact committed project and exact reference RTL-WMBus, fork dev and wmbusmeters source trees, notices and runtime Debian package versions. Paho and Debian source locations are recorded in that archive's README. The deployment archive and image reference identify the matching binary image by digest. Preserve those materials when redistributing a release.
