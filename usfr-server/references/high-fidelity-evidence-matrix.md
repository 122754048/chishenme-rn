# High-Fidelity Capability Evidence Matrix

Snapshot: 2026-07-21  
Profile: `high_fidelity_hybrid_v1`

This matrix distinguishes executable evidence from contract-only declarations.
It is an audit aid; it does not add a public slot, route, stage, approval, or
Provider task.

## Status definitions

- **已证实** — executable code and a focused test/receipt exercise the
  behavior at the stated boundary.
- **仅间接** — a schema, prompt field, hash, or caller-supplied score exists,
  but no independent source/output comparison or default producer proves the
  behavior.
- **缺失** — no executable implementation/evidence exists in the bundled
  server path.

## Capability matrix

| Capability | Current evidence | Status | Remaining boundary |
|---|---|---:|---|
| Source Cut/frame-zero-to-end timing | FFprobe/FFmpeg decoder coverage; VLM response must echo source/frame hashes and contiguous Cuts; `FfmpegDynamicsAnalyzer` and `EvidenceBoundHttpVlmBackend` tests | 已证实 | Semantic quality still depends on the injected VLM model. |
| Background/scene topology | High-fidelity extension schema validates entities, spatial relations, occlusion, negative space, lighting, and framing anchors | 仅间接 | No independent decoded output-vs-source scene/background similarity evaluator. |
| Camera/framing/movement | Source extension and Invocation-B shot contract require camera fields, factor IDs, and continuity | 仅间接 | No independent target camera trajectory/shot-scale comparison. |
| Character identity/performance | Character slot is fixed and prompt/reference-role/character-lock digests are audited; `seedance-characters` is routed when factors require it | 仅间接 | No default face/body/wardrobe/gesture identity evaluator on final media. |
| Product/prop identity and hand interaction | Product slot digest, product lock, affordance/layer ledgers, and prompt factor coverage are validated | 仅间接 | No default product visual/geometry/contact-point comparison against final decoded frames. |
| Atomic action and completed endpoint | Extension validator requires phase coverage, hand ownership, contact points, state sequence, and completed endpoint; Invocation-B validates shot action/endpoint fields | 仅间接 | No independent target action-chain measurement; shadow metrics remain deployment evidence. |
| Voice wording/timing/lip-sync | Pinned Whisper/evidence-bound ASR, exact line contract, segment windows, Foley/silence mappings, and prompt parity gates | 已证实（内容/时序） | Timbre, prosody, loudness, and delivery similarity are not independently compared. |
| Voice tone/prosody/acoustic identity | Audio contract retains ASR/audio-event receipts | 缺失 | Add a deployment-owned voice/prosody comparator before claiming tone fidelity. |
| Selling-point migration | Claim atoms, target value graph, affordance ledger, `Feature → Mechanism → Benefit → Proof → CTA`, unsupported-claim removal, and script projection are schema/tested | 仅间接 | No default target-product/app fact extractor or independent proof-to-output evaluator. Production analysis evidence now requires bound artifact SHA-256. |
| Overlay/logo/CTA replacement | Bundled overlay contract, deterministic text/asset renderer, render receipts, and mapping/receipt tests | 已证实（supported static geometry） | Moving/nonlinear trajectories require a dedicated renderer; unsupported mappings fail closed. |
| Supplied UI operation video | Opaque splice/timeline contracts and real-media splice/QC tests | 已证实（media boundary） | Visual quality remains dependent on the supplied media and transition backend. |
| Generated UI from screenshot | Independent OCR truth derivation, immutable `ui_truth_card`/`ui_render_contract`, real video renderer requirement, state/animation OCR/layout receipts | 已证实（contract and boundary） | Multi-state truth still requires deployment renderer/evidence; one-state fallback is intentionally conservative. |
| App Store URL-only UI route | Official bundled parser, parser-before-UI stage order, screenshot SHA verification, runtime parser fallback, and focused tests | 已证实 | Parser/network availability remains a deployment dependency. |
| App tail-card supplied | Opaque interval contract, edge-black trim policy, duration manifest, transition receipts, and timeline tests | 已证实（contract/technical media) | No semantic inspection is intentionally allowed. |
| App tail-card absent | `omit_source_end_card` route exclusion documented and local assembly path skips script/storyboard/provider | 已证实（routing) | Classification quality depends on the dynamics/route adapter. |
| Route 1 / Route 2 approval count | Existing state machine and stage plan retain storyboard-only Route 1 and script+storyboard Route 2; approval tests | 已证实 | Human approval semantics remain external UI responsibilities. |
| Server/object-store deployment | Fixed slots, Redis CAS, lease fencing, artifact receipts, bundle verifier, Docker handoff, and full suite | 已证实（boundary) | Real Redis/object store/provider/VLM/ASR/UI sidecars must be injected by deployment. |

## Contract closure recorded without activation claims

The production timeline contract now requires frozen Segments and Cuts to form
one global closed set with unique ordered membership; ordinary generated media
cannot bypass exact Segment/Cut bindings. Provider/generated UI/opaque UI/tail
carriers use natural decoded media duration with no padding, freeze, loop, or
hidden retime, and per-Segment audio/video boundaries align before concat.

The contract requires every non-source carrier and every declared source transition to have an exact
final-output-bound receipt tying the selected slot/artifact, Segment, canonical
plan digest, canonical source shell, and current final MP4 SHA-256. Receipts
require that source and omitted routes reject any media binding, and manifest
route, placement, and omission sets are exact. The production loader accepts only absolute paths to
bundled timeline and concat dependencies.

These rows record fail-closed contract and receipt boundaries only. They do not
claim a deployed renderer, provider, semantic comparator, or real production
effect; the profile remains Shadow until deployment-owned evidence and matched
activation gates pass.

## P1 hardening completed in this snapshot

The deterministic technical QC layer now records low-resolution FFmpeg
`freezedetect` intervals alongside the existing one-frame black scan and binds
video/audio stream start timestamps separately from duration. The server hard
gate applies freeze failures only to generated/opaque carrier intervals that
are not covered by a source/user-upload lineage window; static source shots and
static supplied tail/UI media are not misclassified as assembler padding.

This does not close semantic audio fidelity: final-MP4 ASR/line alignment,
prosody/timbre comparison, source-voiceover mixing across opaque regions,
LUFS/true-peak/click checks, and protected audio-window mapping remain
deployment-owned evidence. The profile stays Shadow until those receipts and
the matched A/B/regression gates are present.

The active VLM evidence boundary is temporal as well as cryptographic. Every
source and semantic Cut must cite a decoded sampled frame in its own half-open
time range. When repeated identical pixels share one SHA across multiple
timestamps, the sidecar must carry the matching `timestamp_us`; a bare digest
is treated as ambiguous and rejected. If the configured frame budget cannot
place a sample inside every source Cut, the active run fails closed before
semantic facts are accepted. Shadow/legacy adapters retain their compatibility
behavior and are not activation evidence for this boundary.

The production compositor also distinguishes a semantic overlay layer pass from
complete timeline assembly. `FfmpegCompositor` fails closed when a timeline
contains any `media_origin != source_interval` region without an injected
complete timeline renderer. The bundled `DeterministicOverlayRenderer` is a
source-origin semantic layer pass only; it remains valid only for
source-origin-only timelines and cannot authorize generated or opaque carrier
pixels.

High-fidelity analysis evidence previously required only an object key. In an
active production profile, `server.high_fidelity_projection` now requires every
nested analysis evidence record to carry a lowercase `artifact_sha256` that
matches a digest already authorized by a fixed input slot or a published
upstream artifact. Shadow/legacy/local-development compatibility is unchanged.
This prevents a fabricated source/target evidence object from reaching
Invocation A solely because its object key looks plausible.

The optional `artifact_sha256` field is declared in
`schemas/high_fidelity_analysis.schema.json`; production enforcement is at the
server boundary rather than in the public intake schema.

The assembled-media and deployment boundaries are independently bound as
well. Active weighted QC records `media_bindings` and requires each dimension
and factor evidence set to reference the current run's source artifacts plus
the current final MP4 SHA-256. Stale output or foreign-source evidence is
rejected before publication. Transition receipts are finalized against the
same output bytes; a stale receipt fails with
`TRANSITION_OUTPUT_SHA256_MISMATCH`, while a missing digest is filled only
after the current render completes. Active/production startup also requires
the service and Worker to expose matching `profile_snapshot` and
`stage_capability_manifest` digests, so configuration drift cannot wait until
the first paid stage.

Active production weighted QC now has an independent evaluator boundary for
all production QC StagePort implementations, including
`FfmpegQcEngine(production=True)`. The stage preserves
`qc_evaluator_response`; the returned
`high-fidelity-qc-evaluator-receipt/v1` is checked against the canonical request
and response SHA-256 values, evaluator/model identity, current final/source
media set, and dimensions/factor digests. Missing or stale receipts produce a
blocked diagnostic result and cannot publish a technical-only pass. A real
HTTPS semantic evaluator remains a deployment-injected dependency; the bundled
package supplies the contract and tests but does not claim a local comparator or
independent visual similarity coverage for the matrix rows above.
The deployable transport reference is
`server.vision_backends.EvidenceBoundHttpSemanticQcEvaluator`; it is configured
with `USFR_QC_EVALUATOR_ENDPOINT`, `USFR_QC_EVALUATOR_MODEL_ID`, and
`USFR_QC_EVALUATOR_MODEL_SHA256`, sends `media_base64`/sampled evidence bytes,
and never sends a worker path. The actual HTTPS semantic model remains a
deployment dependency.

## Evidence commands

Focused TDD and regression commands:

```powershell
$env:PYTHONPYCACHEPREFIX='C:\\temp\\usfr-pycache'
python -B -m pytest -q -p no:cacheprovider `
  tests/test_high_fidelity_projection.py `
  tests/test_high_fidelity_analysis.py `
  tests/test_high_fidelity_ports.py
python -B scripts/verify_bundle.py .
```

The full Skill suite is expected to run without writing caches into the bundle;
the final delivery gate remains `verify_bundle.py`.
