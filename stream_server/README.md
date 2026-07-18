# Stremio Stream Engine

Runs the open-source `perpetus/stream-server` engine locally on Home Assistant OS or Supervised installations.

It exposes the Stremio-compatible API on port `11470` for use by the **Stremio Stream Bridge** custom integration.

The first installation builds the Rust server locally for the selected architecture. Raspberry Pi 5 uses the `aarch64` build and PCs use `amd64`.
