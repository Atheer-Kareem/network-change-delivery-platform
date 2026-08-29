FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        snmp=5.9.3+dfsg-2+deb12u1 \
        snmpd=5.9.3+dfsg-2+deb12u1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/ncdp-agent /var/lib/snmp \
    && chmod 0700 /run/ncdp-agent /var/lib/snmp

COPY entrypoint.sh /usr/local/bin/ncdp-synthetic-snmpd

EXPOSE 1161/udp

ENTRYPOINT ["/usr/local/bin/ncdp-synthetic-snmpd"]
