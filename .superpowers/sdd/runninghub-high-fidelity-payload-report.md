# RunningHub High-Fidelity Payload Migration Report

## Scope and result

High-fidelity Invocation-B now takes its final provider-payload authority from
the RunningHub Standard Model submitter.  It no longer imports the legacy
Youdao `seedance_submit.py` validator and no longer reads or writes
`content[0].text`.

The migration does not add a stage, provider request, approval, analysis pass,
or network call.  It preserves the existing stage adapter's provider-request
digest, compiled-prompt parity check, segment-plan SHA binding, source-audio
performance/timeline receipt checks, route error boundary, and aggregate audit
outputs.

## Changed files

- `usfr-server/server/high_fidelity_ports.py`
  - Loads `runninghub_seedance_submit.py` as its deployed payload authority.
  - Replaces direct template `prompt`, validates the exact standard payload,
    and obtains the immutable request digest through the standard submitter's
    public API.
- `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
  - Exposes `validate_runninghub_standard_payload()` and
    `runninghub_standard_request_sha256()` as the small reusable contract API.
  - Validation requires exactly the documented fields and rejects unknown or
    legacy fields; it requires `videoUrls == []`, public HTTPS image/audio
    URLs, at most nine images and one audio URL, `@Audio1` for supplied audio,
    and the existing generation/conversion-slot rules.  The high-fidelity
    caller enables the fixed-B constraint (`720p`, `9:16`).
- `usfr-server/tests/test_high_fidelity_ports.py`
  - Migrates the fixture to the exact RunningHub payload and adds coverage for
    an accepted standard payload, direct `prompt` template substitution, and
    rejection of a legacy `content`/`asset://` payload.

## TDD evidence

### RED (before implementation)

Command run from `usfr-server`:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_high_fidelity_ports.py::HighFidelityPortsTest::test_provider_binding_accepts_exact_runninghub_standard_payload tests/test_high_fidelity_ports.py::HighFidelityPortsTest::test_provider_binding_substitutes_compiled_prompt_into_direct_template_prompt tests/test_high_fidelity_ports.py::HighFidelityPortsTest::test_provider_binding_rejects_legacy_content_asset_payload -q
```

Result: `3 failed in 1.21s`.

- The valid standard payload failed because the port loaded the Youdao schema
  and reported missing/unknown fields.
- The template test failed because the port searched for legacy `content`.
- The legacy `content`/`asset://` payload was accepted, proving the old
  authority was still active.

### GREEN (after minimal implementation)

The same focused command returned: `3 passed in 0.66s`.

Required regression command:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_high_fidelity_ports.py tests/test_runninghub_standard_seedance.py tests/test_seedance_dependency_resolution.py -q
```

Result: `24 passed in 0.88s`.

`git diff --check` over the two implementation files and the focused test also
completed without whitespace errors.

## Safety and compatibility notes

- No credentials were read, logged, or added; no live API call was made.
- Standard payload validation rejects `content`, `model`, `audio_url`, and any
  other undocumented field through exact field-set validation.  `asset://`
  values cannot pass the public-HTTPS media validation, and non-empty
  `videoUrls` are rejected.
- The standard submitter remains the single schema authority; the high-fidelity
  port only calls its reusable validation/digest API.
- The standard submitter was already an untracked shared-worktree file before
  this task.  This task added only the reusable validation/digest surface to
  that file and did not alter unrelated workspace changes.

## Review follow-up: route integrity and public media admission

The reusable RunningHub validator now independently preserves the fixed-B
route-integrity boundary without importing or calling the legacy Youdao
validator.

- It recursively scans every payload key and value for the inherited
  route-excluded marker set (including source-video, opaque-UI, tail/UI and
  route-carrier markers) and rejects any match.
- It rejects unresolved `{{...}}` and `[[...]]` placeholders anywhere in the
  payload.  This preserves the compiled-prompt protection and makes the guard
  fail closed for a future string-valued payload field.
- Public HTTPS media admission now uses only local URL/IP parsing.  It rejects
  `localhost` and any non-global IP literal, covering IPv4/IPv6 loopback,
  private, link-local, unspecified, and reserved literals.  It performs no
  DNS or network lookup.
- `HighFidelityStageAdapter` already delegates to this exact validator; a
  focused port test proves a route-excluded compiled prompt reaches the same
  `ReplicationError` boundary.

### Follow-up TDD evidence

RED command run from `usfr-server`:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_runninghub_standard_seedance.py::test_standard_payload_validation_rejects_route_excluded_markers_in_all_values tests/test_runninghub_standard_seedance.py::test_standard_payload_validation_rejects_unresolved_prompt_placeholder tests/test_runninghub_standard_seedance.py::test_standard_payload_validation_rejects_non_public_literal_media_hosts tests/test_high_fidelity_ports.py::HighFidelityPortsTest::test_provider_binding_rejects_route_excluded_prompt_through_runninghub_validator -q
```

Result: `4 failed in 1.07s`.  The pre-fix validator accepted source-video and
opaque-UI markers, unresolved placeholders, `localhost`/private/link-local
IPv4 and IPv6 literal hosts, and the high-fidelity port consequently accepted
the route-excluded prompt.

After the minimal authority-only change, the same command returned:
`4 passed in 0.77s`.

Fresh focused regression verification:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_high_fidelity_ports.py tests/test_runninghub_standard_seedance.py tests/test_seedance_dependency_resolution.py -q
```

Result: `28 passed in 1.10s`.
