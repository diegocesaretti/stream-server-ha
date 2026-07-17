# Stremio Stream Bridge v0.3.0 for Home Assistant

Custom Home Assistant integration that combines Stremio-compatible catalog, stream and subtitle add-ons into one browsable media library.

The default setup uses:

- **Cinemeta** for movie/series catalogs, posters, metadata, seasons and episodes;
- **Torrentio** as the stream provider;
- **OpenSubtitles v3** as the subtitle provider;
- a Stremio-compatible **stream-server** running on a PC;
- a Home Assistant `media_player` as the playback target.

Home Assistant does not download or transcode the video. It selects a source, builds the stream-server URL and calls `media_player.play_media` on the selected entity.

## What's new in v0.3.0

- Subtitle-provider role and default OpenSubtitles v3 manifest.
- Automatic subtitle selection by language priority.
- Uses stream filename, video hash and video size hints when available.
- Optional stream-server conversion/proxy to WebVTT.
- External subtitle tracks for Home Assistant Google Cast entities.
- A **Play without subtitles** option in the media browser.
- **Ideal link filter**:
  1. applies the configured excluded words and maximum size;
  2. restricts candidates to 1080p when available;
  3. chooses the result with the highest number of seeders;
  4. uses the smallest file as the tie-breaker;
  5. falls back to 720p, then 4K, then other qualities when no 1080p result exists.
- Automatic migration from v0.1 and v0.2 entries.

## Installation or update

1. Copy `custom_components/stremio_stream_bridge` to `/config/custom_components/`.
2. Replace the existing folder when updating.
3. Restart Home Assistant.
4. Existing entries are migrated automatically.
5. Open **Settings → Devices & services → Stremio Stream Bridge → Configure**.

The PC address must be reachable from Home Assistant and from the target TV/Chromecast. Do not configure stream-server as `127.0.0.1` or `localhost` unless all components run on the same computer.

## Default providers

```text
stream-server:
http://192.168.1.50:11470

Catalog and metadata manifests:
https://v3-cinemeta.strem.io/manifest.json

Stream manifests:
https://torrentio.strem.fun/manifest.json

Subtitle manifests:
https://opensubtitles-v3.strem.io/manifest.json
```

Multiple manifest URLs can be entered, one per line. Leave the subtitle manifest field empty to disable subtitle providers.

## Ideal link filter

Enable **Ideal-link filter** in the integration options. Automatic playback then ignores the normal preferred-quality selector and applies this order:

```text
1080p first
→ highest seed count
→ smallest file
```

Example candidates:

```text
1080p · 80 seeds · 2.1 GB
1080p · 140 seeds · 5.8 GB
1080p · 140 seeds · 3.4 GB  ← selected
4K    · 500 seeds · 18 GB
```

The 3.4 GB 1080p source wins because 1080p is required when available, 140 is the highest seed count in that group, and 3.4 GB is smaller than the other 140-seed result.

The maximum-size and excluded-keyword settings are still applied first. Common exclusions are `CAM, HDCAM, TS, TELECINE, SCREENER`.

## Subtitles

Subtitle options:

- mode: `automatic` or `disabled`;
- preferred languages, for example `spa, eng`;
- convert/proxy subtitles through stream-server as WebVTT.

For Google Cast entities, the integration sends the video and external subtitle track to the Cast Default Media Receiver. The stream-server URL looks like:

```text
http://PC:11470/subtitles.vtt?from=https%3A%2F%2Fsubtitle-source%2Ffile.srt
```

Native external subtitle support is currently limited to Home Assistant entities provided by the **Cast** integration. Other media-player integrations receive the video normally but may rely on subtitles embedded in the MKV or on player-specific support.

## Natural Home Assistant workflow

Open a compatible player and browse media:

```text
Stremio Stream Bridge
└── Stremio Media
    ├── Movies
    └── Series
```

A movie opens its stream list. A series opens seasons, episodes and then streams. At the top you get:

```text
▶ Ideal link · 1080p · most seeds · smallest size
▶ Ideal link · without subtitles
```

Manual source entries remain available below those automatic options.

## Actions

Automatic ideal-link playback with automatic subtitles:

```yaml
action: stremio_stream_bridge.play
data:
  media_type: movie
  media_id: tt0133093
  media_player: media_player.tv_living
```

Automatic playback without subtitles:

```yaml
action: stremio_stream_bridge.play
data:
  media_type: movie
  media_id: tt0133093
  media_player: media_player.tv_living
  disable_subtitles: true
```

Manual stream index:

```yaml
action: stremio_stream_bridge.play
data:
  media_type: series
  media_id: "tt0903747:1:1"
  stream_index: 2
  media_player: media_player.tv_living
```

Search on Home Assistant versions without native media-source search:

```yaml
action: stremio_stream_bridge.search
data:
  query: Interstellar
  media_type: all
```

## Supported Stremio sources

- direct HTTP/HTTPS URLs;
- HLS and DASH URLs;
- `infoHash` with optional `fileIdx`, trackers and filename hint;
- magnet URLs;
- `ytId`;
- proxy request/response headers through stream-server;
- subtitle objects included directly in a stream;
- separate Stremio subtitle add-ons.

## Limitations

- Playback depends on codecs and containers accepted by the target player.
- External subtitles are currently implemented specifically for Google Cast entities.
- Subtitle synchronization depends on the subtitle provider match; filename, hash and size hints improve it when the stream add-on supplies them.
- Provider response formats may change.

Use providers and media only where you have the right to access and reproduce the content.
