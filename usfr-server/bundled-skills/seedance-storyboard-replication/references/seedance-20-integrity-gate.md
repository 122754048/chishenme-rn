# Seedance 2.0 Internal Request Integrity Gate

This is the provider-neutral gate after the latest storyboard approval and
before any paid RunningHub Standard Model request. It is an internal integrity
approval, not a third user approval. The gate binds the approved script,
storyboard, route, uploaded media, compiled prompt, and exact provider payload.

## Required sequence

1. Freeze `seedance_input_contract.json` after the latest approved storyboard.
2. Recompile the final prompt through `seedance-20` for the current prompt
   version. Run its professional capability, allocation, reference-role,
   directing, and anti-slop checks.
3. Build one exact unauthorised pre-audit dry-run payload with
   `runninghub_seedance_submit.py --dry-run`. Do not mutate the prompt, image
   mapping, duration, timecodes, route, or provider parameters afterward.
4. Run the script-to-prompt parity audit and write an audit JSON artifact with
   exact request/prompt digests, approved-script digest, compiler provenance,
   contract digests, factor coverage, and every check below.
5. Require zero ambiguity and no unresolved placeholders. Submit unchanged only
   with `--approved-request-sha256`, whose value equals the dry-run digest.
   Audit, script, storyboard, segment, and compiler evidence remain server-side.

## Audit checks

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

The audit confirms complete approved Cut text, fixed-B image allocation,
optional `background_music` `@Audio1` binding, no legacy `reference_videos`, no
default or top-level `reference_audios`, model `seedance-2.0-fast-token`,
`720p`, `9:16`, an allowed 4–15 second video duration, and the absence of opaque
UI or tail-card media. When `videoUrls[0]` is present, the audit additionally
requires `usfr-video-reference/v1`, one 2-15 second matching source segment,
the approved storyboard at `@Image1`, `realPersonMode=true`, and a non-empty
authorized target-change receipt.

## Audit artifact schema and compiler provenance

The audit artifact has `auditor: "seedance-20"` and `status: "passed"`. Its
compiler object records the exact installed Skill snapshot. Before
authorization, the validator loads the installed skill file and recomputes its
raw-byte SHA-256 and authoritative frontmatter metadata version. It compares
both to compiler provenance. The packaged compiler recomputes all checks from
the structured segment, exact-line contract, route exclusions, prompt text,
and immutable Skill bytes; caller-provided booleans are not evidence. Its
literal checks are `professional_gate`, `capability_check`,
`allocation_check`, `reference_role_check`, `directing_coherence_check`, and
`anti_slop_check`.

## Frozen contract digests and contract index

`contract_digests` includes `approved_storyboard_sha256`,
`source_fidelity_contract_sha256`, `timeline_regions_sha256`,
`character_lock_sha256`, `product_truth_sha256`,
`selling_point_mapping_sha256`, `audio_contract_sha256`, and
`continuity_manifest_sha256`. Every factor's `contract_pointer` resolves through
the immutable `contract_index`; a caller cannot point at an unbound fragment.

## Factor coverage and payload-path resolution

The `factor_coverage_ledger` is non-empty and has stable unique factor IDs.
`prompt_carried`, `reference_carried`, and `payload_carried` factors each have
a resolvable `payload_path` against the exact audited request. They cannot use
a synthetic payload path. `postproduction_carried` and `route_excluded` factors
remain outside the provider body.

## Postproduction and route exclusions

Opaque UI, tail, source-origin, deterministic UI, transition, and QC carriers
are `route_excluded`; no postproduction_carried factor reaches `imageUrls`,
`audioUrls`, `videoUrls`, or the final prompt.

## Empty-state and compact route-leakage checks

The artifact records `ambiguities: []` and `unresolved_placeholders: []`.
Prompt and structured values are scanned case-insensitively with separator and
camel-case folding, so route-excluded source, opaque UI, tail, transition, and
QC identifiers block before submission.

## Prompt/script/request mutation locks

The canonical request SHA-256 binds the compiled prompt, ordered image URLs,
duration, ratio, audio URL, model fields, and every direct request parameter.
Any mutation requires a fresh `seedance-20` compilation, dry-run, and audit.

## RunningHub fixed-B request

The provider body contains exactly the documented fields: `prompt`,
`resolution`, `duration`, `imageUrls`, `videoUrls`, `audioUrls`,
`generateAudio`, `ratio`, `realPersonMode`, `conversionSlots`,
`returnLastFrame`, and `seed`.

Fixed-B uses `seedance-2.0-fast-token`, `720p`, `9:16`,
`generateAudio=true`, one complete prompt, and at most nine public HTTPS
`imageUrls`. It may carry one current-segment, 2–15 second `audioUrls` item for
`@Audio1`; that audio requires at least one approved visual image. A
video-reference run may carry exactly one matching source slice at
`videoUrls[0]` only with `usfr-video-reference/v1`; opaque UI media and tail
video are never uploaded or referenced. Unknown fields, private URLs,
unresolved placeholders, and forbidden route markers block before a paid call.

## Submission and resume

The direct submitter accepts `--prompt-file`, repeatable `--image-url` or
`--image-file`, `--duration`, `--ratio`, `--real-person-mode`, `--output-dir`,
`--env-file`, `--dry-run`, `--poll`, `--resume-task-id`,
`--approved-request-sha256`, `--timeout`, and `--poll-interval`. Direct CLI
audio flags are deliberately unavailable: music comes only through the frozen
current-segment music contract bound to an approved visual request.

A plain `--resume-task-id` is a known-task route: it does not require a new
prompt or duration, performs no asset preparation or payload build, and cannot
be combined with `--dry-run`. It never creates a duplicate paid request.

Paid create and media upload are never automatically retried after a 429, 5xx,
timeout, connection reset, or ambiguous response. Reconcile a known task ID,
poll it statefully and without a deadline, and download a successful MP4 before
its result URL expires. Any prompt-only repair repeats this internal
compile/audit sequence; a change to the approved script, storyboard, asset, or
route returns only to the existing relevant user approval gate.
