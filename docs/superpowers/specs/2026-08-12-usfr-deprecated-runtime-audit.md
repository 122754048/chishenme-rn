# USFR Deprecated Runtime Audit

Date: 2026-08-12

| Candidate | Static runtime references | Bundle/test references | Decision |
| --- | --- | --- | --- |
| `server/runninghub_final_lip_sync.py` | None outside its own module | Old unit tests and bundle allowlist only | Removed after H3 language route and bundle closure passed |
| `server/runninghub_song_lip_sync.py` | Formerly imported by `runninghub_workflows.py` | Superseded workflow/stage tests removed | Removed after H3 MV became the only reachable generation route |
| `SongLipSyncStage` and `run_song_lip_sync_segments()` | No current runtime references after H3 routing | Superseded tests removed | Removed; source music-window and UI protection analysis retained |
| `server/remotion_react_ui.py` | Imported by `packaged_factory.py`; consumed by `real_capabilities.py`, `ui_sidecar_runtime.py`, and hybrid compositor | Multiple activation, factory, sidecar and QC tests | Retain; deletion would change existing functionality |
| `scripts/hybrid_compositor.py` | Named by orchestrator assembly and Remotion backend | Bundle and compositor tests | Retain |
| `scripts/source_ui_pixels.py` | Current opaque UI protection | UI-operation tests | Protected; do not modify |
| `_recovery_20260807_prompt/` | No current runtime import found | Historical recovery tests/files only | Removed after static scan and bundle verification found no dependency |
| Historical `docs/superpowers/plans/*` | No runtime execution | Audit value only | Retain outside runtime bundle; not a functional conflict |

## Protected current capabilities

No cleanup may modify or delete code used by person/product/App/scene/garment/jewelry/accessory binding, product/App action adaptation, 24 fps segmentation, deterministic UI-operation video splice, subtitles/overlays, tail splice/trim, source-audio window analysis, off-camera voiceover fallback, provider reconciliation, or final QC.

## Deletion rule

A candidate is removable only when static search, dynamic import, bundle closure, and full regression all show that it is unreachable. A disabled feature with live imports is not considered deprecated.

## 2026-08-12 execution result

- Removed the two obsolete external lip-sync request builders, their direct workflow method/stage, superseded tests, and the isolated recovery directory.
- Retained `singing_audio_router`, `song_lip_sync_contract`, and legacy assembly validators because current source-window analysis, UI monologue protection, or compatibility/QC evidence still references them. They are not reachable as a paid post-generation workflow.
- Retained Remotion/hybrid compositor because static search found 90 active code/test references.
- Protected UI-operation hashes after the patch: `scripts/source_ui_pixels.py` = `68C418DAA468DA3D2E6AD51C55E319DF6896B3EB0AA395ADCC7C2EF9BCDD519C`; `tests/test_source_ui_pixels.py` = `C10D1E91DF2E6F100F53F403BDAFD1634EFC61942D4C186525B5D8E44C024D4E`.
- Local Skill full regression: `2066 passed, 1 skipped`; bundle verification: `bundle is valid`.
- Deployment copy targeted H3 routing regression: `10 passed, 35 deselected`; deployment bundle verification: `bundle is valid`.
