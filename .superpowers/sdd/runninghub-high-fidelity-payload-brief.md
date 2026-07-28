# Task 2.5: Migrate high-fidelity provider payload authority to RunningHub Standard Model

## Why this task exists

The standard RunningHub provider adapter is already in place, but
`server/high_fidelity_ports.py` still loads the legacy `seedance_submit.py`
validator and requires its Youdao `content` payload. This makes high-fidelity
runs fail before the provider even though the final provider was switched.

## Files in scope

- Modify: `usfr-server/server/high_fidelity_ports.py`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
- Modify: `usfr-server/tests/test_high_fidelity_ports.py`
- Modify any directly impacted focused test only if necessary.

## Required behavior

1. The high-fidelity Invocation-B provider payload must be the exact RunningHub
   standard-model payload. It has only these documented fields:
   `prompt`, `resolution`, `duration`, `imageUrls`, `videoUrls`, `audioUrls`,
   `generateAudio`, `ratio`, `realPersonMode`, `conversionSlots`,
   `returnLastFrame`, `seed`.
2. Preserve the current USFR safety constraints: `videoUrls` is exactly `[]`;
   source video, opaque UI, and tail video cannot enter the payload; all media
   references are public HTTPS URLs; at most nine images and one audio clip;
   audio requires `@Audio1`; duration is string `4` through `15`; `720p`,
   normal `9:16`, audio generation and conversion-slot rules remain enforced.
3. High-fidelity payload template prompt substitution must update direct
   `prompt`, not legacy `content[0].text`.
4. The standard submitter must expose a small reusable validation/digest API
   suitable for the high-fidelity port; validation must reject unknown,
   missing, legacy (`content`, `model`, `asset://`, `audio_url`) or source-video
   fields. Do not duplicate an independent second definition of the payload
   schema in `high_fidelity_ports.py`.
5. Preserve the existing immutable provider request digest, approved prompt
   parity, segment-plan binding, source-audio digest/timeline binding, route
   integrity protections, and error boundary. This is only a final provider
   payload migration: it must not add a workflow stage, analysis pass,
   approval, paid request, or live API call.
6. Tests must be written first and observed failing. Cover a valid high-fidelity
   standard payload, direct prompt-template substitution, and rejection of
   legacy content/asset payloads. Do not expose credentials or perform network
   calls.

## Verification

Run from `usfr-server`:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_high_fidelity_ports.py tests/test_runninghub_standard_seedance.py tests/test_seedance_dependency_resolution.py -q
```
