# RunningHub Standard Seedance Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every USFR Seedance video task through RunningHub’s documented `seedance-2.0-fast-token` standard-model API, without changing source analysis, the two user approvals, storyboard generation, ASR/TTS, lip-sync, or final QC.

**Architecture:** Keep USFR’s internal prompt, contract, approval and idempotency gates unchanged. Replace only the final video-provider boundary with a RunningHub standard-model adapter: it uploads only permitted storyboard/target/audio references to the new-key account, sends the documented direct request body, polls the documented query endpoint, and downloads a successful MP4 immediately. The source video, opaque UI media and tail media remain forbidden references for Seedance generation.

**Tech Stack:** Python 3, `urllib`, pytest, RunningHub Standard Model API, existing USFR payload/audit contracts.

## Global Constraints

- Use a dedicated `RUNNINGHUB_SEEDANCE_API_KEY`; keep `RUNNINGHUB_API_KEY` for existing storyboard/ASR/TTS/lip-sync workflows so a consumer workflow key is never accidentally used for the enterprise standard-model endpoint.
- Standard video endpoint: `https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video`; query endpoint: `https://www.runninghub.cn/openapi/v2/query`; upload endpoint: `https://www.runninghub.cn/openapi/v2/media/upload/binary`.
- Send only the documented standard-model fields: `prompt`, `resolution`, `duration`, `imageUrls`, `videoUrls`, `audioUrls`, `generateAudio`, `ratio`, `realPersonMode`, `conversionSlots`, `returnLastFrame`, `seed`.
- Do not send source video, source slices, opaque UI videos or tail videos to the video model. Fixed-B USFR generation sets `videoUrls` to `[]`.
- Keep normal replication at `720p`, `9:16`, 4–15 seconds, and `generateAudio=true`; keep the approved `@Audio1` phrase in the prompt when the selected background-music/singing route supplies one segment-bounded audio reference.
- Do not retry an ambiguous paid create request. Preserve the request digest and task response; query only a known task ID.
- All credentials remain private environment values and must never be written to source, fixtures, task artifacts, terminal output, or documentation examples.

---

### Task 1: Add an independently testable local standard-model submitter

**Files:**

- Create: `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
- Create: `usfr-server/tests/test_runninghub_standard_seedance.py`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/config.py`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/references/seedance.env.example`

**Interfaces:**

- `build_runninghub_standard_payload(prompt, duration, ratio, image_urls, audio_urls, *, real_person_mode) -> dict[str, object]`
- `RunningHubStandardSeedanceClient.create_video(payload) -> str`, `get_status(task_id) -> dict[str, object]`, and `upload_file(path) -> str`
- `poll_runninghub_task(client, task_id, ...) -> str`

- [ ] **Step 1: Write failing payload and provider-client tests**

```python
def test_standard_payload_uses_documented_fields_and_keeps_source_video_out():
    payload = build_runninghub_standard_payload(
        "Use @Audio1 exactly.", 13, "9:16", ["https://media.example/board.png"],
        ["https://media.example/song-clip.mp3"], real_person_mode=True,
    )
    assert payload == {
        "prompt": "Use @Audio1 exactly.", "resolution": "720p", "duration": "13",
        "imageUrls": ["https://media.example/board.png"], "videoUrls": [],
        "audioUrls": ["https://media.example/song-clip.mp3"], "generateAudio": True,
        "ratio": "9:16", "realPersonMode": True, "conversionSlots": ["all"],
        "returnLastFrame": False, "seed": -1,
    }
```

- [ ] **Step 2: Run the new test and verify it fails because the module does not exist**

Run: `python -B -m pytest usfr-server/tests/test_runninghub_standard_seedance.py -q`

Expected: FAIL with import/module-not-found error.

- [ ] **Step 3: Implement the direct standard-model client**

Use multipart upload only for local permitted storyboard, target-image and segment-bounded audio files. Validate public HTTPS URLs, a 4–15 second request duration, 0–9 images, 0–1 audio reference for USFR, no video references, and a direct `taskId` response. Poll `QUEUED`/`RUNNING`, fail on terminal failure, and download the first `results[].url` immediately after `SUCCESS`.

- [ ] **Step 4: Add redacted configuration and verify the focused test**

Set `SEEDANCE_API_PROVIDER=runninghub_standard` by default and require `RUNNINGHUB_SEEDANCE_API_KEY`; report only `present`/`missing` in preflight. Run:

`python -B -m pytest usfr-server/tests/test_runninghub_standard_seedance.py usfr-server/tests/test_seedance_dependency_resolution.py -q`

Expected: PASS.

### Task 2: Make the service provider use the exact standard-model request

**Files:**

- Modify: `usfr-server/server/production_ports.py`
- Modify: `usfr-server/tests/test_production_ports.py`

**Interfaces:**

- `ProductionEnvironment` exposes the standard create/query URLs and the dedicated Seedance key variable name.
- `RunningHubSeedanceProvider.create_video(request)` sends the exact canonical standard payload, with no legacy `workflowId`, `modelId`, `request`, Youdao asset URI, or provider-only audit field.

- [ ] **Step 1: Write failing tests for the new URL, Key and payload shape**

```python
def test_runninghub_seedance_create_sends_standard_payload_with_dedicated_key(monkeypatch):
    _set_complete_environment(monkeypatch)
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_API_KEY", "standard-secret")
    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=_capture)
    provider.create_video(_standard_payload())
    assert captured["url"].endswith("/bytedance/seedance-2.0-fast-token/multimodal-video")
    assert captured["headers"]["Authorization"] == "Bearer standard-secret"
    assert captured["payload"] == _standard_payload()
```

- [ ] **Step 2: Run the test and verify it fails against the workflow-wrapper request**

Run: `python -B -m pytest usfr-server/tests/test_production_ports.py -k runninghub_video_create -q`

Expected: FAIL because the current adapter wraps the request in `workflowId`, `modelId`, and `request` and reads the generic key.

- [ ] **Step 3: Implement strict standard-payload validation and no-wrapper submission**

Validate documented types and values before the paid call. Reject non-empty `videoUrls`, source/opaque route fields and unknown legacy wrapper fields. Use `.cn` create/query defaults, the dedicated API key, no automatic create retry, and the existing known-task lookup/download lifecycle.

- [ ] **Step 4: Run service-provider tests**

Run: `python -B -m pytest usfr-server/tests/test_production_ports.py -k "runninghub or production_environment" -q`

Expected: PASS.

### Task 3: Rebind uploaded-audio payloads to the standard-model shape

**Files:**

- Modify: `backend/app/background_music_execution.py`
- Modify: `backend/app/background_music_local_mvp.py`
- Modify: `backend/tests/test_background_music_execution.py`
- Modify: `backend/tests/test_background_music_local_mvp.py`

**Interfaces:**

- Background-music/singing contracts emit a standard-video payload with `audioUrls`, not a Youdao `content.audio_url` or `asset://` URI.
- The compiler continues to keep exact `@Audio1` singer/lyric instructions in `prompt`; the upload stage materializes a permitted, duration-bounded RunningHub URL before video submission.

- [ ] **Step 1: Write failing tests that assert `audioUrls` and no legacy asset URI/content field**

```python
assert payload["audioUrls"] == ["https://runninghub.example/openapi/song-clip.mp3"]
assert "content" not in payload
assert "asset://" not in json.dumps(payload)
assert "@Audio1" in payload["prompt"]
```

- [ ] **Step 2: Run the two background-audio test modules and confirm the legacy shape fails**

Run: `python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q`

Expected: FAIL only on assertions expecting the legacy `content.audio_url`/`asset://` shape.

- [ ] **Step 3: Implement the canonical standard shape without changing eligibility, lyrics, timing, post mix or QA**

Keep the current singing-candidate routing, immutable music timeline, exact uploaded-fragment mix, Seedance prompt text and QC evidence. Change only the final provider payload and receipt field from provider asset URI to an uploaded RunningHub URL.

- [ ] **Step 4: Run the affected backend tests**

Run: `python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q`

Expected: PASS.

### Task 4: Update the runtime contract and synchronize the local Skill

**Files:**

- Modify: `usfr-server/SKILL.md`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md`
- Modify: `usfr-server/references/server-deployment-step-by-step.md`
- Modify: `.env.example`
- Sync to: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/`

- [ ] **Step 1: Update provider wording and command references**

Replace the active Youdao-only Seedance submission instructions with the RunningHub standard-model endpoint, dedicated key, permitted upload list, fixed `videoUrls=[]`, query/download lifecycle and no-retry policy. Do not alter source analysis, route selection, approvals, storyboard settings, ASR/TTS or lip-sync workflow IDs.

- [ ] **Step 2: Add a contract test that rejects any active provider document or env default pointing to Youdao**

Run: `python -B -m pytest usfr-server/tests/test_skill_contract.py -q`

Expected: FAIL until the runtime contract and package manifest use the new adapter.

- [ ] **Step 3: Sync the verified packaged files to the locally invoked Skill**

Copy only the changed provider/config/script/document files after their workspace tests pass. Do not copy credentials, run artifacts, `.pytest_cache`, source videos, storyboards or temporary files.

- [ ] **Step 4: Run the final focused verification**

Run: `python -B -m pytest usfr-server/tests/test_runninghub_standard_seedance.py usfr-server/tests/test_production_ports.py usfr-server/tests/test_seedance_dependency_resolution.py usfr-server/tests/test_skill_contract.py -q; python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q`

Expected: PASS; no test permits a source-video reference or logs a credential.

## Self-Review

- The plan changes only the final Seedance video-provider boundary; it preserves all mandatory script/storyboard approvals and upstream analysis.
- A dedicated standard-model key avoids silently sending a non-enterprise workflow key to the enterprise-only API.
- The standard payload is audited before paid submission, uploads only references that are legal for the active route, and never carries source/opaque videos.
- Music/singing still uses `@Audio1` in the compiled prompt, while the external request uses RunningHub’s documented `audioUrls` field.
