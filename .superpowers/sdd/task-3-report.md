# Task 3 Report — approved audio-line bindings

## Changes

- Added source-content-timeline, content-type, and confirmed speaker-assignment validation to exact line contracts; these values are frozen during script revision validation.
- Extended performance-line contracts with `line_id`, source timeline SHA, content type, and speaker assignment.
- Made Invocation A (`build_source_audio_contracts`) require canonical approved lines and the source-content-timeline SHA, bind line/Cut/speaker/text/global+segment windows, and enforce one-to-one generated-region coverage.
- Made Invocation B repeat the same one-to-one validation before prompt compilation/validation.
- Kept source-audio performance in the existing script-draft path as `PENDING_CONFIRMATION` candidate evidence; it no longer publishes a final performance contract before script confirmation.

## RED / GREEN evidence

- RED: `python -m pytest tests/test_line_contract.py tests/test_performance_audio_contracts.py tests/test_seedance_prompt_compiler.py -p no:cacheprovider -q` initially produced 3 expected failures for unblocked `PENDING_ASSIGNMENT`; after additional binding tests it produced 7 expected failures (missing confirmed-assignment and performance text binding).
- RED: Invocation-A binding test initially failed with `TypeError: build_source_audio_contracts() got an unexpected keyword argument 'line_contracts'`.
- RED: mixed source-content-timeline test initially failed because no common timeline SHA was enforced.
- GREEN: focused Invocation-A suite passed with `12 passed`.

## Final verification

```text
python -m pytest tests/test_line_contract.py tests/test_performance_audio_contracts.py tests/test_seedance_prompt_compiler.py -p no:cacheprovider -q
72 passed in 2.09s

python -m pytest tests/test_production_ports.py::test_creative_planner_keeps_source_audio_performance_as_pending_script_candidates -p no:cacheprovider -q
1 passed in 0.57s

git diff --check
exit 0 (only repository CRLF conversion warnings)
```

## Self-review / external review

- Initial external review found two P1 issues: Invocation A did not receive approved line contracts, and generated-region coverage was cardinality-only.
- Both were fixed with canonical-line/timeline inputs and consumed-region coverage checks.
- The legacy draft-stage final-contract construction was changed to candidate-only evidence, preventing unconfirmed GPT performance rows from reaching a final contract.

## Concerns

- The final materialization interface now requires confirmed `line_contracts` plus a frozen source-content-timeline SHA. The existing draft stage intentionally lacks those user-confirmed inputs and therefore retains candidates only; the downstream confirmation/recovery caller must invoke the new binding interface once it has the approved rows.

## Recovery integration

- Script approval now atomically writes a canonical `approved-script-lines/v1` sidecar in the existing Redis revision CAS. It binds the exact revision, approved script SHA, frozen source-content-timeline SHA, canonical line rows, and their canonical SHA; HTTP approval writes only this JobStore state.
- The existing `build_script` checkpoint is re-enqueued once after a matching CAS sidecar changes its approval-sensitive dedupe key. The semantic adapter then materializes final exact/performance contracts through the existing stage rather than adding a new stage, approval boundary, input slot, source analysis, GPT call, or Provider call.
- Recovery requires canonical immutable `script_revision` and `source_content_timeline` bytes, leaves GPT performance evidence at `PENDING_CONFIRMATION`, rejects pending/changed lines before publication, and publishes final artifacts only through the worker-owned publisher.
- Invocation B now requires the final performance artifact when the source-audio evidence pair exists and checks its revision, script SHA, frozen timeline SHA, line-list SHA, exact line/Cut/text/speaker/time bindings against the approved CAS sidecar before it invokes B.
- Provider bindings preserve the verified lowercase `performance_line_contract_sha256` in `provider_requests` and reject a Provider result that reports a different digest.

## Recovery RED / GREEN evidence

- RED: `test_invocation_b_rejects_a_performance_artifact_with_a_changed_confirmed_timeline` reached `Invocation B` before any CAS-sidecar timeline validation.
- GREEN: the same regression now fails before Invocation B with the frozen-timeline integrity error.
- RED: `test_provider_binding_preserves_the_frozen_performance_contract_digest` raised `KeyError` because the Provider binding omitted the digest.
- GREEN: the binding carries the exact verified digest.

## Recovery verification

```text
python -m pytest tests/test_revision_cas.py tests/test_review_service.py tests/test_server_api_contract.py tests/test_ephemeral_runtime.py tests/test_approved_script_contracts.py tests/test_high_fidelity_ports.py tests/test_performance_audio_contracts.py tests/test_production_ports.py -p no:cacheprovider -q
116 passed in 1.65s

python -m pytest tests/test_high_fidelity_ports.py tests/test_approved_script_contracts.py tests/test_ephemeral_runtime.py -p no:cacheprovider -q
22 passed in 1.00s

git diff --check
exit 0 (only repository CRLF conversion warnings)
```

## Follow-up review correction

- External review found that recovery dedupe initially omitted the script revision and CAS sidecar binding. A second revision with the same script SHA could therefore skip recovery and retain revision-1 artifacts.
- Fixed the recovery identity to include current script/storyboard revisions plus the sidecar revision, script SHA, timeline SHA, and line-list SHA. A same-SHA revision with a new sidecar now re-enters `build_script`.
- The Redis claim fence now permits this narrowly-scoped re-entry only when `build_script` is already `SUCCEEDED`; all other active-stage lease conflicts retain their prior rejection behavior.
- Regression: `test_driver_recovers_new_script_revision_when_script_sha_is_unchanged` was RED (the driver advanced to `generate_storyboards`), then GREEN.
- Final relevant verification after the correction: `117 passed in 1.65s` for the recovery/API/CAS/high-fidelity/performance/production suite. The full-suite bundle-closure test remains environment-blocked by generated cache directories that its own verifier forbids; cache deletion was rejected by the execution policy and no workspace files were removed.

## Second review correction

- A second review found two P2 hardening gaps. Recovery identity has been separated from the normal stage dedupe and now contains only the current script revision, approved script SHA, and immutable CAS sidecar binding; storyboard revision/approval changes no longer schedule another script recovery.
- Redis now recomputes the exact current sidecar-derived recovery digest before authorizing a completed `build_script` re-claim. The Lua fence accepts its explicit authorization flag only for that recovery path; arbitrary stale or malformed queue dedupes remain conflicts.
- Expanded regression coverage proves that a storyboard change advances to `generate_storyboards`, not another `build_script`, and that an arbitrary recovery dedupe cannot claim the completed stage.
- Final focused verification after this correction:

```text
python -m pytest tests/test_redis_job_store.py tests/test_revision_cas.py tests/test_review_service.py tests/test_server_api_contract.py tests/test_ephemeral_runtime.py tests/test_approved_script_contracts.py tests/test_high_fidelity_ports.py tests/test_performance_audio_contracts.py tests/test_production_ports.py -p no:cacheprovider -q
140 passed in 5.46s
```

## Final review correction

- A duplicate delivery carrying the same already-completed recovery digest under a different owner is now rejected. Redis authorizes re-claim only when the calculated sidecar recovery digest is both valid and different from the succeeded checkpoint digest (the draft-to-recovery transition).
- Final focused verification after this guard: the same 140-test suite passed in `5.45s`; `git diff --check` passed with only CRLF conversion warnings.
