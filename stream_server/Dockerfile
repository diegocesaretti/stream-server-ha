ARG BUILD_VERSION
ARG BUILD_ARCH

FROM rust:1.96-bookworm AS builder

ARG STREAM_SERVER_REF=v0.1.8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        clang \
        cmake \
        git \
        libasound2-dev \
        libayatana-appindicator3-dev \
        libgtk-3-dev \
        libssl-dev \
        libxdo-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${STREAM_SERVER_REF}" \
    https://github.com/perpetus/stream-server.git /src

WORKDIR /src

RUN cargo build --locked --release -p server \
    --no-default-features --features librqbit

FROM debian:bookworm-slim

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.name="Stremio Stream Engine" \
    io.hass.description="Local stream-server engine for Stremio Stream Bridge" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.source="https://github.com/diegocesaretti/stream-server-ha" \
    org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        jq \
        libasound2 \
        libayatana-appindicator3-1 \
        libgtk-3-0 \
        libssl3 \
        libxdo3 \
        tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/target/release/server /usr/local/bin/stream-server
COPY --from=builder /src/LICENSE /usr/share/licenses/stream-server/LICENSE
COPY run.sh /run.sh

RUN chmod 0755 /run.sh /usr/local/bin/stream-server \
    && mkdir -p /data/config /data/cache

EXPOSE 11470/tcp

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/run.sh"]
