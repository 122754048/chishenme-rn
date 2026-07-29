# USFR Pixel-Level UI Render Sidecar Design

Date: 2026-07-29
Status: Approved architecture, pending written-spec review

## Goal

Add a real pixel-level UI interaction renderer to the existing Universal Source Fidelity Replication (USFR) framework. The renderer must reproduce source UI interaction timing and motion while replacing source product, model, application, copy, and localized text with target-owned evidence.

The renderer is an independently installable project, but USFR remains the routing and contract authority. The Sidecar is an optional execution capability behind the existing `generated_ui_demo` route. It does not change any non-UI workflow or the Skill's existing semantic contract.

## Scope

The Sidecar handles only deterministic UI animation reconstruction:

- drag and scroll motion;
- tap timing and visible tap feedback;
- bounce and overshoot;
- scale and rotation;
- opacity changes;
- source entry and exit transition preservation;
- exact UTF-8 multilingual text rendering;
- replacement of source UI imagery, model images, product images, application screens, and approved copy.

The Sidecar does not generate people, scenes, speech, music, lip sync, storyboards, control keyframes, or Seedance prompts. UI pixels and UI text never enter Seedance.

## Trigger Rules

USFR starts the Sidecar only when all of these conditions are true:

1. The routed timeline contains a `generated_ui_demo` interval.
2. The source interval contains UI interaction requiring reconstruction.
3. The user did not upload a replacement UI-operation video.
4. Target-owned product, model, application, screenshot, or approved-copy evidence is available.

The Sidecar is bypassed in every other route.

| Condition | Result |
| --- | --- |
| User uploaded a UI-operation video | Use `opaque_ui_demo`; do not start Sidecar |
| Source has no UI-operation interval | Skip UI rendering; do not start Sidecar |
| Direct language-only workflow | Do not start Sidecar |
| Ordinary character, product, audio, or storyboard work | Do not start Sidecar |
| `generated_ui_demo` without replacement evidence | Fail the UI interval clearly; do not invent UI |
| Eligible `generated_ui_demo` | Lazily start and call Sidecar |

## Project Placement

The executable project lives outside the Skill package:

`C:\Users\zhaocx04\Documents\New project\usfr-ui-render-sidecar`

This keeps `node_modules`, the Python virtual environment, Chromium assets, render caches, and generated media out of the Skill directory.

USFR includes the Sidecar in its project framework through:

- an optional renderer capability identity;
- an immutable Sidecar manifest containing version and code/model SHA-256 values;
- an on-demand process launcher;
- the existing evidence-bound HTTP adapter;
- UI-only contract and integration tests.

The Skill package contains only the small integration modules and manifest needed to discover, launch, verify, and call the independent project.

## Architecture

### USFR UI Router

The existing routing decision remains authoritative. `opaque_ui_demo` keeps priority over `generated_ui_demo`. No Sidecar code runs before this decision.

### On-Demand Lifecycle Manager

An `OnDemandUiSidecarRenderer` wraps the existing `EvidenceBoundHttpUiRenderer`.

Construction of the wrapper does not start a process. On the first eligible render call it:

1. acquires a cross-process lock;
2. checks `GET /readyz`;
3. starts the configured Sidecar command only when the service is unavailable;
4. waits for bounded readiness;
5. submits exactly one render request;
6. records a non-secret lifecycle receipt;
7. allows the Sidecar to stop after a configurable idle timeout.

Concurrent UI jobs share one healthy Sidecar process. Non-UI jobs never import the render engine, launch Chromium, or run OpenCV.

### HTTP Service

The Sidecar is a Node.js and TypeScript service with:

- Express for HTTP transport;
- Zod for strict request and response validation;
- Remotion and `@remotion/renderer` for deterministic frame rendering;
- `@remotion/bundler` for a frozen composition bundle;
- FFmpeg and FFprobe for interval extraction, encoding, and validation;
- a project-local Python virtual environment with OpenCV for ROI-only motion extraction;
- Noto multilingual fonts for exact Unicode rendering.

Endpoints:

- `GET /readyz`: reports process, renderer, FFmpeg, OpenCV, font, and bundle readiness without receiving user media.
- `POST /v1/render`: accepts one evidence-bound UI render request and returns one MP4 plus receipts.

The first implementation is local and Docker-compatible. The HTTP contract does not depend on a user, account, billing, queue, or object-storage system.

### Compute Requirements

A local GPU is not required. The default local installation and acceptance path are CPU-only:

- OpenCV motion extraction runs on CPU;
- Remotion renders through Chromium without requiring CUDA;
- FFmpeg uses software decoding and `libx264` software encoding;
- no CUDA, DirectML, NVENC, or GPU inference dependency is installed;
- Chromium hardware acceleration is disabled for deterministic local tests.

GPU acceleration may be evaluated later as an optional deployment optimization, but it cannot become a functional dependency or alter render output.

### ROI Motion Extractor

The extractor receives only the already-routed source UI interval and its UI ROI. It must not scan the full source video.

For every source frame in the interval it produces a normalized track record containing the applicable values:

- translation `x` and `y`;
- scale `x` and `y`;
- rotation;
- opacity;
- crop or mask bounds;
- scroll offset;
- optional perspective transform;
- tap state;
- confidence and fallback reason.

The extractor uses template tracking, optical flow, feature matching, and bounded temporal smoothing. It classifies actions only to select render behavior; the numeric frame track remains the source of truth.

Track extraction is cached by source interval SHA-256, ROI, FPS, and extractor version. A cache hit avoids repeated analysis for batch variants of the same source video.

### Deterministic UI Composition

Remotion renders target-owned UI layers against the source-frame-locked tracks. Target text comes only from the approved UI truth card. Target images come only from uploaded or parsed target evidence.

Each rendered frame is calculated from the source frame index rather than wall-clock time. The composition preserves the source viewport, duration, frame rate, masks, z-order, and entry or exit shell. It never asks a generative video model to draw UI text or interaction states.

When the available target evidence cannot represent a required state, the render fails with a specific missing-evidence code. It does not invent an unverified screen.

## Evidence-Bound Contract

The current `usfr-ui-render-evidence/v1` request is extended only inside the UI renderer boundary to carry a motion reference:

- target UI source image and SHA-256;
- target `ui_truth_card`;
- target `ui_render_contract`;
- source UI interval MP4 and SHA-256;
- source UI ROI and interval timing;
- expected Sidecar identity and SHA-256.

The response echoes all target contracts and source digests, and returns:

- MP4 bytes and SHA-256;
- exact state sequence;
- motion-track SHA-256;
- composition bundle SHA-256;
- extractor and renderer identities;
- render timing and cache-hit receipts.

No local filesystem path or API token is sent in a request or written to receipts.

## Source Interval Materialization

USFR materializes only the selected UI interval before the HTTP call. FFmpeg trims to the immutable `source_window_us`, keeps the original FPS, and crops or masks to the routed UI ROI when the ROI is smaller than the viewport.

The temporary interval is content-addressed and removed by the existing task cleanup policy. This avoids full-video analysis and limits transport and extraction cost.

## Text and Localization

All JSON, source files, subprocess communication, and render props use UTF-8. The Sidecar rejects:

- Unicode replacement glyphs;
- consecutive question-mark placeholders;
- invalid surrogate sequences;
- missing glyph coverage;
- text not present in the approved truth card.

The default language is the source video's language. When the user specifies a target language, the full UI interval uses that target language. Font fallback is explicit and frozen for Latin, Cyrillic, Arabic, CJK, and emoji. Arabic shaping and bidirectional layout are verified in the rendered browser context.

## Error Handling

There are no automatic generation retries.

Readiness, validation, extraction, rendering, encoding, and digest failures return distinct error codes. A failed request keeps its non-sensitive receipt and diagnostic artifacts. The USFR job fails only the affected UI interval and reports the missing dependency or evidence directly.

An already-created render with an uncertain client response is reconciled by request SHA-256; it is not blindly created again.

## Performance

- Sidecar startup is lazy and shared across concurrent eligible UI jobs.
- Local execution defaults to CPU-only processing and software video encoding.
- The default idle shutdown timeout is 120 seconds and is configurable.
- Motion analysis is restricted to the UI interval and ROI.
- Track extraction is cached across variants.
- Remotion bundle creation is cached by composition SHA-256.
- Rendering concurrency is bounded independently from provider generation concurrency.
- Basic QA samples only contract anchor frames and essential decode, text, duration, viewport, and transition facts.
- Deep frame similarity, dense OCR, and automatic rerender remain disabled by default.

## Security

- The local service binds to `127.0.0.1` by default.
- An optional bearer token is loaded from a private environment file.
- Request size, decoded media size, frame count, duration, and render time are bounded.
- File paths are generated inside a per-request workspace; request values cannot select arbitrary filesystem paths.
- Receipts redact authorization data and never contain environment values.

## Testing Strategy

Implementation follows red-green-refactor TDD.

Required automated coverage:

- request and response schema validation;
- source and output digest binding;
- readiness without process startup during non-UI work;
- lazy single-process startup under concurrent UI calls;
- idle shutdown;
- ROI-only interval extraction;
- translation, drag, scroll, bounce, scale, rotate, opacity, and tap tracks;
- exact state ordering;
- UTF-8 Chinese, Arabic, Portuguese, and English rendering;
- question-mark placeholder and missing-glyph rejection;
- source entry and exit transition preservation;
- invalid or modified truth-contract rejection;
- real MP4 decode, duration, viewport, FPS, and nonblank pixel checks;
- `EvidenceBoundHttpUiRenderer` end-to-end integration;
- `opaque_ui_demo` and no-UI bypass tests.

## Acceptance Criteria

The work is complete only when:

1. all dependencies are installed in the independent project;
2. the Sidecar starts successfully from the USFR on-demand wrapper;
3. a real source UI interval produces a decodable target MP4;
4. the MP4 follows extracted frame-locked motion tracks;
5. multilingual target text renders without mojibake or placeholder glyphs;
6. USFR accepts the returned evidence and hashes;
7. non-UI and uploaded-UI-video routes prove that the Sidecar process was not started;
8. targeted UI tests and the unaffected USFR regression suites pass;
9. the final report provides the service URL, rendered MP4 path, receipts, timing, and any remaining quality limitations.

## Non-Goals

- No changes to source-video analysis outside routed UI intervals.
- No changes to storyboards, keyframes, scripts, audio, language-only, lip-sync, Seedance, provider, queue, or product-routing semantics.
- No account, billing, history, analytics, or production deployment platform.
- No installation of generated dependency folders inside the Skill directory.
- No claim of pixel-perfect reconstruction where target evidence does not contain the required UI state.
