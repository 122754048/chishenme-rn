# Quality Activation Contract

Validation is incremental during development and exhaustive only for the final
immutable release candidate.

## Case catalog

The catalog contains 36 fully configured cases:

- 10 physical-product cases
- 10 App cases
- 5 service cases
- 4 brand cases
- 4 creator cases
- 3 mixed-media cases

Every case declares input-slot fixtures, output language, route/profile tags,
expected approval count, expected generated/source/opaque regions, toolchain
digest, and hard QC assertions.

## Selection

Routine changes run all cases whose component, route, language, or quality tags
intersect the changed dependency set, plus a fixed six-case smoke set. Cache
reuse is allowed only for an exact bundle + fixture + capability + model +
Provider fingerprint. The runner supports bounded parallelism, fail-fast hard
gates, and checkpoint/resume.

The full 36-case matrix runs once against the final immutable bundle digest.
Passing unit tests or metadata-only shadow cases is not evidence that an ad is
ready for use. Release requires a containerized source-to-final execution and a
playable final MP4 proving no black boundary frame, hard-cut gap, unreadable UI,
wrong language, audio drift, or tail padding.

## Executable result gate

Before running cases, use `validation/tools/build_case_catalog.py` with one or
more private validation input roots and a deployment-owned Publisher factory.
The builder computes file SHA-256 values, probes every video, rejects media over
30 seconds, performs byte-level deduplication, and publishes each unique asset
to a private object key. Its catalog and fixture-manifest outputs contain only
object references, media metadata, digests, and verified publication receipts;
local input paths never enter release evidence or the runtime image.

Run `validation/tools/validate_case_results.py` against the catalog and the
case-matrix result report. Incremental evidence must execute every selected
case, include the fixed smoke set, and may reuse another case only when its
complete dependency fingerprint is unchanged.

For an immutable release, all 36 cases must be executed against one bundle
digest; local `fixtures/...` placeholders and reused results are rejected.
Every case must bind its source and final MP4 SHA-256 to a verified independent
evaluator receipt. Route and timeline fidelity must equal 100%. Generated UI
and readable text OCR/layout must equal 100%. Total quality must be at least 85,
each catalog-declared high-critical factor must be at least 90, and Claim and
hard-failure lists must be empty.

Run selected cases with `validation/tools/run_case_matrix.py`. The runner uses
only the existing Jobs API, automates the catalog-declared 2/1/0 review count,
calls a separate private HTTPS evaluator, limits parallelism to 1–8 cases, and
writes an atomic per-case checkpoint after every completed case. Restarting the
same matrix digest resumes completed cases without repeating paid Provider
work.

Incremental mode is the default and accepts one or more `--changed-tag` values.
Immutable mode selects all 36 cases and requires an immutable bundle SHA. Any
selection with generated regions requires
`USFR_VALIDATION_ALLOW_PAID=1`; evaluator credentials use the separate
`USFR_VALIDATION_EVALUATOR_TOKEN` variable and are never sent to the Jobs API.
After execution, pass the result report to `validate_case_results.py`.
