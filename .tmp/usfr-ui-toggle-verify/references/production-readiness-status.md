# Production-readiness status

As of 2026-07-21 the `high_fidelity_hybrid_v1` profile remains `Shadow`.

Verification update (2026-07-21): the cache-free release audit passes
`1142 passed, 1 skipped`; Ruff reports `All checks passed!`; and the bundle
verifier returns `bundle is valid` both before and after the test suite. Its
independently rerun Bundle-closure subset contains `3` Bundle-closure tests.

Current executable evidence includes two different real MP4 checks:

- an in-process control-flow MP4 proves source intake, script revision and
  approval, storyboard revision and approval, supplied UI, supplied tail,
  Provider-carrier handling, assembly, QC, final promotion, and cleanup with
  only `final/{job_id}/result.mp4` retained;
- a real-material canonical splice MP4 proves supplied UI and supplied tail use
  their natural active durations, source UI/tail removal, audio/video
  cross-transition assembly, no leading/trailing/splice-window black frame,
  no detected freeze, and no tail padding to the source duration.

These MP4s are deterministic control-flow and compositor evidence. They are
not ad-grade quality evidence for generated character/product replacement,
semantic fidelity, generated-UI OCR/layout, acting, camera, voice, Foley, or
localised selling-point quality.

Container execution remains unverified on this workstation because Docker and
WSL are unavailable. Real video generation also remains blocked until a
packaged `USFR_PORT_FACTORY` and deployment-owned Seedance Provider, OCR, VLM,
ASR/audio-event, generated-UI renderer, semantic-QC evaluator, and required
model credentials are injected.

Verified in the bundled worker package:

- functional contract/regression suite: 1142 passed and 1 skipped, including
  the 3 Bundle closure tests, executed with cache-free commands;
- bundle self-containment: `bundle is valid` with no cache directories;
- object-completion intake now binds an exact owned `uploads/{upload_scope}/`
  namespace to the Redis job and verifies store metadata before admission. The
  language-only object upload route no longer bypasses binding, and cleanup
  removes the owned upload namespace plus job temporaries while failing closed
  if the upload lifecycle adapter is unavailable;
- the primary bundle audit composes a release-time lightweight verifier that
  rejects legacy SQL/product control-plane files, tenant/account/Outbox
  bindings, workstation Skill paths, and generated cache directories;
- the optional backend policy remains default-disabled. HyperFrames, Remotion,
  Video-use-derived QC, and MediaBunny may become eligible only through
  same-case evaluator receipts proving higher average quality, or lower P95
  time with no minimum-quality or hard-gate regression. A boolean capability
  flag cannot activate an optional compositor, and the benchmark tool cannot
  mutate production policy;
- shadow matrix: 26 cases, zero Provider calls, zero Invocation A/B calls,
  zero approvals, zero paid tasks;
- deterministic FFmpeg compositor/QC and real Whisper adapter contracts;
- strict failure for missing OCR/VLM/ASR/audio-event backends, unpinned model
  artifacts, self-consistency UI scoring, fake artifact hashes, stale prompt
  artifacts, forged publication receipts, and stale stage/profile identity;
- evidence-bound OCR/VLM/audio sidecar contracts with exact media/model hashes,
  frame-zero-to-end semantic coverage, and no worker-path transport.
- `server.vision_backends.EvidenceBoundHttpSemanticQcEvaluator` now provides
  the deployable private-HTTPS transport boundary for the existing QC StagePort:
  it sends final-media/optional sampled-evidence bytes as base64, never a worker
  path, and validates `qc_evaluator_response` plus the
  `high-fidelity-qc-evaluator-receipt/v1` envelope. The external semantic model
  and comparator remain deployment-owned and are not claimed as bundled quality
  evidence.
- `server.orchestrator.build_semantic_stage_mapping` proves that operational
  evidence/approval/provider entries map to the frozen 12 semantic stages;
  deferred target truth is explicitly reported without adding a RunState stage,
  approval, route, or Provider task.
- active/default profile boundaries now consistently require immutable bundle
  resolution, including the Seedance Invocation adapter and service profile
  snapshot validation.
- deployment-owned `USFR_DEPLOYMENT_FACTORY` bootstrap with `/healthz` and
  `/readyz`, plus a default Shadow worker bootstrap, is contract-tested;
  Docker image build itself remains unexecuted here because no container CLI is
  installed.
- the source bundle now includes an isolated Docker `e2e` target, packaged
  deterministic stage/capability ports, and a Python Jobs API driver covering
  real MP4 upload, Redis Worker execution, two approvals, MinIO assembly/QC,
  `CleanupSweeper`, black-frame rejection, and final-only retention. The final
  production target is declared after the E2E copy and excludes those fake
  ports. This harness is source-contract-tested but remains unexecuted until a
  Docker/WSL host is available, so it is not counted as real-model or ad-grade
  evidence.
- assembled-video publication receipts now flow into the following QC stage;
  elastic UI/tail duration uses the compositor manifest, single-frame black
  flashes are rejected, and unsupported `radial_zoom_blur`, `zoom_out`, and
  `zoom_back` transitions fail closed instead of claiming `hblur`/fade
  approximations.
- active semantic-overlay assembly now requires renderer receipts bound to the
  source overlay contract SHA, target mapping SHA, payload SHA, frame windows,
  and final output SHA; the positive compositor-to-timeline-to-QC bridge and
  copy-only fail-closed regression are covered.
- Stage-4 now has a deterministic overlay mapping builder and the bundled
  renderer paints both approved text and immutable target image assets;
  moving text geometry is rendered through frame-evaluable trajectories while
  unsupported rotating text fails closed. Asset receipts bind payload/asset
  SHA to the final output.
- QC black detection is boundary-aware when a compositor manifest exists:
  declared internal black content is preserved, while edge and splice-window
  full-black frames remain hard failures. Sparse black-background logos are
  active content because the detector uses `pic_th=1.0`.
- `probe_source` output is reused by dynamics/QC through the lease-owned cache
  boundary; stale or malformed cached probe evidence fails closed instead of
  silently re-probing changed media.
- generated UI multi-state evidence binds every declared state to decoded
  frame SHA, OCR/layout input SHA, text, and layout records. Encoded PNG/JPEG
  OCR inputs additionally bind `decoded_frame_sha256` separately from the
  backend `input_sha256`; active generated UI still requires a real video
  renderer and ordered per-state evidence.
- `server.vision_backends.EvidenceBoundHttpUiRenderer` now supplies the
  deployable HTTPS renderer boundary: target bytes, UI truth/render contract,
  ordered states, request/source/model/output hashes, MP4 probing, and a
  renderer readiness probe. The actual tenant-side renderer model and its
  activation evidence remain deployment responsibilities.
- Invocation-A now has a lease-owned monotonic deadline/metric path inside the
  existing `build_script` stage. Active/production bootstrap rejects a missing
  timing sink, and `ProductionTiming` accepts nested Invocation-A observations
  without opening a second stage. Success, failure, timeout, and local-only
  skipped paths are covered by runtime tests.
- Opaque UI/tail assembly now carries an explicit audio policy: target audio is
  preserved by default, `silence_allowed` injects a bounded silent stream for a
  genuinely silent upload, and `evidence_bound_mix` uses the bundled FFmpeg
  mixer only when the timeline renderer declares that immutable capability.
  The mixer preserves frozen overlapping source-speech windows, ducks existing
  opaque audio, keeps the target's natural active duration, and emits canonical
  source/opaque/mixed/final SHA lineage. Generic renderers still require a
  current pre-bound receipt, explicit upstream blocked decisions remain
  blocked, and every deferred receipt is validated one-to-one before
  publication. The publication boundary independently re-decodes current
  source, opaque-active-window, and mixed-carrier PCM before recomputing WAV
  and request digests; mixed pre-bound/deferred regions retain per-region
  immutable mixer identities. Final manifests use field/root-aware path
  sanitization, preserve semantic App routes and object-store URIs, reject
  worker/temp/file URIs, and complete canonical preflight before the first
  publisher side effect. Replacement active-window and transition frame math
  remains bound to replacement/source FPS rather than the output canvas FPS.
- activation evidence validation now rejects summary-only/self-attested reports:
  production requires immutable report SHA/receipt envelopes, a server-owned
  receipt verifier, and server-recomputed shadow/A-B/regression aggregates.
- active Invocation-A projection now rejects any source/target evidence record
  without a trusted fixed-slot or published-artifact SHA-256, using the
  `EVIDENCE_DIGEST_UNBOUND` blocker; the schema and evidence matrix carry the
  same production boundary.
- active weighted QC now binds every dimension/factor evidence set to the
  current run's source artifact set and the decoded current final MP4 SHA-256. Stale
  output or foreign-source evidence is rejected before a high-fidelity pass;
  the immutable report records `media_bindings`.
- active production weighted QC now invokes a deployment-owned independent
  evaluator. The server recomputes canonical request/response SHA-256 values
  and verifies evaluator/model identity, final/source media bindings, and
  dimensions/factor digests; missing evaluator/receipt or stale evidence
  returns a blocked diagnostic result and cannot publish a technical-only pass.
- the semantic-stage audit now binds product/model/UI image slots to the
  target-truth boundary at deterministic intake, while App Store evidence may
  remain deferred until generated-UI routing is proven. Deferred reporting
  names semantic stage 2 itself rather than mislabeling the earlier dynamics
  or route entries. The HTTPS QC adapter also rejects a supplied request
  payload whose final/source/input artifact digests differ from the actual
  media and current Run before contacting the evaluator.
- transition receipts are finalized against the actual assembled MP4 SHA-256;
  a stale receipt fails with `TRANSITION_OUTPUT_SHA256_MISMATCH`, while a
  missing digest is populated only after the current output has been rendered.
- active/production bootstrap requires the service and Worker to expose the
  same `profile_snapshot` and `stage_capability_manifest` digests, rejects
  local-path workers, and ships an overridable Docker `CMD` so HTTP and queue
  deployments use the same image boundary.
- real-media acceptance now passes 56 splice/QC tests, including elastic UI
  and tail duration, boundary black-frame rejection, sparse black-background
  tail content, audio/A-V drift, transition receipt binding, and the production
  evaluator request/response receipt gate.
- deterministic FFmpeg final-media QC now records `freezedetect` intervals and
  applies a lineage-aware hard gate for generated/opaque carrier freezes at
  output edges or splice windows; static source/user-upload holds remain
  diagnostic/allowed only inside their declared placement windows. Stream
  start timestamps are checked independently of duration and large offsets
  fail with `AUDIO_VIDEO_START_OFFSET`.
- non-hard transition audio now consumes the declared `audio_fade_duration`
  instead of silently using the visual overlap; the left audio stream is
  trimmed to the exact audio crossfade window and the receipt binds that value.
- timeline normalization now uses an explicit `libx264` `CRF=18`/`veryfast`
  intermediate instead of the codec default, reducing UI/text loss while the
  existing single authoritative assembly path remains unchanged.
- production-active final-audio delivery now fails closed when the frozen final
  timeline requires audio but its canonical contract/evidence is absent. The
  executable gate accepts immutable manifest/stage/artifact/evaluator records,
  binds them to the decoded current final MP4 SHA-256, and validates exact
  lines/timing/language, delivery/lip-sync where applicable, Foley, ambience,
  meaningful silence, LUFS, true peak, boundary sample jumps, stream start,
  and terminal drift. Stale output evidence is rejected, while Shadow/local
  runs keep the prior opt-in behavior. This closes the server gate, not the
  deployment evidence: a real ASR/audio-event/lip-sync/loudness evaluator and
  model receipts still must be injected and exercised on the release cases.
  The bundled source-voiceover/opaque-audio executable path and its immutable
  lineage receipts are now closed at the server boundary. Real ad-quality
  validation remains open: release cases still need independent listening and
  measured evidence for speech intelligibility, natural ducking, ambience,
  loudness/true peak, and boundary quality. `high_fidelity_hybrid_v1` therefore
  remains `Shadow`.
- production compositor carrier guard now rejects using the bundled semantic
  overlay renderer as a generated/opaque timeline assembler; source-origin-only
  overlay passes remain allowed. `server.timeline_renderer.BundledTimelineRenderer`
  now provides the bundled complete timeline renderer (an FFmpeg timeline
  carrier), resolving
  lease-local source/generated/opaque media and sanitizing ephemeral paths;
  deployments still need to inject the object-store materializers/publisher
  and validate the renderer identity.
- active VLM semantic/source evidence is Cut-local as well as hash-bound: every
  Cut must cite a decoded sampled frame inside its half-open time range; a
  repeated frame SHA spanning multiple Cuts requires `timestamp_us`, and an
  uncovered Cut or foreign/ambiguous sample fails closed before the semantic
  extension is accepted.
- the internal `high-fidelity-analysis-envelope` now keeps strict semantic
  analysis separate from raw dynamics/ASR sidecars, verifies component and
  current-run parent digests, and carries one immutable `projection_sha256`.
  Invocation A and B use that same digest and compare every rich shot field and
  factor ID; raw dynamics cannot be promoted by schema coincidence.
- structured Prompt route exclusion now scans mapping keys, values, factors,
  locks, reference roles, shot fields, and negative constraints. Separator and
  camelCase normalization use consecutive token-boundary matching rather than
  compact substring matching, so route carriers are blocked without rejecting
  ordinary phrases such as `detail video` or `resource interval`. The compiler,
  Invocation B, payload builder, and paid `CreateVideo` client all fail closed
  before network submission. `generated_ui_demo` and opaque UI/tail routes stay
  in deterministic renderer/timeline assembly and never enter the semantic
  script, storyboard, Seedance prompt/assets, or paid generation duration;
  legacy `ui_demo`/`tail_card` snake_case, kebab/space, and camelCase route
  markers are also blocked at compiler/Invocation/provider boundaries.
  Invocation-A projection now uses an explicit ordinary-generated region,
  media-origin, and assembly-policy allowlist, so unknown future route aliases
  cannot enter Seedance merely by declaring a generated media origin.

The configured release catalog contains 36 cross-category cases. Normal change
validation uses incremental smoke/impact selection with the fixed six-case
smoke set and exact dependency-fingerprint reuse; it does not regenerate all
36 cases after every change. The profile must not be promoted to
production/default until one 36-case immutable release candidate runs through
the real packaged Provider/model stack and passes every quality and hard gate.
At this checkpoint all 78 referenced fixture assets are absent from the
deployable tree by design, and no private object-store fixture set has been
attached; the catalog is therefore coverage configuration, not executed
quality evidence.

The immutable case-result gate now rejects local fixture placeholders, missing
or reused release cases, stale dependency fingerprints, foreign source/final
media receipts, route/timeline values below 100%, generated-UI or readable-text
OCR/layout below 100%, total scores below 85, high-critical factors below 90,
and any Claim or hard failure. Incremental reports must execute the selected
impact plus fixed-smoke cases and may reuse only an exact dependency match.
The bounded case-matrix runner now drives the existing Jobs API, automates the
catalog-declared 2/1/0 approval route, keeps Job and evaluator credentials
separate, fails fast on hard gates, and writes a per-case checkpoint before a
later case can fail. It remains a release-only tool outside the runtime image.
The private fixture builder now computes actual media SHA-256 values, probes
and rejects videos over 30 seconds, performs byte-level deduplication, and
requires verified Publisher receipts. Its outputs replace local fixture names
with private object keys and cannot contain workstation paths.

A real OCR model, semantic/VLM backend, Seedance Provider, generated-UI
renderer, independent semantic-QC evaluator, and Foley/ambience classifier must
be injected into the server capability map before those cases can be counted.
Composite capability identities propagate nested model/renderer digests through
`BoundRuntimeCapability` into the frozen manifest and dedupe key; real model
E2E evidence and the activation gates remain outstanding.
