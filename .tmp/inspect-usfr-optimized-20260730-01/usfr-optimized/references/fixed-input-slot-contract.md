# Fixed Input Slot Contract

The public intake has exactly seven fixed slots. The slot location determines
the role; no model, filename, or pixel classifier may reassign an uploaded
asset.

| Slot | Required | Accepted value | Role |
| --- | --- | --- | --- |
| `source_video` | yes | video, max 30 seconds | source viral video |
| `new_product_image` | no | image or image list | target product truth |
| `new_model_image` | no | image or image list | target character truth |
| `ui_screenshot` | no | image or image list | target UI truth |
| `app_store_url` | no | official HTTPS Apple App Store or Google Play URL | App evidence |
| `ui_operation_video` | no | video | opaque UI replacement |
| `tail_video` | no | video | opaque App tail-card replacement |

`app_store_url` accepts only a direct official HTTPS Apple App Store URL or a
Google Play URL with the `play.google.com/store/apps/details?id=...` shape. For
Google Play, the package ID is the target identity and must remain consistent
through the requested, final, and canonical URLs. `hl` maps to `language` and
`gl` maps to `storefront`; an absent or invalid `gl` is preserved as `default`,
never inferred from a local or server locale. The bundled
`parse-app-store-evidence` parser is the only admissible store resolver.

For service intake, a media value may also be an upload-completion object:
`{object_key, sha256, size_bytes, content_type, duration_seconds, status}`.
The request must include one safe `upload_scope`, and every completion key must
belong to its exact `uploads/{upload_scope}/` namespace. The server accepts only
safe keys, allowlisted image/video MIME types, exact SHA-256/size metadata, and
(when present) `status: completed`.
Video completion records include `duration_seconds`; `source_video` is capped at
30 seconds. The configured object-store adapter must HEAD/verify the object
before admission. `new_product_image`, `new_model_image`, and `ui_screenshot`
accept lists; all other slots are single-value slots.

`output_language` is a separate fixed parameter, not an eighth media slot.
Supported values are `en`, `ja`, `ko`, `fr`, `de`, `es`, `pt`, `id`, and `zh`.
The explicit language-only route (`source_video` plus valid `output_language`)
still uses this same object verification and scope-ownership path. It sets
`admission.language_only=true`, allows zero optional media slots for that route
only, and becomes a valid source-plus-change admission. The selected language
changes generated dialogue/text/audio while preserving source meaning, tone,
delivery, timing, and all absent-slot preservation routes.

`background_music` is the sole public `input-contract-v2` extension. It is not
an eighth fixed slot: it never changes fixed-slot ordering or asset-role
classification, and is recorded only in `extensions.background_music`. A valid
audio upload is a source-plus-change admission, uses the
`seedance_audio_reference` route, and must be executed only by a deployment
that binds `background_music_execution/v1`. It is never `language_only`.
The final fixed-B request may include it only as one 2–15 second, current-
segment RunningHub Standard Model `audioUrls` entry. The approved visual
request must retain at least one storyboard or target image. For every
source-fidelity generated segment, the exact current 2-15 second matching
original source segment is mandatory at `videoUrls[0]`, and the one-to-nine
image array must use `continuous-present-role-order/v1` plus
`usfr-multimodal-reference-binding/v2`: model identity when present, product/App
truth when present, every approved director-board PNG page, then explicitly
scoped additional references. Source Cut/keyframe sheets and
replacement-control sheets must never be sent to Seedance; the full source
video must never be uploaded. The compiled prompt names the audio entry as
`@Audio1`.

Every approved storyboard page is uploaded as its original confirmed PNG;
`seedance_execution_carrier.png` and single `storyboard_url` bindings are
forbidden. Enforce `uploaded_tags == binding_tags == prompt_tags`. @Video1 and
@Audio1 use independent namespaces and never consume image indices.
Every request with `videoUrls[0]` is compiled through `seedance-20` and must
contain: `@Video1 is the source reference video only for shot structure, composition, camera path, blocking, action timing, pacing, transitions, and delivery rhythm. Do not copy or output any person or identity, product/App or merchandise, visible text, original voice, original narration, or original dialogue from @Video1. Generate only the approved characters, target product/App evidence, exact visible text, voices, narration, dialogue, actions, and audio explicitly specified by this prompt and its bound image and audio references.`
Top-level `reference_audios` remains forbidden.

Store evidence is parsed once per run in a server Worker and persisted as a
tenant-scoped private evidence bundle plus verified media references. The URL,
page HTML, and local staging directory are not generator inputs or production
authority; local paths are development-only.

## Admission

The formal run gate is:

```text
source_video valid
AND (
  at least one of the six optional slots valid
  OR at least one enabled input-contract-v2 extension valid
  OR output_language valid
)
```

Source-only input without a replacement slot and without `output_language`
returns `MIN_ONE_OPTIONAL_INPUT_REQUIRED`; it must not create a formal run,
storyboard, Seedance task, or paid request. A valid optional slot in any one
position admits the run. A valid enabled extension admits the run without
changing the seven-slot manifest. A valid `output_language` admits a
language-only run even when all six optional slots are absent. Preferences and
an approved script do not count as optional media slots.

## Manifest

Run `scripts/bind_input_slots.py` once and persist its output as
`analysis/input_slots.json`. Downstream stages consume this immutable manifest.
Each slot records `slot_id`, fixed `role`, `kind`, `present`, `valid`,
`source`, normalized `values`, and SHA-256 values. The manifest also records
`admission`, deterministic `routes`, and `output_language` when supplied.
Enabled extensions are carried separately in `extensions`, including their
provider route, MIME type and immutable upload digest.
For production, the job-scoped Redis `slots_manifest` snapshot and
immutable object references are authoritative; `analysis/input_slots.json` is
an export snapshot or worker staging artifact only.

## Default routes for absent slots

- absent product image → `source_preserve` product truth;
- absent model image → `source_preserve` character truth;
- no UI video and no UI screenshot/App URL → `source_ui_keep` source-origin
  interval;
- UI screenshot or App URL without UI video → `generated_ui_demo`;
- UI video → `opaque_ui_demo`;
- no tail video → `omit_source_end_card` terminal omission;
- tail video → `opaque_app_tail_card`.

Source UI intervals are post-production source media. Source tail intervals are
excluded entirely when the tail slot is absent. A supplied tail is audited for
technical active content, automatically trims only leading/trailing black
padding, and ends at its last active frame. These intervals are excluded from
generated script/storyboard/Seedance assets and never receive filler, freeze,
loop, or source-duration padding.
In production, “source-origin interval” and “assembled locally” mean a
server-side worker reading a verified object-store reference; they never mean
the user's workstation or a required client-local file.

The deployment switch `USFR_UI_REBUILD_ENABLED` defaults to `false` and is
frozen into `extensions.ui_rebuild_enabled`. It only permits automatic UI
rebuild fallback for product/model/language replacement. A supplied UI
screenshot or official Apple App Store/Google Play URL is explicit target UI
evidence and always enables `generated_ui_demo`, even when the switch is
false. A supplied `ui_operation_video` always wins and remains
`opaque_ui_demo`. With no UI target evidence and the switch disabled, source UI
operations remain untouched and their OCR/App Store/UI-render stages are
skipped.
