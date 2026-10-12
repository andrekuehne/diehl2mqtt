# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=debian:bookworm-slim
FROM ${BASE_IMAGE} AS build
ARG BASE_IMAGE
ARG RTL_WMBUS_REF=34684e655df70867ac86e799561ec6512c45be0a
ARG WMBUSMETERS_REF=ac4f295369a48ef51cb835e6920b62cbee743bd6
ARG BUILD_JOBS=4
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ca-certificates pkg-config libxml2-dev librtlsdr-dev \
    libusb-1.0-0-dev python3-venv && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git init rtl && cd rtl && git remote add origin https://github.com/xaelsouth/rtl-wmbus.git \
    && git fetch --depth 1 origin "$RTL_WMBUS_REF" && git checkout --detach FETCH_HEAD \
    && make release
RUN git init meters && cd meters && git remote add origin https://github.com/wmbusmeters/wmbusmeters.git \
    && git fetch --depth 1 origin "$WMBUSMETERS_REF" && git checkout --detach FETCH_HEAD \
    && ./configure && make -j"$BUILD_JOBS"
COPY requirements.txt /build/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.txt
RUN mkdir -p /provenance/licenses \
    && cp meters/LICENSE /provenance/licenses/wmbusmeters.txt \
    && cp rtl/README.md /provenance/licenses/rtl-wmbus.txt \
    && cp /opt/venv/lib/python*/site-packages/paho_mqtt-*.dist-info/licenses/* /provenance/licenses/ \
    && printf 'base=%s\nrtl_wmbus_ref=%s\nrtl_wmbus_commit=%s\nwmbusmeters_ref=%s\nwmbusmeters_commit=%s\npaho_mqtt=2.1.0\n' \
        "$BASE_IMAGE" "$RTL_WMBUS_REF" "$(git -C rtl rev-parse HEAD)" \
        "$WMBUSMETERS_REF" "$(git -C meters rev-parse HEAD)" > /provenance/versions.txt

FROM ${BASE_IMAGE} AS runtime
ARG BASE_IMAGE
ARG RTL_WMBUS_REF=34684e655df70867ac86e799561ec6512c45be0a
ARG WMBUSMETERS_REF=ac4f295369a48ef51cb835e6920b62cbee743bd6
LABEL org.opencontainers.image.title="Diehl HYDRUS water meter reader" \
      org.opencontainers.image.description="RTL-SDR C1 decoder with optional MQTT and Home Assistant discovery" \
      org.opencontainers.image.base.name="${BASE_IMAGE}" \
      io.watermeter.rtl-wmbus.ref="${RTL_WMBUS_REF}" \
      io.watermeter.wmbusmeters.ref="${WMBUSMETERS_REF}"
RUN apt-get update && apt-get install -y --no-install-recommends \
    rtl-sdr libstdc++6 libxml2 librtlsdr0 libusb-1.0-0 ca-certificates python3 tini \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/watermeter && chmod 700 /run/watermeter
COPY --from=build /build/rtl/build/rtl_wmbus /usr/local/bin/rtl_wmbus
COPY --from=build /build/meters/build/wmbusmeters /usr/local/bin/wmbusmeters
COPY --from=build /opt/venv /opt/venv
COPY --from=build /provenance /usr/share/watermeter
RUN dpkg-query -W > /usr/share/watermeter/packages.txt
COPY src/ /opt/watermeter/
COPY scripts/entrypoint.sh scripts/healthcheck.sh scripts/smoke-image.sh /usr/local/bin/
COPY tests/fixtures/dme173_12345678.hex /usr/share/watermeter/fixture.hex
ENV PATH="/opt/venv/bin:${PATH}" PYTHONPATH=/opt/watermeter PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 METER_ID=12345678 METER_DRIVER=dme173 METER_NAME=Water \
    WMBUS_FREQUENCY=868.95M WMBUS_MODE=c1 MQTT_ENABLED=false
RUN smoke-image.sh
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["healthcheck.sh"]
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["live"]

FROM runtime AS test
RUN apt-get update && apt-get install -y --no-install-recommends mosquitto mosquitto-clients openssl \
    && rm -rf /var/lib/apt/lists/*
COPY tests/ /tests/
WORKDIR /
ENV WATERMETER_TEST_MQTT=1
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

# Keep the default build target as the broker-free production image.
FROM runtime AS final
