# RunningHub standard-model contract sync report

## Scope completed

- The active Seedance provider boundary now documents the RunningHub Standard
  Model create/query/upload API, its dedicated `RUNNINGHUB_SEEDANCE_API_KEY`,
  direct fixed-B fields, `videoUrls=[]`, one optional duration-bounded
  `audioUrls` reference, query/download lifecycle, and no-retry behavior.
- The active package manifest and bundle verifier select
  `runninghub_seedance_submit.py`. The legacy `seedance_submit.py` file was
  retained in the workspace but is not an active packaged runtime route.
- The high-fidelity payload adapter and standard submitter validation API are
  included in the local Skill sync. No source-analysis, route-selection,
  approval, storyboard, ASR/TTS, or lip-sync workflow IDs were changed.

## TDD evidence

### Red

1. Extended `usfr-server/tests/test_skill_contract.py` with the active-provider
   contract: required RunningHub command/key/endpoint/payload markers and
   rejection of active Youdao, legacy submitter, and `asset://` references.
2. Ran:

   ```powershell
   python -B -m pytest usfr-server/tests/test_skill_contract.py -q
   ```

   Result: **7 failed, 24 passed** before the contract migration. The failures
   identified stale active provider expectations/wording, the active legacy
   submitter manifest entry, and the stale `asset://` fixed-B documentation.
   The first matcher was narrowed from a filename substring to the exact legacy
   command path so it does not falsely match `runninghub_seedance_submit.py`.

### Green

The workspace contains pre-existing `.pytest_cache` and `__pycache__`
directories. `verify_bundle()` correctly rejects those artifacts; platform
policy rejected their deletion even after their paths were verified. Therefore
the self-contained contract suite was rerun from a clean, cache-excluded mirror
of the same workspace files.

```powershell
python -B -m pytest tests/test_skill_contract.py -q
# 31 passed

python -B -m pytest tests/test_runninghub_standard_seedance.py tests/test_production_ports.py tests/test_seedance_dependency_resolution.py tests/test_skill_contract.py -q
# 106 passed

python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q
# 77 passed
```

The first two commands ran in clean mirrors so the self-contained bundle check
validated source content rather than unrelated local caches. The backend command
ran in the workspace. No test performed a live provider request or printed a
credential.

## Files copied to the locally invoked Skill

Destination root:
`C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/`

Only the following runtime code, configuration, documentation, and manifest
files were copied; SHA-256 comparison confirmed every destination equals its
workspace source.

```text
.env.example
SKILL.md
bundled-skills/seedance-storyboard-replication/SKILL.md
bundled-skills/seedance-storyboard-replication/references/seedance.env.example
bundled-skills/seedance-storyboard-replication/references/runninghub-standard-seedance-api.md
bundled-skills/seedance-storyboard-replication/scripts/config.py
bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py
references/bundle_manifest.json
references/server-deployment-step-by-step.md
references/update-maintenance-playbook.md
scripts/verify_bundle.py
server/high_fidelity_ports.py
server/production_ports.py
```

Tests, `.env` files, credentials, `.pytest_cache`, `__pycache__`, media,
storyboards, run outputs, and temporary files were not copied. A direct scan of
the synced root `SKILL.md` confirms it contains none of `Youdao`,
`YOUDAO_API_KEY`, `scripts/seedance_submit.py`, or `asset://`.

## Review follow-up: active configuration cleanup

Review found that the active shared configuration module still modeled and
reported historical provider settings despite the RunningHub migration. This
follow-up used a separate red/green cycle:

```powershell
# RED
python -B -m pytest usfr-server/tests/test_runninghub_standard_seedance.py::test_standard_provider_configuration_uses_a_dedicated_enterprise_key -q -p no:cacheprovider
# 1 failed: Settings exposed five Youdao fields.

# GREEN
python -B -m pytest usfr-server/tests/test_runninghub_standard_seedance.py::test_standard_provider_configuration_uses_a_dedicated_enterprise_key -q -p no:cacheprovider
# 1 passed

# Focused regression verification in a clean cache-excluded mirror
python -B -m pytest tests/test_runninghub_standard_seedance.py tests/test_production_ports.py tests/test_seedance_dependency_resolution.py tests/test_skill_contract.py -q
# 106 passed
```

`bundled-skills/seedance-storyboard-replication/scripts/config.py` now exposes
only RunningHub workflow and Standard Model keys/endpoints. It has no Youdao
fields, default URL, or redacted-preflight entries. The historical legacy
submitter file remains present but is not reintroduced as an active route.

Only these review-follow-up files were resynced to the local Skill and their
SHA-256 digests match the workspace source:

```text
bundled-skills/seedance-storyboard-replication/scripts/config.py
tests/test_runninghub_standard_seedance.py
references/update-maintenance-playbook.md
```

No cache deletion was attempted in this follow-up; the controller owns the
previously documented platform-policy block for the 192 pre-existing local
caches.
