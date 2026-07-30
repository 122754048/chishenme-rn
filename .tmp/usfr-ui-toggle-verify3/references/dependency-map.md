# Dependency Map

The top-level dependency is the universal `Source Fidelity Contract` in
`references/universal-source-fidelity-contract.md`. It is frozen before any
generation and is the handoff schema shared by every module below.

The factory vendors four single-purpose skills under `bundled-skills/`.

Before the module graph runs, `scripts/bind_input_slots.py` freezes the fixed
seven-slot manifest. It is required for every formal run and enforces
`source_video` plus at least one fixed change input: either one valid optional
slot or a valid `output_language` for language-only localization. It performs
no AI role classification.

| Module | Required when | Main outputs |
| --- | --- | --- |
| `parse-app-store-evidence` | Official App Store URL supplied and a generated UI/target-evidence carrier remains | Evidence bundle, official icon/screenshots, hashes |
| `analyze-reference-video-dynamics` | Any supported source video supplied | Probe, frame-accurate scene/camera/action/audio contract |
| `replicate-source-ui-overlays` | Timed overlays must be semantically replicated | Overlay geometry and QA frame plan |
| `seedance-storyboard-replication` | Any generated region remains after routing | Intent, scripts, storyboards, RunningHub Standard Model Seedance, assembly, QC |

The installed external `seedance-20` skill is an additional mandatory
dependency for final Prompt recompilation and the internal request-integrity
audit. It is not one of the four vendored modules. If `seedance-20` is missing
or cannot produce valid compiler provenance, contract digests, complete factor
coverage, `ambiguities=[]`, and `unresolved_placeholders=[]`, the Factory must
block before any paid Seedance request. This dependency does not change the two
user approval types, fixed-B RunningHub Standard Model parameters, caching/concurrency rules, or
duplicate-paid-task protection.

`scripts/skill_router.py` is the deterministic dependency planner for the
high-fidelity profile. It consumes only frozen analysis flags, selects the
smallest required set of bundled and injected Seedance modules, and emits a
canonical route digest plus package-relative dependency snapshot. Workers
resolve that snapshot from the deployed image or a tenant-private immutable
artifact and verify exact bytes before Invocation A or B. The router does not
add a stage, approval, provider call, or public input field.

App intervals are located from source dynamics and routed from the manifest:
`opaque_ui_demo` when a UI operation video is supplied,
`generated_ui_demo` when a UI screenshot or App Store URL is supplied without
that video, and `source_ui_keep` when all three UI slots are absent. A supplied
tail card is opaque replacement media with leading/trailing black auto-trim and
an effective-duration terminal endpoint; a missing tail card uses
`omit_source_end_card` and is absent from final assembly. Source-origin UI media
is excluded from script/storyboard/Seedance and receives only deterministic
timeline assembly. The opaque
UI/tail/source branch and semantic overlay replication are mutually exclusive
for the same source interval. Evidence and dynamics are cached once per run.
When routing produces zero generated regions, App-store parsing and all
commercial/voiceover/Seedance analysis that cannot affect local assembly are
recorded as skipped; no network fetch or second semantic pass is permitted.

`USFR_UI_REBUILD_ENABLED=false` is the default automatic-rebuild guard. Without
explicit target UI evidence, product/model/language replacement keeps detected
source UI intervals and skips OCR, App Store parsing, and UI rendering. A UI
screenshot or official store URL always enables the target-UI route, while a
UI operation video always remains the higher-priority opaque splice route.
The factory owns the internal Seedance integrity gate, autonomous submission,
provider waiting, assembly, and QC; the Seedance module supplies implementation
details.

For deployment, `server/` is the authoritative application boundary around
these modules. The HTTP adapter and durable repository own run state,
approvals, idempotency, provider intents, leases, and outbox events; bundled
CLI scripts are worker adapters and may not mutate the top-level run state
directly.

`server/seedance_invocations.py` is the worker-side A/B bridge: it loads the
packaged `seedance_prescript.py` and exact-line contract without depending on
the worker's current directory, validates the same `seedance-20` byte snapshot
at both boundaries, and for active profiles compiles/validates a structured
prompt request through the packaged `seedance_prompt_compiler.py` rather than
accepting a raw prompt bypass. It performs deterministic prompt length, line,
Cut, shot-coverage, no-speech, and route-leakage checks. It never calls a
provider. A provider adapter remains a
separate injected port and is reached only after the existing paid-request
integrity gate.

`server/high_fidelity_ports.py` embeds that bridge inside the existing
`build_script` and `compile_seedance20_prompt` handlers. Profile-disabled runs
short-circuit those internal handlers, preserving the legacy route without
adding hidden work or a new stage.

`server/capability_ports.py` is the executable deployment boundary for the
seven declared capabilities. `validate_runtime_capability_ports` binds real
server/container adapters to the immutable manifest identity; direct
`CapabilityStagePort` handlers execute dynamics+ASR, generated-UI rendering,
compositing, and QC, while `BoundStagePort` preserves the existing script/
prompt handlers for the dual-stage Seedance bridge. It rejects generic
callables, local artifact references, empty/status-only sidecars, OCR/layout
results below 100%, and mismatched adapter bytes before stage publication.
