# Hybrid compositor contract

The hybrid compositor is an additive post-production adapter inside the
existing assembly/timeline stage. It does not add a route, approval, provider
task, or public input. It consumes verified tenant-private object references
and emits the existing immutable `final/result.mp4` artifact plus the ordinary
timeline manifest.

## Region manifest

Each generated or composite region records:

- `base_plate` with origin (`source`, `generated`, or `opaque`) and object key;
- ordered visual layers using only `KEEP`, `REPLACE`, `COMPOSITE`, `REMOVE`,
  `REINTERPRET`, or `OPAQUE_SPLICE`;
- z-order, normalized geometry, matte, tracking, occlusion, and light-match
  evidence for every `COMPOSITE` layer;
- audio layers with explicit time windows and authorized object/source
  references;
- an immutable output artifact URI, byte size, and SHA-256.

Workers build and validate this envelope with
`build_composite_manifest(...)` and `validate_composite_manifest(...)` before
calling the existing timeline splice adapter.

The default backend is deterministic FFmpeg. HyperFrames HTML UI and Remotion
React UI are optional adapters and remain disabled unless a same-case benchmark
proves the required OCR/trajectory/stream quality and bounded active-time
overhead. MediaBunny is a client-side preflight utility, not a server authority.

## Opaque and source-origin media

`OPAQUE_SPLICE` preserves supplied UI/tail pixels and audio. It may normalize
container, dimensions, frame rate, timestamps, and boundary black trim only as
the fixed timeline contract permits; it must not OCR, redraw, retime, rewrite,
or send the media to Seedance/Image Gen. Source-origin intervals are spliced
from verified object references and receive technical-only QC.

Opaque aspect normalization is fail-closed when it would require visible black
padding or a centered crop beyond the 12% safe cover-crop limit. Decoded video
stream duration, not container or AAC overhang, is the visual placement
authority. Supplied UI trims only leading/trailing black padding from video and
audio together, preserves its active-content duration, and recalculates all
downstream mappings from the effective duration. It receives no final-frame
padding, no audio padding, no atempo, loop, freeze, or time stretch. After
normalization, every region is forced to a square sample aspect ratio
(`SAR=1:1`) before xfade/concat; source SAR is kept only in placement provenance
so mixed mobile exports cannot break the transition graph.

No compositor path may introduce black filler, an unintended freeze frame,
unowned audio, PTS/A/V drift, or a transition shell that was not carried by the
source contract. A supplied terminal tail ends at its last active frame; an
absent tail is omitted from final assembly.
Every completed hard-cut/transition window receives boundary-aware black QC;
one full black frame at a splice boundary, or any longer splice-boundary black
interval, blocks publication even when it is internal to the file.

## Deployment boundary

The manifest is validated before rendering and is lease-fenced with the
existing artifact publication. Local paths are staging inputs only. Backend
selection is capability/configuration data inside the worker and cannot become
a new client field or silently change an approved route.
