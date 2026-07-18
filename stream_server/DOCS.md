# Stremio Stream Engine

This app provides a local torrent streaming backend for **Stremio Stream Bridge**. It is based on the MIT-licensed [`perpetus/stream-server`](https://github.com/perpetus/stream-server) project and uses the upstream-supported `libtorrent` backend.

## Installation

1. Add this repository to the Home Assistant app store:
   `https://github.com/diegocesaretti/stream-server-ha`
2. Install **Stremio Stream Engine**.
3. Keep TCP port `11470` mapped to `11470`.
4. Start the app and enable **Start on boot** and **Watchdog**.
5. Open the app logs and confirm that the server is listening on port `11470`.

The first installation builds the Rust binary locally. On a Raspberry Pi this can take substantially longer than installing a prebuilt image.

## Connect Stremio Stream Bridge

Open:

**Settings → Devices & services → Stremio Stream Bridge → Configure**

Set **stream-server URL** to:

```text
http://HOME_ASSISTANT_IP:11470
```

Use the real LAN IP of the Raspberry Pi, not `localhost` and not the internal app hostname. Chromecast must be able to open that address directly.

Examples:

```text
http://192.168.1.50:11470
http://homeassistant.local:11470
```

An IP address is usually more reliable for Cast devices.

## Switching between local and external engines

The integration remains compatible with an external PC server. Change only the configured server URL:

- Local Raspberry Pi engine: `http://HOME_ASSISTANT_IP:11470`
- External PC engine: `http://PC_IP:11470`

All catalog, provider, subtitle, quality, fallback and Cast settings remain unchanged.

## Storage

The app stores its configuration and cache below `/data`, which Home Assistant includes with the app's persistent data and backups.

## Performance

Direct Cast playback does not use the Raspberry Pi GPU. CPU and memory use should stay low after torrent metadata has been resolved. Network and storage throughput are the main resources used.

Real-time transcoding through FFmpeg is available in the upstream engine but is not the recommended default on Raspberry Pi. Keep **Audio compatibility** set to `direct` unless a source specifically requires transcoding.

## Troubleshooting

### Integration cannot connect

- Confirm that the app is running.
- Open `http://HOME_ASSISTANT_IP:11470/heartbeat` from another device on the LAN.
- Verify that port `11470` is not used by another service.
- Do not configure the integration with `127.0.0.1`; Cast devices cannot reach that address on Home Assistant.

### Cast starts but video does not play

Use the integration's source fallback and Cast compatibility filter. Prefer MP4, H.264 and AAC sources. MKV, HEVC, DTS and multichannel audio may still be unsupported by the receiver.

### Build fails during installation

The initial version builds upstream source locally. Check free disk space and memory, then inspect the Supervisor build log. A later release can replace this with prebuilt multi-architecture container images.

## Legal

Use torrent and streaming providers only for media you are authorized to access and reproduce.
