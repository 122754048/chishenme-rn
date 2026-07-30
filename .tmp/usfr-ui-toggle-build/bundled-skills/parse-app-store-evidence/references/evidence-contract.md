# App-store evidence contract

Contract version `1` is provider-neutral. The same bundle shape is emitted for
Apple App Store and Google Play; only provider identity and store-specific ID
semantics differ (`adamId` versus Android package/application ID).

## Output

Write `app_store_evidence_bundle.json` as UTF-8 JSON.

Required top-level fields:

- `contract`: `app-store-evidence`
- `contract_version`: `1`
- `provider`
- `requested_url`, `final_url`, `canonical_url`
- `store_app_id`, `name`, optional `bundle_id`
- `storefront`, `language`
- `page_sha256`
- `pixel_truth_mode`: `replacement_pixels`, `icon_only`, or `metadata_only`
- optional `icon`
- ordered `screenshots`
- ordered `screenshot_device_families`
- `warnings`

Accepted product URLs are direct public HTTP(S) pages on `apps.apple.com` with a
numeric `/id...` path or on `play.google.com/store/apps/details` with one valid
`id=<package>` query value. Google `hl` and `gl` values populate `language` and
`storefront`; a missing `gl` is represented as `default`, never guessed from
the user's machine.

Each media record contains:

- `media_role`: `app_icon` or `app_screenshot`
- `store_media_ordinal`
- optional `device_family` and `device_family_ordinal`
- `width` and `height` (declared page dimensions in metadata-only mode;
  verified decoded dimensions after download)
- `source_url`, `final_url`
- `content_type`, `size_bytes`, `sha256`
- optional relative `file_path`

## Authority and validation

- `store_app_id`, `storefront`, and `language` form the target identity.
- Every downloaded file must belong to that identity and to the ordered media list emitted by the same page.
- `store_media_ordinal` is global page order within the ordered screenshot
  list. `device_family_ordinal` is local order inside one family.
- Do not convert unknown device families to phone or tablet.
- A media budget failure blocks the complete ingestion; never truncate the list.
- Metadata-only evidence does not authorize a specific logo or UI.

Google pages contain many unrelated Googleusercontent images (reviews,
recommendations, permissions). Only explicit target icon/screenshot markers
from the requested page are admissible. Thumbnail URLs are normalized to the
official CDN's original-asset form before download; the downloaded Pillow
dimensions, content type, byte count, and SHA-256 are authoritative.

## Downstream use

Downstream workflows may use verified textual metadata as facts and downloaded files as pixel truth. They must not use the store URL, raw page, recommendations, or unrelated media as generator inputs.
