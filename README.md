# Stremio Stream Bridge v0.5.6

Custom Home Assistant integration that combines Stremio-compatible catalogs, stream providers and subtitles, selects practical sources, and sends playback to a configured media player through a compatible stream-server.

## Repository layout

This repository contains only the Home Assistant integration:

```text
custom_components/stremio_stream_bridge
```

The stream-server projects are maintained separately:

```text
Home Assistant app:
https://github.com/diegocesaretti/stream-server-home-assistant

GPU / Cast build:
https://github.com/diegocesaretti/stream-server-gpu-cast
```

Catalog filtering and torrent ranking happen inside Home Assistant before the selected source is handed to the stream-server. The GPU build changes serving and transcoding, not metadata search.

## What is new in 0.5.6

### Optional H.264 and file-size preferences

The source selector now separates mandatory filters from optional preferences.

Mandatory:

```text
excluded release keywords
maximum configured size
```

Optional:

```text
prefer H.264 / x264 names
prefer the smaller file as the final tie-breaker
```

Both optional preferences are disabled by default. This is appropriate when every source is transcoded to a compatible H.264/AAC output.

The maximum-size setting is a hard filter. A source with a known size above the selected value is never used, including as fallback. Sources whose provider does not report a size cannot be compared against that limit.

When `force_transcode` is active, direct-play container and codec penalties no longer affect ranking because the receiver gets the encoded output rather than the original MKV/HEVC/DTS source.

### Configurable Audio Español/Latino filter

The Audio Español/Latino profile uses the same main stream providers as normal playback. It checks configurable markers in:

```text
name
title
description
behaviorHints.filename
```

Default markers include:

```text
audio latino
español latino
castellano latino
spanish latino
dual latino
latino / latina
latam
latinoamérica / latin america
español / castellano / spanish
Latin American country flags
```

Matching ignores capitalization, accents and punctuation.

The legacy `latin_manifest_urls` field is retained only so old configuration entries continue loading. It is ignored and no legacy Latin provider is contacted.

### Hide titles without Spanish/Latin sources

The Audio Español/Latino catalog can hide titles for which no matching source exists.

To avoid flooding providers:

- checks run with limited concurrency;
- confirmed results are cached for 30 minutes;
- series sample representative episodes from the beginning, middle and end;
- temporary provider errors keep the card visible instead of hiding the entire catalog.

Opening the filtered catalog is therefore slower the first time than opening the normal catalog. Later visits use the availability cache.

### Preferred internal audio tracks

For multi-audio files, the integration sends an ordered language preference to compatible GPU stream-server builds:

```text
lat, esp, spa, es
```

The server should mark the first matching internal audio track as the HLS default. If no track matches, it should retain the file's original default track.

The query parameter is named:

```text
audioLanguages=lat,esp,spa,es
```

Older stream-server builds safely ignore the parameter. Actual automatic track switching requires a GPU/server build that implements it.

### Secondary main stream source

Options now include one optional **Secondary main source manifest JSON**.

It is registered with the same `stream` role as the main providers:

```text
primary stream manifests
+ secondary manifest.json
→ parallel requests
→ merged results
→ duplicate removal
```

The secondary provider also participates in Audio Español/Latino filtering. If it is unavailable, successfully loaded primary providers continue working.

## Search in the Home Assistant Media Browser

Native Media Source search requires Home Assistant 2026.7 or later. On compatible Core/frontend versions, searchable folders expose the Media Browser search action:

```text
Stremio Stream Bridge → movies and series
Películas             → movies only
Series                → series only
```

The integration queries configured catalogs that advertise the Stremio `search` extra, merges responding providers, removes duplicate IDs and ranks exact title matches before prefix and partial matches.

On older Home Assistant versions, use:

```yaml
action: stremio_stream_bridge.search
data:
  query: The Matrix
  media_type: all
response_variable: result
```

The latest service search is exposed inside the Media Browser as:

```text
Búsqueda: The Matrix
```

## Automatic source selection

With all preferences enabled, the practical order is:

```text
mandatory maximum-size and exclusion filters
→ direct-play compatibility, unless force_transcode is active
→ optional H.264/x264 preference
→ preferred resolution
→ highest seed count
→ optional smaller-file tie-breaker
```

For `profile=latin`, sources are first restricted to releases matching the configured Spanish/Latin markers.

The integration can stop the previous playback session, close the active Cast receiver, prebuffer the new source and try ranked fallbacks until the player reaches `playing`.

## Provider profiles

### Default

Typical providers:

```text
Catalog and metadata:
https://v3-cinemeta.strem.io/manifest.json

Primary streams:
https://torrentio.strem.fun/manifest.json

Optional secondary streams:
any compatible Stremio stream manifest.json

Subtitles:
https://opensubtitles-v3.strem.io/manifest.json
```

### Audio Español/Latino

Uses the main and optional secondary stream providers, filtered by configurable release metadata. No dedicated Latin provider is required.

### F1 and Sports

Sports remains a separate optional provider profile because its catalogs and live-stream resources are structurally different from movie and series torrents.

## Audio compatibility

Available modes:

- `direct` — sends the original stream-server URL to the player;
- `automatic` — retained as a backwards-compatible direct-playback alias;
- `force_transcode` — requests the configured stream-server HLS conversion route and currently retains the established direct fallback if conversion validation fails.

For an encode-first GPU setup, disable **Prefer H.264/x264 sources** unless reducing decode load matters more than seeds or availability.

## Home Assistant services

### Search

```yaml
action: stremio_stream_bridge.search
data:
  query: The Matrix
  media_type: movie
response_variable: result
```

### Resolve

```yaml
action: stremio_stream_bridge.resolve
data:
  query: Breaking Bad
  media_type: series
  season: 2
  episode: 3
response_variable: result
```

### Play

```yaml
action: stremio_stream_bridge.play
data:
  media_type: "{{ result.selected.media_type }}"
  media_id: "{{ result.selected.media_id }}"
  profile: "{{ result.profile }}"
  media_player: media_player.tv_living
```

Available profiles:

```text
default
latin
sports
```

## Installation or update

1. Copy `custom_components/stremio_stream_bridge` to `/config/custom_components/`.
2. Replace the existing folder when updating.
3. Restart Home Assistant.
4. Keep the existing configuration entry; no reset is required.
5. Open **Settings → Devices & services → Stremio Stream Bridge → Configure**.
6. Configure the maximum size and optional H.264/smaller-file preferences.
7. Edit the Spanish/Latin release keywords and internal audio codes when needed.
8. Optionally enter a secondary main provider `manifest.json`.
9. Clear the legacy Latin Audio manifests field.

Do not use `127.0.0.1` or `localhost` when a Chromecast or television must open the stream URL itself.

## Internal identity

```text
domain: stremio_stream_bridge
folder: custom_components/stremio_stream_bridge
services: stremio_stream_bridge.*
```

The domain remains unchanged so existing configuration entries, services and automations continue working.

## Notes

- The configured stream-server must be reachable from Home Assistant and the playback device.
- Public Stremio add-ons can change or disappear without notice.
- Torrent release names are not perfectly standardized; language filtering can only use metadata returned by providers.
- Filtering the Spanish/Latin catalog requires additional stream-provider requests on the first visit.
- Use media, catalogs and providers only where you have the right to access and reproduce the content.
