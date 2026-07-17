# Stremio Stream Bridge v0.4.1 for Home Assistant

Custom Home Assistant integration that combines Stremio-compatible catalogs, stream providers and subtitles, then sends the selected media through a Stremio stream-server running on a PC.

## v0.4.1 Cast hotfix

- HLS and DASH URLs now use the MIME type of the resolved playlist, even when an add-on supplies a misleading filename hint.
- Proxied playlists are checked before Cast playback. Dead links are skipped automatically.
- F1/Sports playback tries the next source instead of blindly using a broken first result.

## What is new in v0.4.0

- Borderless Google Cast subtitles: transparent background/window and `edgeType: NONE`.
- Audio compatibility mode enabled by default. Torrent and MKV-like sources can be routed through stream-server `hlsv2` as H.264 video with AAC stereo audio.
- Direct ideal-link playback enabled by default: selecting a movie, episode or event starts playback instead of opening the source list.
- Optional **Latin Audio** provider profile. It uses only the configured Latin stream add-ons and always disables subtitles.
- Optional **F1 and Sports** provider profile. It uses the add-on's own catalogs and streams and does not request subtitles.
- Fixed migration logic from old versions.

## Installation or update

1. Copy `custom_components/stremio_stream_bridge` to `/config/custom_components/`.
2. Replace the existing folder when updating.
3. Restart Home Assistant.
4. Keep the existing config entry; it migrates automatically to version 4.
5. Open **Settings → Devices & services → Stremio Stream Bridge → Configure**.

## Default profile

```text
Catalog and metadata:
https://v3-cinemeta.strem.io/manifest.json

Default streams:
https://torrentio.strem.fun/manifest.json

Subtitles:
https://opensubtitles-v3.strem.io/manifest.json
```

The ideal-link selector prefers:

```text
1080p
→ highest seeder count
→ smallest file when seeders are tied
```

## Direct playback

**Play ideal link when selecting an item** is enabled by default.

- Selecting a movie starts the ideal link directly.
- Selecting a series still opens seasons.
- Selecting an episode starts the ideal link directly.
- Selecting a sports event/channel tries provider sources in order and skips dead proxied playlists.

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
