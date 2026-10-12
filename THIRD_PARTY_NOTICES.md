# Third-party software

The image builds unmodified upstream software with pinned provenance:

- wmbusmeters 3.0.0, ac4f295369a48ef51cb835e6920b62cbee743bd6: GPL-3.0-or-later. https://github.com/wmbusmeters/wmbusmeters
- xaelsouth rtl-wmbus 1.1.0, 34684e655df70867ac86e799561ec6512c45be0a: BSD-2-Clause; copyright and full notice in upstream README. https://github.com/xaelsouth/rtl-wmbus
- Eclipse Paho MQTT Python 2.1.0: EPL-2.0 / EDL-1.0 distribution notices included in wheel. https://github.com/eclipse-paho/paho.mqtt.python
- Debian rtl-sdr/libusb and other runtime packages: package metadata/individual distribution licenses apply.

Upstream notices are copied into /usr/share/watermeter/licenses and resolved source/base/client versions into /usr/share/watermeter/versions.txt. Runtime Debian packages are enumerated in packages.txt. Redistributors must satisfy corresponding-source obligations for covered binaries and carry applicable notices. Preserve this repository's Dockerfile, dependency pins and build instructions alongside corresponding upstream source when distributing.
