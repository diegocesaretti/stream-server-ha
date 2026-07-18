# Stremio Stream Bridge v0.5.5

Custom Home Assistant integration that combines Stremio-compatible catalogs, stream providers and subtitles, selects practical sources, and sends playback to a configured media player through a compatible stream-server.

## Repository layout

This repository contains only the Home Assistant integration:

```text
custom_components/stremio_stream_bridge
```

The Stream Engine, including the GPU-enabled build, is maintained separately:

```text
https://github.com/diegocesaretti/stream-server-home-assistant
```

The filtering and ranking described below happen inside Home Assistant before the selected torrent is handed to the stream-server. Using the GPU Stream Engine does not change catalog search or Latin Audio filtering; it only changes how the chosen source is served, remuxed or transcoded.

## What is new in 0.5.5

### Audio Latino through the main provider

The **Audio Latino** section no longer depends on a separate Stremio stream provider. It requests the same sources as the default profile and keeps only releases whose metadata advertises Latin American Spanish audio.

The filter checks:

```text
stream name
title
description
behaviorHints.filename
```

Recognized signals include:

```text
latino
latina
latam
audio latino
español latino
spanish latino
dual latino
latinoamérica / latin america
Latin American country flags
```

The match is accent-insensitive and punctuation-insensitive. For example, `Español.Latino`, `SPANISH-LATINO` and `Audio Latino` are treated equivalently.

If no release matches, the Latin profile returns an explicit error instead of silently playing a non-Latin source.

Old `latin_manifest_urls` values are retained only for configuration compatibility. They are ignored, never loaded and never contacted. New installations leave that legacy field empty.

External subtitles remain disabled for the Latin profile, as before.

## Search in the Home Assistant Media Browser

Native Media Source search requires **Home Assistant 2026.7 or later**. On compatible Core/frontend versions, searchable folders expose the Media Browser search action:

```text
Stremio Stream Bridge → movies and series
Películas             → movies only
Series                → series only
```

The integration queries every configured catalog that advertises the Stremio `search` extra, merges responding providers, removes duplicate IDs and ranks exact title matches before prefix and partial matches.

The stream-server is not contacted during metadata search. It is used after selecting a movie or episode.

On older Home Assistant versions, use the service fallback:

```yaml
action: stremio_stream_bridge.search
data:
  query: The Matrix
  media_type: all
response_variable: result
```

The latest service search is also exposed inside the Media Browser as:

```text
Búsqueda: The Matrix
```

## H.264/x264 name preference

When a provider returns at least one source explicitly labelled as H.264, stream ordering prefers:

```text
H.264 / H264 / x264 / AVC
→ codec not identified by name
→ H.265 / H265 / x265 / HEVC
```

H.265 sources are retained as fallbacks. This is a lightweight name filter; it does not inspect the real media tracks with FFprobe.

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

Resolve a spoken movie or series title without starting playback:

```yaml
action: stremio_stream_bridge.resolve
data:
  query: Breaking Bad
  media_type: series
  season: 2
  episode: 3
response_variable: result
```

Normal resolver outcomes are `exact`, `not_found`, `episode_not_found`, `unsupported` and `error`.

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

## Automatic source selection and fallback

Depending on the configured options, ranking considers:

```text
Cast/direct-play compatibility
→ Latin Audio match when profile=latin
→ H.264/x264 name preference
→ preferred resolution
→ highest seed count
→ smallest file when otherwise tied
```

The integration can stop the previous playback session, close the active Cast receiver, prebuffer the new source and wait for the player to reach `playing`. Failed or stalled candidates fall through to the next ranked source.

## Provider profiles

### Default

Typical providers:

```text
Catalog and metadata:
https://v3-cinemeta.strem.io/manifest.json

Streams:
https://torrentio.strem.fun/manifest.json

Subtitles:
https://opensubtitles-v3.strem.io/manifest.json
```

### Audio Latino

Uses the same stream manifests as **Default**, filtered by release-name metadata. No additional Latin provider is required.

### F1 and Sports

Sports remains a separate optional provider profile because its catalogs and live stream resources are structurally different from movie and series torrents.

## Audio compatibility

Available modes:

- `direct` — sends the original stream-server URL to the player.
- `automatic` — retained as a backwards-compatible direct-playback alias.
- `force_transcode` — requests the configured stream-server conversion route and falls back to direct when conversion fails.

The GPU Stream Engine can improve remux/transcode performance, but it does not change which source is selected by Home Assistant.

## Subtitles

The integration can aggregate subtitle providers, download and normalize subtitle files, convert them to WebVTT and temporarily serve them through Home Assistant.

For Home Assistant Cast entities, subtitle styling uses a transparent background and no black edge or window.

## Installation or update

1. Copy `custom_components/stremio_stream_bridge` to `/config/custom_components/`.
2. Replace the existing folder when updating.
3. Restart Home Assistant.
4. Keep the existing configuration entry; no reset is required.
5. Open **Settings → Devices & services → Stremio Stream Bridge → Configure**.
6. Enter the GPU or standard stream-server URL reachable from Home Assistant and the playback device.
7. Clear the legacy **Latin Audio manifests** field; it is ignored in v0.5.5.

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
- Torrent release names are not perfectly standardized; the Latin filter only trusts metadata explicitly returned by the provider.
- Use media, catalogs and providers only where you have the right to access and reproduce the content.
