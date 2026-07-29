# USFR Pixel-Level UI Render Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, install, and verify a CPU-only pixel-level UI interaction Sidecar that is independently packaged, registered inside USFR, and launched only for eligible `generated_ui_demo` intervals.

**Architecture:** USFR remains the route and evidence authority. A lazy Python wrapper starts a local Node/TypeScript HTTP Sidecar only when the existing generated-UI renderer is invoked; the Sidecar uses OpenCV dense motion transfer for the routed UI interval and Remotion for deterministic UTF-8 composition and MP4 output. Uploaded UI videos remain `opaque_ui_demo`, and every non-UI route bypasses the Sidecar without starting a process.

**Tech Stack:** Node.js 24, TypeScript, Express, Zod, Remotion, React, Vitest, Supertest, Python 3.12 virtual environment, OpenCV headless, NumPy, FFmpeg/FFprobe, project-local Noto fonts, pytest.

## Global Constraints

- The executable project is `C:\Users\zhaocx04\Documents\New project\usfr-ui-render-sidecar`.
- No `node_modules`, Python virtual environment, Chromium cache, render cache, or generated media may be placed inside the Skill directory.
- Local execution is CPU-only; do not install or require CUDA, DirectML, NVENC, or GPU inference.
- Only routed UI intervals are materialized; no full-video deep analysis is permitted.
- `opaque_ui_demo` has priority and must never start the Sidecar.
- No-UI, language-only, storyboard, audio, lip-sync, Seedance, product, and model routes must never start the Sidecar.
- UI text is exact UTF-8 target truth. Replacement glyphs, consecutive question-mark placeholders, missing glyphs, and renderer-authored copy are forbidden.
- No automatic generation or rendering retry is permitted.
- Basic QA is the default; dense OCR, deep frame similarity, and automatic rerender remain disabled.
- Existing USFR semantics and non-UI files remain unchanged except for the minimum optional capability registration.

## File Map

### Independent Sidecar project

- `usfr-ui-render-sidecar/package.json`: exact Node dependencies and scripts.
- `usfr-ui-render-sidecar/package-lock.json`: frozen npm dependency graph.
- `usfr-ui-render-sidecar/tsconfig.json`: strict TypeScript build.
- `usfr-ui-render-sidecar/vitest.config.ts`: unit and integration test configuration.
- `usfr-ui-render-sidecar/src/contracts.ts`: Zod request, response, model, truth, and motion schemas.
- `usfr-ui-render-sidecar/src/digests.ts`: canonical UTF-8 JSON and SHA-256 helpers.
- `usfr-ui-render-sidecar/src/config.ts`: loopback, token, limits, CPU-only, and idle timeout configuration.
- `usfr-ui-render-sidecar/src/server.ts`: `/readyz`, `/v1/render`, internal asset serving, lifecycle, and error mapping.
- `usfr-ui-render-sidecar/src/render-pipeline.ts`: request workspace, decoder, Python extractor, Remotion render, and receipts.
- `usfr-ui-render-sidecar/src/python-runner.ts`: bounded UTF-8 Python subprocess adapter.
- `usfr-ui-render-sidecar/src/remotion/index.tsx`: Remotion registration entrypoint.
- `usfr-ui-render-sidecar/src/remotion/UiReplica.tsx`: deterministic frame and exact-text composition.
- `usfr-ui-render-sidecar/src/remotion/render.ts`: bundle cache and `renderMedia` wrapper.
- `usfr-ui-render-sidecar/python/track_extractor.py`: ROI-only dense-flow motion transfer and summary tracks.
- `usfr-ui-render-sidecar/python/requirements.lock`: exact OpenCV, NumPy, and pytest versions.
- `usfr-ui-render-sidecar/assets/fonts/`: project-local Noto font assets installed from npm packages.
- `usfr-ui-render-sidecar/sidecar-manifest.json`: immutable model, extractor, renderer, and composition identity.
- `usfr-ui-render-sidecar/scripts/install.ps1`: idempotent CPU-only dependency installation.
- `usfr-ui-render-sidecar/scripts/start.ps1`: local loopback startup.
- `usfr-ui-render-sidecar/scripts/smoke.ps1`: one real render and receipt check.
- `usfr-ui-render-sidecar/tests/`: contract, readiness, render, UTF-8, motion, and lifecycle tests.

### USFR Skill integration

- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ui_interaction_contract.py`: freeze FPS and pixel ROI in the existing UI-only interaction contract.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\vision_backends.py`: materialize one source UI interval and bind it to the existing evidence HTTP request.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ui_sidecar_runtime.py`: lazy process lifecycle wrapper.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_factory.py`: optional environment-driven registration only.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\__init__.py`: export the new UI-only wrapper.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\references\bundle_manifest.json`: include the new runtime module.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\verify_bundle.py`: require the UI lifecycle module when declared.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ui_sidecar_runtime.py`: lazy start and bypass tests.
- `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ui_renderer_motion_reference.py`: interval and digest binding tests.
- Existing focused UI tests are modified only when the frozen UI contract gains FPS and ROI fields.

---

### Task 1: Bootstrap the independent CPU-only Sidecar and freeze its API contract

**Files:**
- Create: `usfr-ui-render-sidecar/package.json`
- Create: `usfr-ui-render-sidecar/tsconfig.json`
- Create: `usfr-ui-render-sidecar/vitest.config.ts`
- Create: `usfr-ui-render-sidecar/src/contracts.ts`
- Create: `usfr-ui-render-sidecar/src/digests.ts`
- Create: `usfr-ui-render-sidecar/tests/contracts.test.ts`
- Create: `usfr-ui-render-sidecar/tests/fixtures.ts`
- Create: `usfr-ui-render-sidecar/.gitignore`

**Interfaces:**
- Consumes: `usfr-ui-render-evidence/v1`, target image bytes, target truth, target render contract, and a source motion-reference interval.
- Produces: `RenderRequest`, `RenderResponse`, `canonicalSha256(value)`, and strict Zod schemas used by all later tasks.

`tests/fixtures.ts` exports this exact helper:

```ts
export const sourceInteractionContract = () => ({
  schema_version: 'source-ui-interaction/v1' as const,
  region_id: 'ui-001',
  source_window_us: {start: 0, end_exclusive: 800_000},
  frame_window: {start: 0, end_exclusive: 24},
  source_fps: {num: 30, den: 1},
  display_viewport: [180, 320],
  ui_roi: {x: 0, y: 0, width: 180, height: 320, coordinate_space: 'display_pixels' as const},
  language: {source: 'en', target: 'en', mode: 'preserve_source' as const},
  text_encoding: {encoding: 'utf-8' as const, replacement_glyphs_forbidden: true as const},
  motion: {
    capture_scope: 'ui_roi_only' as const,
    track_policy: 'source_frame_locked' as const,
    supported_actions: ['drag', 'scroll', 'bounce', 'scale', 'rotate', 'opacity', 'tap'],
  },
  validation: {mode: 'basic_anchor_only' as const, automatic_retry: false as const, anchor_frames: [0, 23]},
});

export const validRequest = (approvedCopy: string[] = ['Buy now']) => {
  const core = {
    schema_version: 'usfr-ui-render-evidence/v1' as const,
    source_sha256: '1'.repeat(64),
    source_content_type: 'image/png',
    source_base64: 'aW1hZ2U=',
    ui_truth_card: {
      approved_copy: approvedCopy,
      states: [{state_id: 'state-001', frame_ms: 0, expected_text: approvedCopy, expected_layout: []}],
    },
    ui_render_contract: {viewport: [180, 320], state_sequence: ['state-001']},
    motion_reference: {
      sha256: '2'.repeat(64),
      content_type: 'video/mp4' as const,
      video_base64: 'dmlkZW8=',
      source_ui_interaction_contract: sourceInteractionContract(),
    },
    expected_model: {id: 'usfr-ui-remotion-opencv', sha256: '3'.repeat(64)},
  };
  return {...core, request_sha256: canonicalSha256(core)};
};
```

- [ ] **Step 1: Create package metadata and install exact dependencies**

Create scripts with these names:

```json
{
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "start": "tsx src/server.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  }
}
```

Run:

```powershell
npm install --save-exact express zod remotion @remotion/renderer @remotion/bundler react react-dom @fontsource/noto-sans @fontsource/noto-sans-sc @fontsource/noto-sans-arabic
npm install --save-dev --save-exact typescript tsx vitest supertest @types/express @types/node @types/react @types/react-dom @types/supertest
```

Expected: `package-lock.json` exists and `npm audit --omit=dev` completes without an install failure.

- [ ] **Step 2: Write the failing contract tests**

```ts
import {describe, expect, it} from 'vitest';
import {RenderRequestSchema, canonicalSha256} from '../src/contracts';

it('accepts exact UTF-8 truth and a bound motion reference', () => {
  const request = RenderRequestSchema.parse(validRequest(['立即购买', 'مرحبا']));
  expect(request.motion_reference.sha256).toMatch(/^[0-9a-f]{64}$/);
});

it('rejects replacement glyphs and question-mark placeholder runs', () => {
  expect(() => RenderRequestSchema.parse(validRequest(['????']))).toThrow();
  expect(() => RenderRequestSchema.parse(validRequest(['bad\uFFFDtext']))).toThrow();
});

it('hashes canonical Unicode JSON without ASCII escaping', () => {
  expect(canonicalSha256({text: '中文'})).toHaveLength(64);
});
```

- [ ] **Step 3: Run the tests and verify RED**

Run: `npm test -- tests/contracts.test.ts`

Expected: FAIL because `src/contracts.ts` and `canonicalSha256` do not exist.

- [ ] **Step 4: Implement the strict schemas and digest helper**

The request schema must require:

```ts
type RenderRequest = {
  schema_version: 'usfr-ui-render-evidence/v1';
  request_sha256: string;
  source_sha256: string;
  source_content_type: string;
  source_base64: string;
  ui_truth_card: UiTruthCard;
  ui_render_contract: UiRenderContract;
  motion_reference: {
    sha256: string;
    content_type: 'video/mp4';
    video_base64: string;
    source_ui_interaction_contract: SourceUiInteractionContract;
  };
  expected_model: {id: string; sha256: string};
};
```

Validate every text leaf with:

```ts
const exactText = z.string().min(1).refine(
  (value) => !value.includes('\uFFFD') && !/\?\?/.test(value),
  'text contains replacement or placeholder glyphs',
);
```

- [ ] **Step 5: Run contract tests and typecheck GREEN**

Run:

```powershell
npm test -- tests/contracts.test.ts
npm run typecheck
```

Expected: all contract tests PASS and TypeScript reports no errors.

- [ ] **Step 6: Commit Task 1**

```powershell
git add usfr-ui-render-sidecar/package.json usfr-ui-render-sidecar/package-lock.json usfr-ui-render-sidecar/tsconfig.json usfr-ui-render-sidecar/vitest.config.ts usfr-ui-render-sidecar/src/contracts.ts usfr-ui-render-sidecar/src/digests.ts usfr-ui-render-sidecar/tests/contracts.test.ts usfr-ui-render-sidecar/tests/fixtures.ts usfr-ui-render-sidecar/.gitignore
git commit --only -m "feat: freeze USFR UI sidecar contract" -- usfr-ui-render-sidecar
```

### Task 2: Implement ROI-only OpenCV motion transfer

**Files:**
- Create: `usfr-ui-render-sidecar/python/track_extractor.py`
- Create: `usfr-ui-render-sidecar/python/requirements.lock`
- Create: `usfr-ui-render-sidecar/python/tests/test_track_extractor.py`
- Create: `usfr-ui-render-sidecar/python/tests/fixtures.py`
- Create: `usfr-ui-render-sidecar/scripts/install.ps1`

**Interfaces:**
- Consumes: source interval MP4, target UI image, source UI interaction JSON, and output directory.
- Produces: `motion.mp4` and `motion-track.json` with one frame row per source frame.

`python/tests/fixtures.py` exports `make_drag_video`, `make_target_ui`, `run_extractor`, `full_frame_contract`, `short_video`, `target_image`, `oversized_contract`, `video_with_motion_outside_roi`, and `roi_contract`. Each helper writes a real OpenCV image/video fixture and returns `Path` objects or the exact contract dictionary consumed by `extract_tracks`.

- [ ] **Step 1: Write the failing Python tests**

```python
def test_dense_flow_transfers_horizontal_drag(tmp_path):
    source = make_drag_video(tmp_path, frames=12, dx=48)
    target = make_target_ui(tmp_path)
    result = run_extractor(source, target, full_frame_contract(12), tmp_path / "out")
    track = json.loads(result.track.read_text(encoding="utf-8"))
    assert len(track["frames"]) == 12
    assert track["frames"][-1]["translation_x"] >= 40

def test_extractor_rejects_contract_outside_video(tmp_path):
    with pytest.raises(ExtractorError, match="frame window"):
        extract_tracks(short_video(tmp_path), target_image(tmp_path), oversized_contract(), tmp_path / "out")

def test_analysis_never_reads_outside_ui_roi(tmp_path):
    result = run_extractor(video_with_motion_outside_roi(tmp_path), target_image(tmp_path), roi_contract(), tmp_path / "out")
    assert abs(result.track["frames"][-1]["translation_x"]) < 2
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest python/tests/test_track_extractor.py -q`

Expected: FAIL because the extractor module does not exist.

- [ ] **Step 3: Create the project-local Python environment and install pinned CPU packages**

`python/requirements.lock` contains:

```text
numpy==2.2.6
opencv-python-headless==4.12.0.88
pytest==8.4.2
```

`scripts/install.ps1` must run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r python\requirements.lock
npm ci
```

It must not install CUDA or change global Python packages.

- [ ] **Step 4: Implement dense-flow motion transfer**

Use the first ROI frame as the reference, compute Farneback flow for each later ROI frame, remap the target pixels with `cv2.remap`, and encode the warped frames with software H.264.

The track output is:

```python
{
    "schema_version": "usfr-ui-motion-track/v1",
    "fps": {"num": fps_num, "den": fps_den},
    "roi": {"x": x, "y": y, "width": width, "height": height},
    "frames": [
        {
            "frame": index,
            "translation_x": float(dx),
            "translation_y": float(dy),
            "scale_x": float(scale_x),
            "scale_y": float(scale_y),
            "rotation_deg": float(rotation),
            "opacity": float(opacity),
            "tap": bool(tap),
            "confidence": float(confidence),
        }
    ],
}
```

Reject empty media, invalid ROI, mismatched frame windows, and non-finite values. Do not retry extraction.

- [ ] **Step 5: Run Python tests GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest python/tests/test_track_extractor.py -q`

Expected: all tests PASS; fixture `motion.mp4` is decodable by FFprobe.

- [ ] **Step 6: Commit Task 2**

```powershell
git add usfr-ui-render-sidecar/python usfr-ui-render-sidecar/scripts/install.ps1
git commit --only -m "feat: transfer source UI motion on CPU" -- usfr-ui-render-sidecar/python usfr-ui-render-sidecar/scripts/install.ps1
```

### Task 3: Build deterministic Remotion composition and multilingual text rendering

**Files:**
- Create: `usfr-ui-render-sidecar/src/remotion/index.tsx`
- Create: `usfr-ui-render-sidecar/src/remotion/UiReplica.tsx`
- Create: `usfr-ui-render-sidecar/src/remotion/render.ts`
- Create: `usfr-ui-render-sidecar/src/fonts.ts`
- Create: `usfr-ui-render-sidecar/tests/remotion.test.ts`
- Create: `usfr-ui-render-sidecar/tests/render-fixture.ts`

**Interfaces:**
- Consumes: internal motion MP4 URL, truth states, viewport, FPS, duration, transition shell, and project-local fonts.
- Produces: `renderReplica(props, outputPath)` and a software-encoded H.264 MP4.

`tests/render-fixture.ts` exports `renderFixture(copy, options)` and creates a real local motion MP4, calls `renderReplica`, probes the output with FFprobe JSON, extracts anchor PNGs, and returns `{probe, replacementGlyphCount, outputPath}`.

- [ ] **Step 1: Write the failing Remotion tests**

```ts
it('renders exact Chinese Arabic Portuguese and English text', async () => {
  const result = await renderFixture(['立即购买', 'اشتر الآن', 'Comprar agora', 'Buy now']);
  expect(result.probe.codec_name).toBe('h264');
  expect(result.replacementGlyphCount).toBe(0);
});

it('keeps frame count and viewport fixed', async () => {
  const result = await renderFixture(['Buy now'], {frames: 18, width: 180, height: 320});
  expect(result.probe.nb_read_frames).toBe(18);
  expect([result.probe.width, result.probe.height]).toEqual([180, 320]);
});
```

- [ ] **Step 2: Run and verify RED**

Run: `npm test -- tests/remotion.test.ts`

Expected: FAIL because the Remotion composition and renderer are absent.

- [ ] **Step 3: Implement frame-deterministic composition**

Register one composition named `UiReplica` and calculate every state from `useCurrentFrame()`:

```tsx
export const UiReplica: React.FC<UiReplicaProps> = (props) => {
  const frame = useCurrentFrame();
  const state = interpolateUiState(frame, props.states, props.fps);
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <OffthreadVideo src={props.motionVideoUrl} muted />
      {state.elements.map((element) => <ExactText key={element.element_id} element={element} />)}
    </AbsoluteFill>
  );
};
```

Use software encoding, Chromium GPU disable flags, `concurrency: 1` for the acceptance fixture, and project-local Noto fonts. Do not fetch fonts over the network while rendering.

- [ ] **Step 4: Run tests and typecheck GREEN**

Run:

```powershell
npm test -- tests/remotion.test.ts
npm run typecheck
```

Expected: tests PASS and generated MP4s are nonblank and decodable.

- [ ] **Step 5: Commit Task 3**

```powershell
git add usfr-ui-render-sidecar/src/remotion usfr-ui-render-sidecar/src/fonts.ts usfr-ui-render-sidecar/tests/remotion.test.ts
git commit --only -m "feat: render deterministic multilingual UI video" -- usfr-ui-render-sidecar/src/remotion usfr-ui-render-sidecar/src/fonts.ts usfr-ui-render-sidecar/tests/remotion.test.ts
```

### Task 4: Implement the evidence-bound HTTP render service

**Files:**
- Create: `usfr-ui-render-sidecar/src/config.ts`
- Create: `usfr-ui-render-sidecar/src/python-runner.ts`
- Create: `usfr-ui-render-sidecar/src/render-pipeline.ts`
- Create: `usfr-ui-render-sidecar/src/server.ts`
- Create: `usfr-ui-render-sidecar/tests/server.test.ts`
- Create: `usfr-ui-render-sidecar/tests/render-pipeline.test.ts`

**Interfaces:**
- Consumes: `POST /v1/render` JSON and optional bearer token.
- Produces: exact contract echo, MP4 base64, output SHA-256, state sequence, motion-track SHA-256, model identity, and timing/cache receipts.

- [ ] **Step 1: Write failing readiness and render tests**

```ts
it('reports CPU-only dependency readiness', async () => {
  const response = await request(app).get('/readyz').expect(200);
  expect(response.body).toMatchObject({ready: true, cpu_only: true});
});

it('rejects a request whose canonical request hash is wrong', async () => {
  await request(app).post('/v1/render').send({...validRequest(), request_sha256: '0'.repeat(64)}).expect(422);
});

it('returns a bound real MP4 exactly once', async () => {
  const response = await request(app).post('/v1/render').send(validRequest()).expect(200);
  expect(sha256(Buffer.from(response.body.video_base64, 'base64'))).toBe(response.body.video_sha256);
  expect(response.body.motion_track_sha256).toMatch(/^[0-9a-f]{64}$/);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- tests/server.test.ts tests/render-pipeline.test.ts`

Expected: FAIL because the HTTP app and pipeline do not exist.

- [ ] **Step 3: Implement bounded render orchestration**

For each accepted request:

1. verify authorization before decoding media;
2. verify canonical request SHA and every media SHA;
3. create a request directory below `.runtime/jobs`, named exactly by `request_sha256`;
4. write target PNG, motion-reference MP4, and canonical contracts;
5. run Python once with a hard timeout;
6. run Remotion once with a hard timeout;
7. FFprobe the output;
8. return contract echoes and evidence digests;
9. retain only receipts on failure and clean transient media on success.

Map failures to stable codes such as `REQUEST_INVALID`, `MOTION_REFERENCE_INVALID`, `TRACK_EXTRACTION_FAILED`, `RENDER_FAILED`, and `OUTPUT_INVALID`. Never auto-retry.

- [ ] **Step 4: Add idle shutdown without affecting active requests**

Track `activeRequestCount` and `lastActivityAt`. Exit only when the configured idle timeout has elapsed and `activeRequestCount === 0`. Disable idle exit in tests with `USFR_UI_SIDECAR_IDLE_TIMEOUT_SECONDS=0`.

- [ ] **Step 5: Run server tests GREEN**

Run:

```powershell
npm test -- tests/server.test.ts tests/render-pipeline.test.ts
npm run build
```

Expected: all tests PASS and `dist/server.js` exists.

- [ ] **Step 6: Commit Task 4**

```powershell
git add usfr-ui-render-sidecar/src usfr-ui-render-sidecar/tests/server.test.ts usfr-ui-render-sidecar/tests/render-pipeline.test.ts
git commit --only -m "feat: serve evidence-bound UI renders" -- usfr-ui-render-sidecar/src usfr-ui-render-sidecar/tests/server.test.ts usfr-ui-render-sidecar/tests/render-pipeline.test.ts
```

### Task 5: Freeze FPS and ROI and send one source UI interval from USFR

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ui_interaction_contract.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\vision_backends.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ui_interaction_contract.py`
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ui_renderer_motion_reference.py`

**Interfaces:**
- Consumes: existing generated-UI region and `context.materialize_slot('source_video')`.
- Produces: interaction contract fields `source_fps` and `ui_roi`, plus one content-addressed motion-reference MP4 in the HTTP payload.

- [ ] **Step 1: Write failing UI contract tests**

```python
def test_contract_freezes_source_fps_and_pixel_roi():
    contract = build_source_ui_interaction_contract(region(ui_roi=[10, 20, 300, 500]), fps_num=30000, fps_den=1001, source_language="en", output_language="pt")
    assert contract["source_fps"] == {"num": 30000, "den": 1001}
    assert contract["ui_roi"] == {"x": 10, "y": 20, "width": 300, "height": 500, "coordinate_space": "display_pixels"}

def test_missing_roi_defaults_to_display_viewport():
    contract = build_contract(region_without_roi())
    assert contract["ui_roi"] == {"x": 0, "y": 0, "width": 1080, "height": 1920, "coordinate_space": "display_pixels"}
```

- [ ] **Step 2: Write the failing adapter test**

The test context exposes `materialize_slot('source_video')`, and the fake HTTP server records the request. Assert:

```python
assert payload["motion_reference"]["content_type"] == "video/mp4"
assert sha256(base64.b64decode(payload["motion_reference"]["video_base64"])).hexdigest() == payload["motion_reference"]["sha256"]
assert payload["motion_reference"]["source_ui_interaction_contract"] == render_contract["source_ui_interaction_contract"]
```

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_ui_interaction_contract.py tests/test_ui_renderer_motion_reference.py -q
```

Expected: FAIL because FPS, ROI, and motion-reference media are absent.

- [ ] **Step 4: Implement FPS/ROI validation and interval materialization**

The adapter must:

- materialize only `source_video`;
- trim only `source_window_us` with FFmpeg software decoding and `libx264`;
- produce the exact expected frame count from `frame_window`;
- keep the full viewport media but instruct the Sidecar to analyze only `ui_roi`;
- hash and base64-encode the trimmed MP4;
- keep the source materialization context open until the HTTP call returns;
- remove the temporary interval afterward;
- omit `motion_reference` for legacy calls without a source interaction contract.

- [ ] **Step 5: Run focused and existing adapter tests GREEN**

Run:

```powershell
python -m pytest tests/test_ui_interaction_contract.py tests/test_ui_renderer_motion_reference.py tests/test_real_capabilities.py tests/test_remotion_react_ui_activation.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 5**

Commit only the four UI files with `git commit --only`; do not include generated caches or unrelated Skill changes.

### Task 6: Add the lazy Sidecar process wrapper and USFR framework registration

**Files:**
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ui_sidecar_runtime.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_factory.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\__init__.py`
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ui_sidecar_runtime.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_packaged_factory.py`

**Interfaces:**
- Consumes: an `EvidenceBoundHttpUiRenderer`, project directory, Node executable, endpoint, startup timeout, idle timeout, and immutable manifest.
- Produces: `OnDemandUiSidecarRenderer.__call__`, `check_ready`, and `capability_identity`.

The test module defines `make_wrapper()` with an injected process factory and readiness probe, and `build_ports_for_route(route)` with a minimal replaceable `ocr_ui_renderer` adapter. These helpers contain no network or real process calls.

- [ ] **Step 1: Write failing lazy-start tests**

```python
def test_constructing_wrapper_does_not_start_process():
    wrapper = make_wrapper()
    assert process_factory.calls == []

def test_first_ui_call_starts_once_and_concurrent_calls_share_process():
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: wrapper(source, output_for(_), context, truth=truth, render_contract=contract), range(4)))
    assert process_factory.call_count == 1

def test_no_ui_and_opaque_routes_do_not_configure_sidecar(monkeypatch):
    ports = build_ports_for_route("opaque_ui_demo")
    assert ports["ocr_ui_renderer"].adapter.render_backend is original_backend
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_ui_sidecar_runtime.py tests/test_packaged_factory.py -q`

Expected: FAIL because the wrapper and optional registration do not exist.

- [ ] **Step 3: Implement the lazy wrapper**

Use an atomic startup lock file and readiness polling. The wrapper must never use `shell=True`, print environment variables, or launch before `__call__`.

Return a renderer decision:

```python
result["ui_renderer_decision"] = {
    "backend": "remotion_react_ui",
    "enabled": True,
    "reason": "eligible_generated_ui_started_on_demand",
    "renderer_identity": self.capability_identity(),
    "started_process": started,
}
```

- [ ] **Step 4: Register only when explicitly enabled**

`packaged_factory.py` reads:

```text
USFR_UI_SIDECAR_ENABLED=true
USFR_UI_SIDECAR_PROJECT_DIR=C:\Users\zhaocx04\Documents\New project\usfr-ui-render-sidecar
USFR_UI_RENDER_ENDPOINT=http://127.0.0.1:47821/v1/render
USFR_UI_RENDER_MODEL_ID=usfr-ui-remotion-opencv
USFR_UI_RENDER_MODEL_SHA256 is read from `sidecar-manifest.json` field `model_sha256`
USFR_UI_SIDECAR_STARTUP_TIMEOUT_SECONDS=90
USFR_UI_SIDECAR_IDLE_TIMEOUT_SECONDS=120
```

Registration creates the wrapper but does not call `check_ready` or start the service. Without `USFR_UI_SIDECAR_ENABLED=true`, the existing renderer remains byte-for-byte unchanged.

- [ ] **Step 5: Run focused tests GREEN**

Run:

```powershell
python -m pytest tests/test_ui_sidecar_runtime.py tests/test_packaged_factory.py tests/test_remotion_react_ui_activation.py -q
```

Expected: all tests PASS and process-start count is zero for bypass cases.

- [ ] **Step 6: Commit Task 6**

Commit only the new wrapper, factory registration, export, and focused tests.

### Task 7: Add immutable manifest, private configuration, and bundle purity checks

**Files:**
- Create: `usfr-ui-render-sidecar/sidecar-manifest.json`
- Create: `usfr-ui-render-sidecar/scripts/build-manifest.ts`
- Create: `usfr-ui-render-sidecar/scripts/start.ps1`
- Create: `usfr-ui-render-sidecar/.env.example`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\references\bundle_manifest.json`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\verify_bundle.py`
- Modify: `C:\Users\zhaocx04\Documents\New project\usfr-local-console\.env`

**Interfaces:**
- Consumes: built Sidecar source and composition bundle.
- Produces: a canonical SHA-256 identity used by USFR and the HTTP response.

- [ ] **Step 1: Write failing manifest tests**

Add a test that calculates SHA-256 for the canonical manifest and rejects a modified renderer file. Add a Skill bundle test that requires `server/ui_sidecar_runtime.py` but rejects `node_modules`, `.venv`, `.runtime`, `__pycache__`, and `.pytest_cache` inside the Skill.

- [ ] **Step 2: Run tests and verify RED**

Run the Sidecar manifest test and `python scripts/verify_bundle.py`.

Expected: FAIL because the manifest and new bundle entry do not exist.

- [ ] **Step 3: Generate the immutable manifest**

`scripts/build-manifest.ts` calculates every digest instead of accepting text values:

```ts
const identity = {
  schema_version: 'usfr-ui-sidecar-manifest/v1',
  model_id: 'usfr-ui-remotion-opencv',
  cpu_only: true,
  renderer_sha256: hashFiles(['src/render-pipeline.ts', 'src/remotion/render.ts']),
  extractor_sha256: hashFiles(['python/track_extractor.py', 'python/requirements.lock']),
  composition_sha256: hashFiles(['src/remotion/index.tsx', 'src/remotion/UiReplica.tsx', 'src/fonts.ts']),
};
const manifest = {...identity, model_sha256: canonicalSha256(identity)};
```

- [ ] **Step 4: Write non-secret configuration**

Generate a random local bearer token and write it only to the ignored private `usfr-local-console/.env`. Do not print it. Read `model_sha256` with `Get-Content sidecar-manifest.json | ConvertFrom-Json`, then write that exact value with the project path, endpoint, model ID, startup timeout, idle timeout, and `USFR_UI_SIDECAR_ENABLED=true`.

- [ ] **Step 5: Run manifest and bundle checks GREEN**

Expected: Sidecar identity test and Skill bundle verifier PASS; generated dependency folders remain outside the Skill.

- [ ] **Step 6: Commit Task 7**

Commit Sidecar manifest/scripts and Skill manifest/verifier only. Never commit the private `.env`.

### Task 8: Run real local end-to-end rendering and unaffected regression suites

**Files:**
- Create: `usfr-ui-render-sidecar/scripts/smoke.ps1`
- Create: `usfr-ui-render-sidecar/fixtures/target-ui.png`
- Create at runtime: `usfr-ui-render-sidecar/.runtime/smoke/source-ui.mp4`
- Create at runtime: `usfr-ui-render-sidecar/.runtime/smoke/output-ui.mp4`
- Create at runtime: `usfr-ui-render-sidecar/.runtime/smoke/receipt.json`

**Interfaces:**
- Consumes: installed Sidecar, generated motion fixture, exact multilingual truth, and the real USFR HTTP adapter.
- Produces: one accepted MP4, one evidence receipt, timing metrics, and bypass proof.

- [ ] **Step 1: Write the failing end-to-end smoke test**

The smoke test must:

1. generate a 24-frame source UI video containing drag, bounce, scale, rotation, opacity, and tap feedback;
2. generate a target UI image with new product/model pixels;
3. submit through `OnDemandUiSidecarRenderer` and `EvidenceBoundHttpUiRenderer`;
4. assert the response hashes and state order;
5. FFprobe the final MP4;
6. sample first, middle, and last frames for nonblank pixels;
7. confirm Chinese, Arabic, Portuguese, and English strings contain no replacement glyphs or `??` runs;
8. instantiate non-UI and `opaque_ui_demo` contexts and prove no Sidecar process starts.

- [ ] **Step 2: Run smoke and verify RED before final wiring**

Run: `powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1`

Expected: FAIL until the built manifest, private configuration, and USFR wrapper are connected.

- [ ] **Step 3: Complete only the wiring required by the failing smoke**

Do not add new routes or fallback generation. Correct endpoint, manifest identity, startup command, and fixture contracts until the real adapter accepts the returned video.

- [ ] **Step 4: Run all Sidecar tests and real smoke GREEN**

Run:

```powershell
npm test
npm run typecheck
npm run build
.\.venv\Scripts\python.exe -m pytest python/tests -q
powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1
```

Expected: all commands PASS; `output-ui.mp4` and `receipt.json` exist.

- [ ] **Step 5: Run focused and broad USFR regression suites**

Run:

```powershell
python -m pytest tests/test_ui_interaction_contract.py tests/test_ui_sidecar_runtime.py tests/test_ui_renderer_motion_reference.py tests/test_remotion_react_ui_activation.py tests/test_packaged_factory.py tests/test_real_capabilities.py -q
python -m pytest tests -q
python scripts/verify_bundle.py
```

Expected: focused suites PASS, full suite PASS, and bundle purity PASS. If the full suite has a pre-existing unrelated failure, record it separately with the exact test and do not modify unrelated code.

- [ ] **Step 6: Verify process lifecycle and CPU-only behavior**

Record process lists before a non-UI call, after the eligible UI call, and after the idle timeout. Verify:

- no Sidecar Node process exists before the UI call;
- exactly one Sidecar process serves the UI call;
- no CUDA/NVENC arguments or GPU processes are used;
- the Sidecar exits after the configured idle timeout;
- no automatic second render request appears in receipts.

- [ ] **Step 7: Commit Task 8**

Commit only smoke scripts and durable fixtures. Do not commit `.runtime`, generated MP4s, tokens, `node_modules`, or `.venv`.

## Final Verification Report

Report:

- installed Node, npm, Python, OpenCV, Remotion, FFmpeg, and font versions;
- Sidecar project path and local URL;
- final output MP4 absolute path;
- output SHA-256, duration, dimensions, FPS, and frame count;
- motion-track and model SHA-256 values;
- startup time, extraction time, render time, and cache-hit state;
- targeted and full USFR test results;
- proof that bypass routes did not start the process;
- proof that execution was CPU-only;
- any remaining evidence-dependent limitations without claiming pixel perfection where target state evidence is missing.
