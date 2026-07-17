# Changelog

## 0.4.1

- Fix HLS/DASH MIME detection: the resolved `.m3u8`/`.mpd` URL now takes precedence over an add-on filename hint.
- Validate proxied HLS manifests before casting and automatically fall back to the next ranked source when a link is dead.
- Sports automatic playback no longer blindly trusts the first stream returned by the add-on.
- Add clearer debug logging for selected stream, MIME type and fallback decisions.

## 0.4.0

- Removed black subtitle outlines/background windows on Google Cast.
- Added automatic H.264/AAC HLS compatibility mode to fix silent audio.
- Added direct ideal-link playback on item selection, enabled by default.
- Added separate configurable Latin Audio and F1/Sports provider profiles.
- Latin and sports profiles automatically disable external subtitles.
- Added sports catalog browsing and Latin catalog mirroring.
- Added profile selection to the `play` action.
- Fixed migration from older config-entry versions.

## 0.3.1

- Fixed external subtitles failing silently.
- Added Home Assistant-hosted temporary WebVTT proxy with CORS.
- Added gzip/ZIP, UTF-8, UTF-16, Windows-1252 and Latin-1 subtitle decoding.
- Added fallback retry without Stremio subtitle extras.
- Marked Cast video playback as BUFFERED instead of LIVE.
- Added subtitle provider errors and Cast compatibility to the connectivity sensor.
- Added an optional LAN subtitle base URL for receivers that cannot resolve Home Assistant automatically.

## 0.3.0

- Added subtitle add-on aggregation and OpenSubtitles v3 default configuration.
- Added preferred subtitle languages and automatic subtitle selection.
- Added optional stream-server WebVTT conversion/proxy.
- Added Google Cast external subtitle-track playback.
- Added per-playback subtitle disable option.
- Added ideal-link filter: prefer 1080p, highest seed count, then smallest file.
- Added migration from v0.2 to subtitle-capable configuration.

## 0.2.0

- Aggregate catalog, metadata and stream providers.
- Default Cinemeta + Torrentio configuration.
- Movies/series hierarchy, seasons and episodes.
- Genre/year filters and pagination.
- Automatic and manual stream selection.
- Search service and forward-compatible native media-source search.
- Migration from v0.1 single-add-on entries.

## 0.1.0

- Initial single add-on and stream-server bridge.
