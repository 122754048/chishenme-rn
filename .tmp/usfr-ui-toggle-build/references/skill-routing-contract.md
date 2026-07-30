# Deterministic Skill Routing Contract

Contract: `universal-fidelity-skill-routing/v1`.

This is an internal, additive contract for the `high_fidelity_hybrid_v1`
profile. It does not add an intake slot, RunState stage, user approval, paid
provider request, or public API field. The route is computed after the one
frame-zero-to-end dynamics pass from already frozen analysis flags.

## Inputs

```json
{
  "generated_regions": 0,
  "factors": {
    "performance": true,
    "camera": true,
    "motion": true,
    "lighting": false,
    "audio": true,
    "multi_shot": false
  },
  "overlay_required": false,
  "app_store_url_present": false
}
```

`generated_regions` is the validated count of contiguous generated regions and
must be `0`, `1`, or `2`. It comes from the authoritative Stage-4 timeline
regions, not from slot filenames or an AI role classifier. Factor flags are
projections of the high-fidelity dynamics/intent contracts; they do not trigger
a second analysis pass.

## Output

The router returns:

- `contract` and `analysis_pass_count`;
- a deterministic ordered `modules` list;
- `provider_modules` (only the existing storyboard/provider adapter);
- `dependency_snapshot` entries containing a logical POSIX `package_path`,
  role, source (`bundled` or `injected`), and `digest_required=true`;
- `route_sha256`, the SHA-256 of the canonical output before that field.

Local-only/opaque-only routes contain only
`analyze-reference-video-dynamics` plus an explicitly required technical
overlay module. An App Store URL does not load or fetch
`parse-app-store-evidence` when authoritative Stage-4 routing contains zero
generated regions, because no generated UI/target-evidence carrier can consume
its semantics. Generated routes always contain
`seedance-storyboard-replication`, root `seedance-20`, `seedance-prompt`, and
`seedance-antislop` in that order. Factor-specific modules are added only when
their factor is true, followed by `seedance-sequence` when two generated
regions or explicit multi-shot/continuity requires it. This relative order is
shared by Invocation A's route digest and Invocation B's prompt compiler.

## Server resolution and integrity

The package paths are logical and must be resolved from the deployed container
or a tenant-private immutable dependency artifact. A worker records the exact
byte SHA-256 and metadata version at startup and carries the same dependency
snapshot into Invocation A and Invocation B. `~/.codex/skills`, client paths,
absolute paths, and mutable local run directories are invalid authorities. A
missing, changed, or stale dependency blocks through the existing
`CONTRACT_INVALID`/`PROMPT_INTEGRITY_FAILED` path before `CreateAsset` or
`CreateVideo`.

The route digest is included in the parent input digest for the A sidecar, the
frozen Seedance input contract, and the final request audit. A route-only
serialization repair is allowed without a new user approval only when all
frozen source, script, line, storyboard, asset, and provider digests remain
unchanged.
