# Seedance 2.0 Internal Request Integrity Gate

This is the provider-neutral gate after the latest storyboard approval and
before any paid Youdao request. It is an internal integrity approval, not a
third user approval. The gate binds the approved script, storyboard, route,
assets, compiled prompt, and exact provider payload.

## Required sequence

1. Freeze `seedance_input_contract.json` after the latest approved storyboard.
2. Recompile the final prompt through `seedance-20` for the current prompt
   version. Run its professional capability, allocation, reference-role,
   directing, and anti-slop checks.
3. Build one exact unauthorised pre-audit dry-run payload. Do not pass audited,
   legacy, audit, script, or input-contract authorization flags, and do not
   mutate prompt, image mapping, duration, timecodes, route, or provider
   parameters after the dry run.
4. Run the parity audit and write an audit JSON artifact with exact request and
   prompt digests, approved-script digest, auditor, status, and every check.
5. Require zero ambiguity and no unresolved placeholders. Approve the exact
   digest internally, then submit unchanged with
   `--audited-request-sha256`, `--audit-artifact`,
   `--approved-script-sha256`, `--seedance-input-contract`, and
   `--seedance20-skill-file`.

## Audit checks

The artifact must compare all of these fields:

```json
{
  "approved_cut_order": true,
  "character_lock": true,
  "product_lock": true,
  "duration_and_timing": true,
  "voiceover_and_audio": true,
  "camera_action_continuity": true,
  "selling_point_evidence": true,
  "timeline_region_routing": true,
  "reference_role_mapping": true,
  "provider_parameters": true,
  "forbidden_fields": true,
  "zero_ambiguity": true,
  "no_unresolved_placeholders": true
}
```

The audit also confirms complete approved Cut text, fixed-B image allocation,
target route, no `reference_videos`, no default `reference_audios`, model
`seedance-2.0-fast`, `720p`, `9:16`, allowed duration, and the absence of
opaque UI or `app_tail_card_video` assets. Selling points must retain their
`Feature → Mechanism → Benefit → Proof → CTA` evidence chain; an
`unsupported` claim is lowered or removed before approval.

## Audit artifact schema and compiler provenance

The audit artifact is a JSON object with `auditor: "seedance-20"` and
`status: "passed"`. Its `compiler` object records the required provenance for
the exact final-prompt recompile. The caller/compiler must compute and record
the actual SHA-256 of the installed skill snapshot. Before authorization, the
validator loads the installed skill file and recomputes its exact raw-byte
SHA-256 and authoritative frontmatter metadata version, then compares both to
the artifact. `compiler.skill` is `"seedance-20"`,
`compiler.version` is a non-empty string, and `compiler.skill_sha256` is a
lowercase 64-hex SHA-256. The following compiler checks are literal booleans
and every one must be `true`: `professional_gate`, `capability_check`,
`allocation_check`, `reference_role_check`, `directing_coherence_check`, and
`anti_slop_check`.
The packaged compiler recomputes these checks from the structured segment,
line contract, route exclusions, prompt text, and immutable Skill bytes; a
caller-supplied boolean map is not evidence. The compiled artifact records a
`rule_audit` containing the root Skill SHA and recomputed-check digest.

## Frozen contract digests and contract index

`contract_digests` carries at least these eight required keys (additional
contract digests are allowed):

- `approved_storyboard_sha256`
- `source_fidelity_contract_sha256`
- `timeline_regions_sha256`
- `character_lock_sha256`
- `product_truth_sha256`
- `selling_point_mapping_sha256`
- `audio_contract_sha256`
- `continuity_manifest_sha256`

Every required digest value is a lowercase SHA-256; optional additional digest
fields are not validator-enforced. Each factor's `contract_pointer`
must be an exact key in `contract_index`; the value mapped by that index entry
must name one of the required digest keys above. The gate validates this index
mapping; it does not dereference a JSON fragment from the pointer.

## Factor coverage and payload-path resolution

`factor_coverage_ledger` must be non-empty. Every row has a stable unique
`factor_id`, a `source_pointer`, and `status: "passed"`. The only carriers are
`prompt_carried`, `reference_carried`, `payload_carried`,
`postproduction_carried`, and `route_excluded`.

For `prompt_carried`, `reference_carried`, and `payload_carried`,
`payload_path` is required and must resolve against the exact provider payload
whose request digest was audited. The supported JSONPath subset is `$`,
`.field`, `[N]`, `['field']`, and `["field"]`; wildcards and filters are not
accepted. A prompt carrier also requires a bounded `prompt_span` within the
compiled prompt. `postproduction_carried` and `route_excluded` do not need a
synthetic payload path, but any non-empty supplied `payload_path` must still
resolve. Every row also requires a `contract_pointer` satisfying the
contract-index rule above.

## Postproduction and route exclusions

Upstream route planning keeps postproduction content in the frozen
splice/assembly contracts and excludes it from the Seedance prompt, registered
assets, and provider payload. This is a route invariant carried by those frozen
contracts, not a semantic fact proven by this validator. The canonical Factory
form for `route_excluded` is an exact dictionary entry `{factor_id: true}` in
the route-exclusion contract. Missing, `false`, approximate, or differently
formatted factor ids fail closed. Legacy string/list aliases are
compatibility-only; Factory artifacts should emit the boolean mapping.

## Empty-state and compact route-leakage checks

The artifact must explicitly contain `ambiguities: []` and
`unresolved_placeholders: []`. The compiled prompt is scanned for unresolved
`{{...}}` and `[[...]]` markers. Route matching is case-insensitive,
separator-folded, and camelCase-aware. It compares complete contiguous tokens
or an exact compact token, never an arbitrary substring inside an unrelated
word; therefore `detail video` is not `tail_video` and `resource interval` is
not `source_interval`. snake_case, kebab-case, spaced, camelCase, and exact
compact spellings of a listed marker remain equivalent. Structured Prompt
compilation applies the same rule recursively to mapping keys and string
values, including `factors`, while preserving the explicit
`factor_ids`/`required_factor_ids` audit-label exemption. The implementation
blocks opaque/generated UI, tail-card, source-UI, transition, QC, and media
carriers including `opaque_ui_demo`, `generated_ui_demo`,
`opaque_app_tail_card`, `opaque_tail`, `tail_card`, `ui_render_contract`,
`ui_truth_card`, `ui_qc_report`, `rendered_media`, `media_sha256`, `qc_report`,
`transition_render_receipt`, `ui_operation_video`, `tail_video`,
`source_interval`, `source_ui_keep`, `transition_shell`,
`excluded_app_end_card`, `omit_source_end_card`, and `excluded_region`.
Forbidden provider-payload keys include `reference_videos`,
`reference_audios`, `opaque_ui_demo`, `opaque_ui_video`, `ui_demo_video`,
`generated_ui_demo`, `generated_ui`, `ui_render_contract`, `ui_truth_card`,
`ui_qc_report`, `ui_operation_video`, `ui_media`, `app_tail_card_video`,
`tail_video`, `tail_card`, `opaque_app_tail_card`, `opaque_tail`,
`rendered_media`, `media_sha256`, `qc_report`,
`excluded_app_end_card`, `omit_source_end_card`, `source_ui_frames`,
`source_interval`, `source_ui_keep`, `transition_shell`, and `excluded_region`.

## Prompt/script/request mutation locks

`request_sha256` is the SHA-256 of canonical JSON encoded as UTF-8 with
`ensure_ascii=false`, `sort_keys=true`, and `separators=(',', ':')`.
`compiled_prompt_sha256` is the SHA-256 of the exact UTF-8 text carried by the
provider payload. `approved_script_sha256` is the frozen approved-script digest
supplied to the validator. Any post-dry-run change to the prompt, image URI or
order, content order, model, resolution, ratio, duration, audio, watermark, or
other provider field requires a new `seedance-20` compile and audit.

The Factory paid path uses the complete set `--audited-request-sha256`,
`--audit-artifact`, `--approved-script-sha256`, `--seedance-input-contract`,
and `--seedance20-skill-file`. Legacy `--approved-request-sha256` remains
compatibility-only and is not the Factory's normal route. Resuming a known task
ID is not a new submission and must not create a duplicate paid task.

## Audited Factory frozen input contract and paid-path closure

The audited Factory route requires `--seedance-input-contract` and hashes its
exact raw bytes. The JSON object contains `approved_script_sha256`, the same
eight `contract_digests`, an exact unique `required_audit_checks` list matching
the 13 checks above, and a non-empty unique `required_factor_ids` list. The
ledger factor-ID set must equal that frozen list exactly: no omitted or extra
factor is accepted. The audit artifact records
`seedance_input_contract_sha256` for the raw-byte match.

Before any asset registration, the route validates the frozen contract,
prompt/route markers, fixed Factory parameters, and the installed root
`seedance-20/SKILL.md` snapshot. The snapshot must have `name: seedance-20` in
frontmatter; its exact-byte lowercase SHA-256 and authoritative metadata
version must match `compiler.skill_sha256` and `compiler.version`.

Only the audited Factory path enforces Youdao fixed-B payload shape:
`seedance-2.0-fast`, `720p`, `9:16`, duration 4–15, `generate_audio: true`,
`watermark: false`, one exact text item followed by at most four exact
`reference_image` `asset://asset-*` items, and no unknown provider fields or
forbidden route markers. The unauthorised `--dry-run` route is the only preview
and digest-preparation route; it cannot carry audited or legacy authorization
flags. Actual audited submission uses cache-only mappings produced by that dry
run: each mapping must be `status: Active`, have a non-empty `asset_id`, use
exactly `asset://{asset_id}`, and match the client's project name. A missing or
invalid mapping fails closed without registration, polling, or manifest writes.
Legacy explicit digest callers retain their compatibility behavior and are not
the normal Factory route. A plain `--resume-task-id` invocation is a separate
known-task route; it does not require a new prompt or duration, performs no asset
preparation or payload build, cannot be combined with `--dry-run`, cannot carry
authorization, audit, script, or input-contract flags, and is never described
as a new audited authorization.

The complete submission flags are `--prompt-file`, `--image-url` (repeatable),
`--duration`, `--ratio`, `--resolution`, `--output-dir`, `--env-file`,
`--dry-run`, `--poll`, `--resume-task-id`, `--approved-request-sha256` (legacy
only), `--audited-request-sha256`, `--audit-artifact`,
`--approved-script-sha256`, `--seedance-input-contract`,
`--seedance20-skill-file`, `--timeout`, `--poll-interval`, `--asset-timeout`,
and `--asset-poll-interval`. Mixed audited and legacy authorization is rejected.

## Failure and change routing

Any failed check, ambiguity, unresolved placeholder, digest mutation, unsafe
asset change, wrong route, or duplicate paid task blocks submission. Resume a
known task ID rather than creating a duplicate. Prompt-only repair repeats the
internal compile/audit sequence without asking the user again. A change to the
approved script, storyboard, assets, or timeline routes returns only to the
existing relevant user approval gate. A successful final response contains only
`final/result.mp4`.

## High-fidelity A/B snapshot bridge

When `high_fidelity_hybrid_v1` is active, Invocation A writes the internal
`seedance20_prescript_v1` artifact before the existing script gate. Invocation B
may receive `--profile-snapshot` and `--prescript-artifact` as worker-only
inputs; the submitter verifies the packaged `seedance-20` byte SHA and metadata
version before compiling or paying. These flags are new-request metadata, never
accepted on `--resume-task-id`, and do not add a public API field or approval.
The final prompt still passes the unchanged 13 audit checks and fixed-B closure.
