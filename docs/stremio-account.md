# Optional Stremio account bridge

The account layer is optional and does not replace the integration's playback engine. Search, source ranking, Cast cleanup, fallback, subtitles and stream-server transcoding continue through the existing `stremio_stream_bridge` pipeline.

## Setup

Open **Settings → Devices & services → Stremio Stream Bridge → Configure** and enable **Link a Stremio account**.

Enter the account email and password once. The password is exchanged for a Stremio authentication key and is not stored in the config entry. On later edits, leave the password blank to keep the existing key. Enter the password again only when reauthentication is needed.

## Provider modes

- `manual`: use only the manifests configured in Stremio Stream Bridge.
- `account`: use the account's installed add-ons for catalogs, streams and subtitles. The separately configured Sports profile is retained.
- `hybrid`: merge manual and account add-ons, query compatible providers together and deduplicate their results.

Account add-on transport URLs can contain private configuration. Full URLs remain in memory for requests, while entity attributes and coordinator diagnostics use non-secret `account://…` identifiers. If account providers fail to load, the bridge restores its previous manual provider set.

## Library and resume

When the account is connected, the Home Assistant Media Browser adds:

- **Continue Watching**
- **My Stremio Library**

Selecting a resume item sends its movie or episode through the normal stream selection and playback pipeline, then seeks the physical `media_player` to the saved position.

The playback tracker observes the selected physical player and writes position updates back to Stremio roughly once per minute and immediately when playback pauses or stops. Only items that already exist in the linked Stremio library are updated in this first implementation; playing an unrelated catalog item does not automatically add it to the library.

## Failure isolation

Account login, polling and provider errors are non-fatal. A Stremio account outage must not prevent manually configured catalogs or the existing stream-server playback path from loading.
