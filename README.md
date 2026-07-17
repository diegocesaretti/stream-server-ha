# Stremio Stream Bridge v0.4.1 for Home Assistant

Custom Home Assistant integration that combines Stremio-compatible catalogs, stream providers and subtitles, then sends the selected media through a Stremio stream-server running on a PC.

## What is new in v0.4.1

- Default PC stream-server URL changed to `http://192.168.1.145:11470`.
- Cinecalidad is preconfigured for the **Latin Audio** profile.
- StremVerse is preconfigured for **F1 and Sports**.
- Optional provider failures no longer block the whole integration setup.
- A temporarily offline PC stream-server no longer prevents the entry from loading; the connectivity sensor shows the exact LAN error.
- Added `stremio_stream_bridge.connection_diagnostics`, which tests each endpoint independently.
- The stream-server URL can now be changed from the integration options.
- Retains borderless subtitles, audio compatibility and direct ideal-link playback from v0.4.0.

## Installation or update

1. Copy `custom_components/stremio_stream_bridge` to `/config/custom_components/`.
2. Replace the existing folder when updating.
3. Restart Home Assistant.
4. Keep the existing config entry; it migrates automatically to version 5.
5. Open **Settings → Devices & services → Stremio Stream Bridge → Configure**.

## Default connection and providers

```text
PC stream-server:
http://192.168.1.145:11470

Catalog and metadata:
https://v3-cinemeta.strem.io/manifest.json

Default streams:
https://torrentio.strem.fun/manifest.json

Subtitles:
https://opensubtitles-v3.strem.io/manifest.json

Latin Audio:
https://cinecalidad-stremio-addon.fly.dev/manifest.json

F1 and Sports:
https://stremverse1.alwaysdata.net/manifest.json
```

The ideal-link selector prefers:

```text
1080p
→ highest seeder count
→ smallest file when seeders are tied
```


## Connection diagnostics

Run this response-enabled action in **Developer tools → Actions**:

```yaml
action: stremio_stream_bridge.connection_diagnostics
```

It reports the stream-server and every manifest separately. A typical PC-side failure looks like:

```yaml
stream_server:
  url: http://192.168.1.145:11470
  ok: false
  test_path: /settings
  error: Failed requesting http://192.168.1.145:11470/settings: TimeoutError
```

From another LAN device, `http://192.168.1.145:11470/settings` must return JSON. If it does not, check that the server listens on `0.0.0.0` rather than only `127.0.0.1`, and allow inbound TCP port 11470 in the Windows Private firewall profile.

## Direct playback

**Play ideal link when selecting an item** is enabled by default.

- Selecting a movie starts the ideal link directly.
- Selecting a series still opens seasons.
- Selecting an episode starts the ideal link directly.
- Selecting a sports event/channel starts the first source returned by that sports add-on.

Disable the setting to restore the manual list of source links.

## Audio compatibility

The **Audio compatibility** option has three modes:

- `automatic` — default. Torrent/MKV-like sources are routed through stream-server HLS using H.264/AAC stereo. Existing HLS/DASH live feeds are left untouched.
- `direct` — sends the original stream URL directly to the player.
- `force_transcode` — forces stream-server transcoding for every non-live source.

Automatic mode is intended to fix the common situation where Cast shows video but cannot decode DTS, TrueHD, E-AC-3 or another audio track.

## Borderless subtitles

When the target is a Home Assistant Cast entity, the integration modifies the outgoing Cast LOAD message so subtitle style uses:

```text
edgeType: NONE
background: transparent
window: none
```

Subtitles are still downloaded, converted to WebVTT and served temporarily by Home Assistant.

## Latin Audio profile

Put one or more Stremio manifest URLs in **Latin Audio manifests**. A stream-only add-on is enough: when it does not provide catalogs, the integration mirrors the normal Cinemeta movie/series catalogs and queries only the Latin provider for playback.

The browser then shows:

```text
Stremio Media
├── Películas
├── Series
├── Audio Latino
│   ├── Películas
│   └── Series
└── F1 y Deportes
```

The Latin profile always plays without external subtitles.

Action example:

```yaml
action: stremio_stream_bridge.play
data:
  media_type: movie
  media_id: tt0133093
  profile: latin
  media_player: media_player.tv_living
```

## F1 and Sports profile

Put the sports add-on manifest in **F1 and Sports manifests**. For natural navigation, the add-on must expose both `catalog` and `stream` resources.

Its catalog types may be `tv`, `channel`, `movie`, `series` or another valid Stremio type. The integration creates a dedicated **F1 y Deportes** section and uses only that provider group for playback.

Action example:

```yaml
action: stremio_stream_bridge.play
data:
  media_type: tv
  media_id: event-id-from-addon
  profile: sports
  media_player: media_player.tv_living
```

## Notes

- The PC stream-server must be reachable from Home Assistant and from the playback device.
- HLS audio compatibility depends on FFmpeg/transcoding support in the stream-server build.
- External subtitles are applied only to Home Assistant entities belonging to the Cast integration.
- Public add-ons can change or disappear; configurable manifest fields are intentionally used instead of hard-coding a specific Latin or sports service.
- Use media and providers only where you have the right to access and reproduce the content.
