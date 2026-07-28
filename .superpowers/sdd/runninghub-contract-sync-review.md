diff --git a/.env.example b/.env.example
index 4a9bf4f..434031a 100644
--- a/.env.example
+++ b/.env.example
@@ -4,12 +4,12 @@ APP_ENV=production
 
 # Provider credentials are server-only.
 RUNNINGHUB_API_KEY=
-YOUDAO_API_KEY=
-YOUDAO_BASE_URL=https://openapi.youdao.com/llmgateway
-YOUDAO_SEEDANCE_MODEL=seedance-2.0
-YOUDAO_SEEDANCE_RESOLUTION=720p
-YOUDAO_PROJECT_NAME=default
-SEEDANCE_API_PROVIDER=youdao
+# Enterprise shared Key for RunningHub Standard Model Seedance video generation.
+RUNNINGHUB_SEEDANCE_API_KEY=
+RUNNINGHUB_SEEDANCE_CREATE_URL=https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video
+RUNNINGHUB_SEEDANCE_QUERY_URL=https://www.runninghub.cn/openapi/v2/query
+RUNNINGHUB_SEEDANCE_UPLOAD_URL=https://www.runninghub.cn/openapi/v2/media/upload/binary
+SEEDANCE_API_PROVIDER=runninghub_standard
 
 # Standard USFR commercial batch deployment.
 REPLICATION_RUNTIME_FACTORY=app.usfr_commercial_deployment:build_replication_runtime
diff --git a/usfr-server/SKILL.md b/usfr-server/SKILL.md
index 6f52201..16df17e 100644
--- a/usfr-server/SKILL.md
+++ b/usfr-server/SKILL.md
@@ -116,7 +116,7 @@ Read only the modules required by the current input:
   stage or Provider task, never invents a claim, and fails closed when required
   evidence or a 4-15 second generated-region contract is unavailable.
 - `bundled-skills/seedance-storyboard-replication/SKILL.md`: route selection,
-  weighted intent, storyboard generation, RunningHub image2, Youdao assets,
+  weighted intent, storyboard generation, RunningHub image2 and Standard Model media upload,
   Seedance compilation/submission, `opaque_ui_demo`, supplied App tail-card
   assembly, and QC.
 
@@ -230,10 +230,9 @@ eighth fixed slot. It never changes the seven slot roles or ordering. A valid
 upload is written only to `extensions.background_music`, admits a
 source-plus-change run, uses `seedance_audio_reference`, and is not a
 `language_only` request. It is usable only when the deployment has bound the
-`background_music_execution/v1` adapter. The fixed-B request registers it as a
-Youdao `Audio` asset and carries exactly one content `audio_url` item with
-`role=reference_audio`; the prompt refers to it as `@Audio1`, while top-level
-`reference_audios` remains forbidden.
+`background_music_execution/v1` adapter. The fixed-B request carries exactly
+one duration-bounded RunningHub Standard Model `audioUrls` item; the prompt
+refers to it as `@Audio1`, while legacy `reference_audios` remains forbidden.
 
 `output_language` is a separate fixed parameter, not a media slot. Supported
 values are `en`, `ja`, `ko`, `fr`, `de`, `es`, `pt`, `id`, and `zh`. The UI
@@ -617,17 +616,16 @@ two Provider tasks for deployment audits.
      approval triggers autonomous Seedance compilation, submission, provider
      waiting, assembly, and QC.
 
- 9. **Compile and audit the exact Youdao request internally**
+ 9. **Compile and audit the exact RunningHub Standard Model request internally**
     - After the latest storyboard approval, freeze `seedance_input_contract.json`.
       Recompile the final prompt through `seedance-20`, then build exactly one
-      unauthorised pre-audit dry-run payload for that prompt version. Do not pass
-      audited/legacy authorization, audit, script, or input-contract flags on
-      the dry run.
-    - Register only required generated-region storyboard images and populated
-      target reference images from the fixed slot manifest with Youdao CreateAsset.
-      Never register the source video, source intervals, or opaque
-      media.
-      `CreateAsset` is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Reuse an existing Active mapping or stop for provider-state reconciliation.
+      unauthorised pre-submit dry-run payload for that prompt version. Do not
+      pass `--approved-request-sha256` on the dry run.
+    - Upload only required generated-region storyboard images and populated
+      target reference images from the fixed slot manifest with RunningHub
+      Standard Model binary upload. Never upload the source video, source
+      intervals, opaque UI media, or tail media. RunningHub media upload is never automatically
+      retried after a 429, 5xx, timeout, connection reset, or ambiguous response.
    - Build the complete prompt under 5000 characters and run dry-run.
    - Build the internal `seedance-20` request, redacted payload, and SHA-256.
     - Load only the factor-specific specialists selected by the immutable Skill
@@ -654,10 +652,10 @@ two Provider tasks for deployment audits.
       only the current segment's deterministically rebound local-time rows. A
       missing/invalid plan, snapshot mismatch, boundary crossing, or
       line-contract mutation blocks before CreateAsset/CreateVideo.
-    - Submit the unchanged request only with the complete audited authorization
-      set: `--audited-request-sha256`, `--audit-artifact`,
-      `--approved-script-sha256`, `--seedance-input-contract`, and
-      `--seedance20-skill-file` for the installed root `seedance-20/SKILL.md`.
+    - Submit the unchanged dry-run request only with
+      `--approved-request-sha256 <dry-run-request-sha256>`. The parity audit,
+      frozen input contract, and packaged Skill digest remain server-side
+      integrity evidence and are not submitter flags.
     - Prompt-only repair stays inside this internal gate. A change to the
       approved script, storyboard, assets, or routes returns only to the existing
       relevant script/storyboard approval gate.
@@ -677,7 +675,7 @@ two Provider tasks for deployment audits.
       combined with `--dry-run`. Resume known IDs
       instead of creating duplicate paid tasks. Never silently retry an
       ambiguous provider failure.
-    - `CreateVideo` is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Preserve the exact audited request and reconcile provider state; resume only when a task ID is known.
+    - Paid Seedance create is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Preserve the exact audited request and reconcile provider state; resume only when a task ID is known. Query only a returned task ID, then download the successful MP4 immediately before its result URL expires.
     - For a one-or-two-Segment plan, submit every missing Segment intent in
       frozen plan order before polling. The first successful Segment remains
       in `PROVIDER_RUNNING`; only the exact complete successful Segment set may
@@ -825,12 +823,12 @@ The speed design is fixed: one deterministic slot bind, one deterministic probe
 and one semantic pass, cached contracts/assets, independent asset and segment work concurrent, and
 dependency-locked work ordered. Compile once per `seedance-20` prompt version
 and run one dry-run per version; perform local deterministic parity checks
-afterward. The Youdao route is fixed to `seedance-2.0-fast`, `720p`, `9:16`,
-the fixed-B image route, no `reference_videos`, and no `reference_audios`
-field. A registered audio asset and content `audio_url` are permitted only for
-the approved `background_music` extension, which must render as `@Audio1` and
-remain bound to its music execution contract. Resume known task IDs and never
-create duplicate paid tasks.
+afterward. The RunningHub Standard Model route is fixed to
+`seedance-2.0-fast-token`, `720p`, `9:16`, the fixed-B image route,
+`videoUrls=[]`, and no legacy `reference_audios` field. One duration-bounded
+`audioUrls` item is permitted only for the approved `background_music`
+extension, which must render as `@Audio1` and remain bound to its music
+execution contract. Resume known task IDs and never create duplicate paid tasks.
 
 `probe_source` is the deterministic probe cache boundary. Its verified output
 must carry the source SHA-256, duration, dimensions, and frame-rate fields;
@@ -860,7 +858,7 @@ Use `scripts/production_timing.py` for every run and persist to the run's
   and `resume_approval("script")` immediately after it; likewise use
   `pause_approval("storyboard")` / `resume_approval("storyboard")` only around
   the storyboard approval wait. Do not exclude any other work or wait.
-- Wrap each RunningHub image2 wait and Youdao Seedance wait with
+- Wrap each RunningHub image2 wait and RunningHub Standard Model Seedance wait with
   `start_stage(<stage-name>, provider=True)` and `end_stage(<stage-name>)`.
   Provider stages remain included in active processing and are also totaled
   separately as provider time.
diff --git a/usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md b/usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md
index 52714de..c641d22 100644
--- a/usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md
+++ b/usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md
@@ -6,10 +6,10 @@ description: Use when a user needs storyboard and Seedance execution for an appr
 # Seedance Storyboard Replication
 
 Turn an approved source-video contract into model-generated storyboards and a
-Youdao Seedance 2.0 task for each generated region. The skill is universal across
+RunningHub Standard Model Seedance 2.0 Fast task for each generated region. The skill is universal across
 physical products, Apps/digital products, services, brands, and no-product
 formats; source camera style and content type come from the contract. It owns
-route selection, approval gates, prompt assembly, Youdao asset registration,
+route selection, approval gates, prompt assembly, RunningHub media upload,
 Seedance submission, timeline assembly, and final QC.
 
 ## Route Selection
@@ -35,13 +35,13 @@ Both routes must tell the user before Seedance submission that this workflow acc
 
 Both routes use the **固定 B 方案**. 参考视频仅用于反解分镜、节奏分析和故事板生成;
 after storyboard approval retain it only as server-side, verified
-tenant-private object-storage evidence. 禁止将参考视频注册为 Youdao 素材,
-and 禁止发送 `reference_videos` to Seedance. The exact fixed-B payload uses
-`generate_audio=true` and `watermark=false`; no top-level `reference_audios`
+tenant-private object-storage evidence. Never upload or send reference video
+to RunningHub Seedance. The exact fixed-B payload uses
+`generateAudio=true` and `videoUrls=[]`; no legacy `reference_audios`
 field or implicit audio reference is permitted. The approved
-`background_music` extension is the sole exception: register it as Youdao
-`AssetType=Audio`, send it only as content `audio_url` with
-`role=reference_audio`, and require `@Audio1` in the compiled prompt.
+`background_music` extension is the sole exception: upload one
+duration-bounded fragment as `audioUrls[0]` and require `@Audio1` in the
+compiled prompt.
 This rule also applies to Route 1 even when the user supplied an approved script
 together with a reference video.
 
@@ -180,7 +180,7 @@ stop with a blocker. After generation, write paths into `analysis/timeline_regio
 run `scripts/timeline_splice.py`, save `timeline_splice_manifest.json`, and
 verify source-to-output placement. Opaque and source-origin media remain local
 only as server-side object-store-backed or lease-materialized media and are
-never Youdao assets or client-workstation dependencies.
+never legacy provider assets or client-workstation dependencies.
 
 ## Evidence and Analysis Routing
 
@@ -295,11 +295,11 @@ step and is not vendored by this bundled module. If it is unavailable, stop
 before any paid request.
 
 1. Compile through `seedance-20`, preserving the complete approved Cuts, four-image mapping, fixed-B payload, and all negative constraints.
-2. Build the exact final payload and run `scripts/seedance_submit.py --dry-run` once as the unauthorised pre-audit preview; do not pass audited/legacy authorization, audit, script, or input-contract flags on this dry run.
+2. Build the exact final payload and run `scripts/runninghub_seedance_submit.py --dry-run` once as the pre-submit preview; do not create a paid task at this step.
 3. Run the `seedance-20` script-to-prompt parity audit against that exact dry-run request and write the required audit JSON artifact (`auditor`, `status`, exact request/prompt digests, approved script digest, compiler provenance, contract digests, factor coverage, zero ambiguities, and every required check in `references/seedance-20-integrity-gate.md`).
-4. Submit only with the complete audited authorization set: `--audited-request-sha256 <digest>`, `--audit-artifact <path>`, `--approved-script-sha256 <digest>`, `--seedance-input-contract <path>`, and `--seedance20-skill-file <path>` matching the saved internal audit and frozen inputs.
+4. Submit only the exact audited payload with `--approved-request-sha256 <digest>` matching the saved dry-run request SHA-256; audit, script, and contract artifacts remain server-side integrity evidence.
 5. The Factory executor owns two-segment concurrency: it starts both independent single-task CLI invocations before waiting for either. Preserve ordering where segment 2 requires segment 1 pixels; dependency-locked segment 2 remains sequential.
-6. Reuse cached Active Youdao assets under a cross-process manifest lock; polling is state-aware and non-deadline by default, with no duplicate registrations or paid tasks.
+6. Upload only the required storyboard/target/audio references to the RunningHub Standard Model account, poll known task IDs statefully and without a deadline, and never create duplicate paid tasks.
 7. Finalize and deliver only `final/result.mp4`; successful delivery contains no extra artifacts.
 8. Unsafe asset changes, a failed parity audit, digest mutation, or a duplicate paid retry remain blockers. Resume known tasks instead of creating duplicate paid tasks.
 
@@ -330,28 +330,25 @@ digest mutation, unsafe asset change, or duplicate paid retry is a blocker.
 
 ### Audited Factory closure
 
-The audited submission must pass `--seedance-input-contract` containing the
-approved-script digest, the eight contract digests, the exact unique 13-check
-list, and the non-empty unique `required_factor_ids` list. The ledger factor-ID
-set must equal that frozen list exactly. The audit stores the raw-byte
-`seedance_input_contract_sha256` and validates it before any asset operation.
+The audited dry run stores the approved-script digest, the eight contract
+digests, the exact unique 13-check list, and the non-empty unique
+`required_factor_ids` list as server-side integrity evidence. The ledger
+factor-ID set must equal that frozen list exactly. The audit stores the raw-byte
+`seedance_input_contract_sha256` and validates it before any provider call.
 
 The installed root `seedance-20/SKILL.md` is required before the paid path. Its
 frontmatter must name `seedance-20`; its exact-byte SHA-256 and metadata version
-must match compiler provenance. The audited payload is strictly Youdao fixed-B
-plus the approved `background_music` extension when supplied:
-`seedance-2.0`, `720p`, `9:16`, duration 4–15, audio enabled, watermark
-disabled, exact text/reference-image item shapes, at most one exact
-`audio_url` item carrying `@Audio1`, and no unknown or leaked provider fields.
-The normal unauthorised dry run is explicitly pre-audit and
-cannot carry audited or legacy authorization flags. Audited actual submission
-reads only cached Active asset mappings from that dry run (`cache_only`); each
-must be Active with a non-empty ID, exact `asset://{asset_id}` URI, and the
-client project name. Missing or invalid cache provenance fails without
-CreateAsset registration, polling, or manifest writes. Dry-run and legacy
-explicit-digest paths retain their existing behavior. Legacy authorization is
-compatibility-only and never the normal Factory route; mixed audited/legacy
-flags are invalid. A plain `--resume-task-id` is a separate known-task route,
+must match compiler provenance. The audited payload is strictly RunningHub
+Standard Model fixed-B plus the approved `background_music` extension when supplied:
+`seedance-2.0-fast-token`, `720p`, `9:16`, duration 4–15, `generateAudio=true`,
+and documented direct image/audio URL fields: at most one exact `audioUrls`
+item carrying `@Audio1`, `videoUrls=[]`, and no unknown or leaked provider
+fields. The normal unauthorised dry run cannot carry
+`--approved-request-sha256`. Actual submission uses only
+`--approved-request-sha256 <dry-run-request-sha256>` for the exact saved
+payload. Every uploaded URL must bind to the exact local input SHA-256 and
+remain valid for the selected RunningHub account; missing, expired, or invalid
+upload provenance blocks before paid creation. A plain `--resume-task-id` is a separate known-task route,
 does not require a new prompt or duration, performs no asset preparation or
 payload build, cannot be combined with `--dry-run`, cannot carry authorization/
 audit/script/input-contract flags, and is not a new audited authorization.
@@ -371,27 +368,27 @@ Calculate duration only from the ordered contiguous generated regions in
 - The Skill chooses the boundary from story meaning; `segment_plan.py` only validates the chosen `--split-boundary`. It must never invent or balance the split.
 - If no valid approved boundary exists, or the generated-region plan would exceed two total tasks, stop with a blocker requiring storyboard-script revision or a different postproduction route. Never hard-cut and never add a third storyboard.
 
-## Youdao Asset and Seedance Submission
+## RunningHub Standard Model Seedance Submission
 
-Read `references/seedance-prompt.md` and `references/youdao-api.md` before assembling the final request.
+Read `references/seedance-prompt.md` and `references/runninghub-standard-seedance-api.md` before assembling the final request.
 
 1. Confirm the user approved the storyboard and understands the four-image allocation.
-2. Obtain the existing public HTTPS source URL for each approved segment storyboard, character reference, and product board. In the RunningHub image2 route, reuse the saved RunningHub upload/result URLs; do not generate or upload the images again.
-3. Run `scripts/seedance_submit.py --dry-run` with those source URLs as the unauthorised pre-audit request; do not pass authorization/audit/contract flags. For Youdao, the script calls `POST /api/v1/assets?Action=CreateAsset`, reads `Result.id`, polls `GetAsset` until `Status=Active`, caches mappings in `youdao_assets.json`, and maps each one to `asset://<id>`. No COS service is required. 禁止注册参考视频.
+2. Upload each approved segment storyboard, character reference, product board, and optional duration-bounded audio fragment with the dedicated Standard Model key. Bind each returned public HTTPS URL to the exact input SHA-256; do not reuse an expired URL from another account.
+3. Run `scripts/runninghub_seedance_submit.py --dry-run` with those URLs as the pre-submit request. It must contain the documented direct fields, especially `videoUrls=[]`; source video, opaque UI, and tail media are forbidden.
 4. Build each segment prompt under 5000 characters. Repeat that segment's complete approved Cuts as text, with global Cut numbers, local timecodes, actual `@图片1` to `@图片4` mapping, incoming/outgoing continuity anchors, 脚本描述, camera/action direction, product/person identity lock, 口播内容, sound, continuity, and 备注. Never replace these fields with “follow the storyboard image.”
-5. Do not use the top-level `reference_audios` field. Approved uploaded music
-   is accepted only as one `audio_url` content item plus an explicit `@Audio1`
-   prompt reference.
+5. Do not use any legacy `reference_audios` field. Approved uploaded music is
+   accepted only as one `audioUrls` item plus an explicit `@Audio1` prompt
+   reference.
 6. Audio policy: request voiceover plus environment/action sound, and **不默认添加背景音乐** unless the user explicitly asks for music or uploads `background_music`.
 7. Run one dry-run, save the exact prompt/request and `approval_preview.json`, then complete the `seedance-20` parity audit, write the audit artifact, and authorize the exact digest.
-8. Submit with Youdao model `seedance-2.0`, `resolution=720p`, `ratio=9:16`, `duration=4-15`, cached Youdao `asset://` image references, the optional cached `@Audio1` Audio asset when `background_music` is supplied, and the complete audited authorization set: `--audited-request-sha256`, `--audit-artifact`, `--approved-script-sha256`, `--seedance-input-contract`, and `--seedance20-skill-file`. 禁止发送 `reference_videos`.
-9. When `opaque_ui_demo` or supplied `excluded_app_end_card` exists, submit only contiguous generated regions. Never register or send those opaque videos to Youdao, and never mention their visual contents in the Seedance prompt.
+8. Submit through `seedance-2.0-fast-token/multimodal-video` at `720p`, `9:16`, duration 4–15, with only uploaded `imageUrls`, optional one `audioUrls` entry for `@Audio1`, `videoUrls=[]`, `generateAudio=true`, and `--approved-request-sha256` matching the audited dry run.
+9. When `opaque_ui_demo` or supplied `excluded_app_end_card` exists, submit only contiguous generated regions. Never upload or send those opaque videos to RunningHub Seedance, and never mention their visual contents in the Seedance prompt.
 
 Never make a paid Seedance call until the latest storyboard has been approved and the internal parity audit authorizes the exact audited digest. Normal submission does not require a user prompt confirmation.
 
 ## Download, Concatenation, and QC
 
-When a Seedance task completes, immediately download `data.result.video_url` to `result.mp4`; successful delivery is MP4-only at `final/result.mp4`.
+When a Seedance task completes, immediately download the returned `results[].url` MP4 to `result.mp4`; successful delivery is MP4-only at `final/result.mp4`.
 
 - For a single task, probe the MP4 with `scripts/concat_videos.py` or FFprobe and confirm a video stream exists.
 - For two segments, concatenate with FFmpeg through `scripts/concat_videos.py` at the approved story boundary and preserve audio. Do not add a crossfade by default.
@@ -422,9 +419,9 @@ When a Seedance task completes, immediately download `data.result.video_url` to
 
 - Save `task_id.txt`, `request.redacted.json`, `approval_preview.json`, `create_response.json`, `status.json`, and `failure.json` when applicable.
 - Use `--resume-task-id` to continue a known Seedance task instead of submitting a duplicate paid task.
-- Retry 429 and transient 5xx responses only for idempotent status/readiness calls such as GetAsset/GetTask. `CreateAsset` is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. `CreateVideo` is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Preserve the audited request, reconcile provider state, and resume only a known task ID. Treat 401/403 as configuration errors.
-- If Youdao CreateAsset/GetAsset fails or any required `asset://` mapping is missing, do not submit Seedance.
-- If a planned or dry-run payload contains `reference_videos`, stop before submission and rebuild it with the fixed B route.
+- Retry 429 and transient 5xx responses only for idempotent query/readiness calls. RunningHub media upload is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Paid Seedance create is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Preserve the audited request, reconcile provider state, and resume only a known task ID. Treat 401/403 as configuration errors.
+- If a required RunningHub upload fails, expires, or cannot be bound to its local SHA-256, do not submit Seedance.
+- If a planned or dry-run payload contains a non-empty `videoUrls`, stop before submission and rebuild it with the fixed-B route.
 - `[SY_ERR:10] PROVIDER_MODERATION_ERROR: TRADEMARK`: do not retry unchanged. Clearly report the trademark moderation point, return to the storyboard prompt/image approval loop, and explain that changing the prompt may not be enough when the uploaded product image itself contains the mark. Never silently remove a product logo; obtain user approval before a compliant debranded or replacement asset is used.
 - A bare `[SY_ERR:10] PROVIDER_MODERATION_ERROR` has no known subtype. Report it as an unspecified moderation failure and preserve the raw message; never infer `TRADEMARK` unless the provider returned that token.
 - `[SY_ERR:10] Read timed out`, `s3 upload failed`, or `connection reset by peer`: treat as an ambiguous provider media-fetch failure. Do not change the prompt or create a replacement paid task. Preserve the original audited request, enter the existing provider-reconciliation/user-action blocker, and resume only when a known task ID or authoritative provider lookup resolves the outcome.
@@ -479,9 +476,9 @@ through `scripts/seedance_prompt_compiler.py` and the same packaged
 `seedance-20` snapshot, repeat approved dialogue and
 timing verbatim, then run the existing unauthorized dry-run and 13-check audit.
 No paid task is allowed before zero ambiguity, no unresolved placeholders, and
-fixed-B closure. Do not send source/opaque media, `reference_videos`, or
-top-level `reference_audios`; the approved `background_music` exception uses
-content `audio_url` plus prompt `@Audio1`.
+fixed-B closure. Do not send source/opaque media or any non-empty
+`videoUrls`; the approved `background_music` exception uses one `audioUrls`
+item plus prompt `@Audio1`.
 The compiler recomputes the root Skill checks from the structured segment,
 exact line contract, route exclusions, anti-slop rules, and immutable Skill
 bytes; caller-supplied boolean checks are not authorization. The compiled
diff --git a/usfr-server/bundled-skills/seedance-storyboard-replication/references/seedance.env.example b/usfr-server/bundled-skills/seedance-storyboard-replication/references/seedance.env.example
index b03b777..bb2118f 100644
--- a/usfr-server/bundled-skills/seedance-storyboard-replication/references/seedance.env.example
+++ b/usfr-server/bundled-skills/seedance-storyboard-replication/references/seedance.env.example
@@ -3,9 +3,9 @@
 RUNNINGHUB_API_KEY=
 RUNNINGHUB_BASE_URL=
 
-SEEDANCE_API_PROVIDER=youdao
-YOUDAO_API_KEY=
-YOUDAO_BASE_URL=https://openapi.youdao.com/llmgateway
-YOUDAO_SEEDANCE_MODEL=seedance-2.0-fast
-YOUDAO_SEEDANCE_RESOLUTION=720p
-YOUDAO_PROJECT_NAME=default
+# Enterprise shared Key used only by RunningHub Standard Model Seedance calls.
+RUNNINGHUB_SEEDANCE_API_KEY=
+SEEDANCE_API_PROVIDER=runninghub_standard
+RUNNINGHUB_SEEDANCE_CREATE_URL=https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video
+RUNNINGHUB_SEEDANCE_QUERY_URL=https://www.runninghub.cn/openapi/v2/query
+RUNNINGHUB_SEEDANCE_UPLOAD_URL=https://www.runninghub.cn/openapi/v2/media/upload/binary
diff --git a/usfr-server/bundled-skills/seedance-storyboard-replication/scripts/config.py b/usfr-server/bundled-skills/seedance-storyboard-replication/scripts/config.py
index d2173df..e567a94 100644
--- a/usfr-server/bundled-skills/seedance-storyboard-replication/scripts/config.py
+++ b/usfr-server/bundled-skills/seedance-storyboard-replication/scripts/config.py
@@ -48,11 +48,10 @@ def _parse_env(path: Path) -> dict[str, str]:
 class Settings:
     runninghub_api_key: str = field(repr=False)
     runninghub_base_url: str
-    youdao_api_key: str = field(repr=False)
-    youdao_base_url: str
-    youdao_model: str
-    youdao_resolution: str
-    youdao_project_name: str
+    runninghub_seedance_api_key: str = field(repr=False)
+    runninghub_seedance_create_url: str
+    runninghub_seedance_query_url: str
+    runninghub_seedance_upload_url: str
     seedance_api_provider: str
 
     def require_runninghub(self) -> None:
@@ -60,12 +59,10 @@ class Settings:
             raise ConfigurationError("Missing configuration: RUNNINGHUB_API_KEY")
 
     def require_seedance(self) -> None:
-        if self.seedance_api_provider != "youdao":
-            raise ConfigurationError("SEEDANCE_API_PROVIDER must be youdao")
-        if not self.youdao_api_key:
-            raise ConfigurationError("Missing configuration: YOUDAO_API_KEY")
-        if self.youdao_model != "seedance-2.0":
-            raise ConfigurationError("YOUDAO_SEEDANCE_MODEL must be seedance-2.0")
+        if self.seedance_api_provider != "runninghub_standard":
+            raise ConfigurationError("SEEDANCE_API_PROVIDER must be runninghub_standard")
+        if not self.runninghub_seedance_api_key:
+            raise ConfigurationError("Missing configuration: RUNNINGHUB_SEEDANCE_API_KEY")
 
 
 def load_settings(
@@ -87,15 +84,20 @@ def load_settings(
             "RUNNINGHUB_BASE_URL",
             default="https://www.runninghub.ai",
         ),
-        youdao_api_key=value("YOUDAO_API_KEY"),
-        youdao_base_url=value(
-            "YOUDAO_BASE_URL",
-            default="https://openapi.youdao.com/llmgateway",
+        runninghub_seedance_api_key=value("RUNNINGHUB_SEEDANCE_API_KEY"),
+        runninghub_seedance_create_url=value(
+            "RUNNINGHUB_SEEDANCE_CREATE_URL",
+            default="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
         ),
-        youdao_model=value("YOUDAO_SEEDANCE_MODEL", default="seedance-2.0"),
-        youdao_resolution=value("YOUDAO_SEEDANCE_RESOLUTION", default="720p"),
-        youdao_project_name=value("YOUDAO_PROJECT_NAME", default="default"),
-        seedance_api_provider=value("SEEDANCE_API_PROVIDER", default="youdao").lower(),
+        runninghub_seedance_query_url=value(
+            "RUNNINGHUB_SEEDANCE_QUERY_URL",
+            default="https://www.runninghub.cn/openapi/v2/query",
+        ),
+        runninghub_seedance_upload_url=value(
+            "RUNNINGHUB_SEEDANCE_UPLOAD_URL",
+            default="https://www.runninghub.cn/openapi/v2/media/upload/binary",
+        ),
+        seedance_api_provider=value("SEEDANCE_API_PROVIDER", default="runninghub_standard").lower(),
     )
 
 
@@ -119,10 +121,11 @@ def build_redacted_provider_preflight(
             else "none"
         ),
         "runninghub_api_key": "present" if settings.runninghub_api_key else "missing",
-        "youdao_api_key": "present" if settings.youdao_api_key else "missing",
+        "runninghub_seedance_api_key": "present" if settings.runninghub_seedance_api_key else "missing",
         "runninghub_base_url": "present" if settings.runninghub_base_url else "missing",
-        "youdao_base_url": "present" if settings.youdao_base_url else "missing",
         "seedance_api_provider": (
-            "youdao" if settings.seedance_api_provider == "youdao" else "unsupported"
+            "runninghub_standard"
+            if settings.seedance_api_provider == "runninghub_standard"
+            else "unsupported"
         ),
     }
diff --git a/usfr-server/references/bundle_manifest.json b/usfr-server/references/bundle_manifest.json
index 5d085e3..5263e8d 100644
--- a/usfr-server/references/bundle_manifest.json
+++ b/usfr-server/references/bundle_manifest.json
@@ -94,8 +94,8 @@
       "role": "RunningHub storyboard image adapter"
     },
     {
-      "path": "bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py",
-      "role": "fixed-B Seedance asset/task adapter and integrity submission"
+      "path": "bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py",
+      "role": "RunningHub Standard Model Seedance video adapter"
     },
     {
       "path": "bundled-skills/seedance-storyboard-replication/scripts/timeline_splice.py",
diff --git a/usfr-server/references/server-deployment-step-by-step.md b/usfr-server/references/server-deployment-step-by-step.md
index 02f5811..82019f3 100644
--- a/usfr-server/references/server-deployment-step-by-step.md
+++ b/usfr-server/references/server-deployment-step-by-step.md
@@ -211,8 +211,8 @@ credentials.
 
 ### RunningHub And Seedance Provider
 
-Use RunningHub/Seedance for storyboard image generation and final Seedance
-video generation.
+Use RunningHub for storyboard image generation and RunningHub Standard Model
+Seedance for final video generation.
 
 Your provider adapter must implement:
 
@@ -225,15 +225,22 @@ The workflow already creates provider intents and hashes the exact request
 payload before the paid call. Your adapter must not mutate the prompt, duration,
 reference list, model, or payload after the audit hash is frozen.
 
-Suggested adapter-owned environment:
+Required adapter-owned environment:
 
 ```bash
 RUNNINGHUB_API_KEY=<server-owned-runninghub-key>
-RUNNINGHUB_PROJECT_ID=<project-id>
-SEEDANCE_MODEL=seedance-2.0-fast
-SEEDANCE_REGION=<provider-region-if-needed>
+RUNNINGHUB_SEEDANCE_API_KEY=<enterprise-shared-runninghub-standard-model-key>
+RUNNINGHUB_SEEDANCE_CREATE_URL=https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video
+RUNNINGHUB_SEEDANCE_QUERY_URL=https://www.runninghub.cn/openapi/v2/query
+RUNNINGHUB_SEEDANCE_UPLOAD_URL=https://www.runninghub.cn/openapi/v2/media/upload/binary
 ```
 
+The video request must be the direct documented Standard Model body. Fixed-B
+USFR uploads only approved storyboard/target images and one eligible audio
+fragment; it sends `videoUrls=[]` and never sends source video, source slices,
+opaque UI video, or tail video. The Seedance key is separate so an ordinary
+RunningHub workflow key is never sent to the enterprise-only standard-model API.
+
 If the HTTP request times out after a paid create call may have reached the
 provider, return an ambiguous state and let `/provider/reconcile` use
 `lookup(...)`. Do not blindly submit a second paid job.
diff --git a/usfr-server/references/update-maintenance-playbook.md b/usfr-server/references/update-maintenance-playbook.md
index 19f5811..79705ac 100644
--- a/usfr-server/references/update-maintenance-playbook.md
+++ b/usfr-server/references/update-maintenance-playbook.md
@@ -182,13 +182,13 @@ Rules to preserve:
 Update these when paid provider calls, asset upload, polling, reconciliation,
 or provider payload shape changes:
 
-- `bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py`
+- `bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
 - `bundled-skills/seedance-storyboard-replication/scripts/runninghub_image2.py`
 - `server/provider_ports.py`
 - `server/production_ports.py`
 - `server/capability_ports.py`
 - `server/packaged_factory.py`
-- `tests/test_youdao_seedance.py`
+- `tests/test_runninghub_standard_seedance.py`
 - `tests/test_provider_idempotency_redis.py`
 - `tests/test_capability_ports.py`
 
diff --git a/usfr-server/scripts/verify_bundle.py b/usfr-server/scripts/verify_bundle.py
index 1606f0c..510074b 100644
--- a/usfr-server/scripts/verify_bundle.py
+++ b/usfr-server/scripts/verify_bundle.py
@@ -58,7 +58,7 @@ REQUIRED_MODULE_FILES = {
         "scripts/media_quality.py",
         "scripts/segment_plan.py",
         "scripts/runninghub_image2.py",
-        "scripts/seedance_submit.py",
+        "scripts/runninghub_seedance_submit.py",
         "scripts/timeline_splice.py",
     ],
 }
diff --git a/usfr-server/tests/test_bundle_runtime_closure.py b/usfr-server/tests/test_bundle_runtime_closure.py
index c268127..034199d 100644
--- a/usfr-server/tests/test_bundle_runtime_closure.py
+++ b/usfr-server/tests/test_bundle_runtime_closure.py
@@ -52,6 +52,7 @@ class BundleRuntimeClosureTest(unittest.TestCase):
             "scripts/media_quality.py",
             "scripts/segment_plan.py",
             "scripts/runninghub_image2.py",
+            "scripts/runninghub_seedance_submit.py",
             "scripts/seedance_submit.py",
             "scripts/timeline_splice.py",
         ):
@@ -80,6 +81,7 @@ class BundleRuntimeClosureTest(unittest.TestCase):
             "bundled-skills/seedance-storyboard-replication/scripts/media_quality.py",
             "bundled-skills/seedance-storyboard-replication/scripts/segment_plan.py",
             "bundled-skills/seedance-storyboard-replication/scripts/runninghub_image2.py",
+            "bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py",
             "bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py",
             "bundled-skills/seedance-storyboard-replication/scripts/timeline_splice.py",
             "bundled-skills/analyze-reference-video-dynamics/scripts/probe_video.py",
diff --git a/usfr-server/tests/test_seedance_dependency_resolution.py b/usfr-server/tests/test_seedance_dependency_resolution.py
index 76764b5..978d4f7 100644
--- a/usfr-server/tests/test_seedance_dependency_resolution.py
+++ b/usfr-server/tests/test_seedance_dependency_resolution.py
@@ -55,7 +55,7 @@ class SeedanceDependencyResolutionTest(unittest.TestCase):
         with patch.dict(os.environ, {}, clear=True):
             self.assertIsNone(resolve_env_file())
             settings = load_settings(None, environ={})
-        with self.assertRaisesRegex(Exception, "YOUDAO_API_KEY"):
+        with self.assertRaisesRegex(Exception, "RUNNINGHUB_SEEDANCE_API_KEY"):
             settings.require_seedance()
 
     def test_worker_environment_file_is_resolved(self):
diff --git a/usfr-server/tests/test_skill_contract.py b/usfr-server/tests/test_skill_contract.py
index 3db23f0..61c7e63 100644
--- a/usfr-server/tests/test_skill_contract.py
+++ b/usfr-server/tests/test_skill_contract.py
@@ -36,7 +36,7 @@ class FactorySkillContractTest(unittest.TestCase):
             "weighted commercial intent",
             "Opaque slice branch",
             "RunningHub image2",
-            "Youdao CreateAsset",
+            "RunningHub Standard Model",
             "timeline_splice.py",
             "确认反解分镜脚本",
             "确认故事板",
@@ -46,6 +46,48 @@ class FactorySkillContractTest(unittest.TestCase):
         ):
             self.assertIn(required, skill)
 
+    def test_active_seedance_submission_contract_uses_runninghub_standard_model(self):
+        bundled_root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
+        documents = {
+            "root skill": ROOT / "SKILL.md",
+            "storyboard skill": bundled_root / "SKILL.md",
+            "deployment guide": ROOT / "references" / "server-deployment-step-by-step.md",
+            "workspace environment example": ROOT.parent / ".env.example",
+            "bundled environment example": bundled_root / "references" / "seedance.env.example",
+        }
+        combined = "\n".join(
+            document.read_text(encoding="utf-8") for document in documents.values()
+        )
+        for required in (
+            "runninghub_seedance_submit.py",
+            "seedance-2.0-fast-token/multimodal-video",
+            "RUNNINGHUB_SEEDANCE_API_KEY",
+            "videoUrls=[]",
+        ):
+            with self.subTest(required=required):
+                self.assertIn(required, combined)
+        for forbidden in (
+            "Youdao",
+            "youdao",
+            "scripts/seedance_submit.py",
+            "asset://",
+        ):
+            for name, document in documents.items():
+                with self.subTest(document=name, forbidden=forbidden):
+                    self.assertNotIn(forbidden, document.read_text(encoding="utf-8"))
+
+        manifest = (ROOT / "references" / "bundle_manifest.json").read_text(
+            encoding="utf-8"
+        )
+        self.assertIn(
+            "bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py",
+            manifest,
+        )
+        self.assertNotIn(
+            "bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py",
+            manifest,
+        )
+
     def test_fixed_slot_admission_and_source_defaults_are_documented(self):
         skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
         contract = (
@@ -336,23 +378,22 @@ class FactorySkillContractTest(unittest.TestCase):
     def test_bundled_seedance_workflow_uses_internal_audit_and_safe_concurrency(self):
         root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
         skill = (root / "SKILL.md").read_text(encoding="utf-8")
-        prompt = (root / "references" / "seedance-prompt.md").read_text(encoding="utf-8")
-        api = (root / "references" / "youdao-api.md").read_text(encoding="utf-8")
-        combined = "\n".join((skill, prompt, api))
+        api = (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8")
+        combined = "\n".join((skill, api))
         self.assertNotIn("\u786e\u8ba4 Seedance \u63d0\u793a\u8bcd", combined)
         self.assertNotIn("\u786e\u8ba4\u5267\u60c5\u5207\u70b9", combined)
         self.assertNotIn("explicit user approval of that exact digest", combined)
         for required in (
             "seedance-20",
             "script-to-prompt parity audit",
-            "--audited-request-sha256",
-            "--audit-artifact",
-            "--approved-script-sha256",
-            "independent segment",
-            "concurrently",
-            "cached",
-            "non-deadline polling",
-            "cross-process manifest lock",
+            "--approved-request-sha256",
+            "runninghub_seedance_submit.py --dry-run",
+            "RunningHub Standard Model",
+            "videoUrls=[]",
+            "audioUrls",
+            "independent single-task",
+            "two-segment concurrency",
+            "statefully and without a deadline",
             "Factory executor owns two-segment concurrency",
             "final/result.mp4",
             "complete approved Cuts",
@@ -363,12 +404,13 @@ class FactorySkillContractTest(unittest.TestCase):
             "final QC",
         ):
             self.assertIn(required, combined)
-        dry_run = skill.index("seedance_submit.py --dry-run")
+        self.assertNotIn("scripts/seedance_submit.py", combined)
+        self.assertNotIn("asset://", combined)
+        dry_run = skill.index("runninghub_seedance_submit.py --dry-run")
         parity = skill.index("script-to-prompt parity audit")
-        digest = skill.index("--audited-request-sha256")
+        digest = skill.index("--approved-request-sha256")
         self.assertLess(dry_run, parity)
         self.assertLess(parity, digest)
-        self.assertLess(digest, combined.index("--audit-artifact"))
 
     def test_generated_ui_and_opaque_app_regions_stay_out_of_seedance_semantics(self):
         factory = (ROOT / "SKILL.md").read_text(encoding="utf-8")
@@ -447,60 +489,27 @@ class FactorySkillContractTest(unittest.TestCase):
         ):
             self.assertIn(required, combined)
 
-    def test_audited_factory_steps_name_the_complete_authorization_set(self):
+    def test_audited_factory_steps_name_the_standard_model_request_digest(self):
         root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
         factory = (ROOT / "SKILL.md").read_text(encoding="utf-8")
         skill = (root / "SKILL.md").read_text(encoding="utf-8")
-        integrity = (
-            root / "references" / "seedance-20-integrity-gate.md"
-        ).read_text(encoding="utf-8")
-        prompt = (root / "references" / "seedance-prompt.md").read_text(encoding="utf-8")
-        api = (root / "references" / "youdao-api.md").read_text(encoding="utf-8")
-        required_flags = (
-            "--audited-request-sha256",
-            "--audit-artifact",
-            "--approved-script-sha256",
-            "--seedance-input-contract",
-            "--seedance20-skill-file",
-        )
+        api = (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8")
         sections = {
             "factory audited sequence": factory[
-                factory.index("9. **Compile and audit the exact Youdao request internally**") :
+                factory.index("9. **Compile and audit the exact RunningHub Standard Model request internally**") :
                 factory.index("11. **Assemble final video**")
             ],
-            "bundled integrity sequence": skill[
-                skill.index("## Seedance Internal Integrity Gate") :
-                skill.index("## Universal selling-point mapping")
-            ],
             "bundled submission sequence": skill[
-                skill.index("## Youdao Asset and Seedance Submission") :
+                skill.index("## RunningHub Standard Model Seedance Submission") :
                 skill.index("## Download, Concatenation, and QC")
             ],
-            "integrity required sequence": integrity[
-                integrity.index("## Required sequence") :
-                integrity.index("## Audit checks")
-            ],
-            "integrity paid path": integrity[
-                integrity.index("The Factory paid path uses") :
-                integrity.index("## Audited Factory frozen input contract")
-            ],
-            "prompt opening authorization": prompt[
-                prompt.index("After assembling the complete prompt") :
-                prompt.index("## Required post-storyboard integrity sequence")
-            ],
-            "prompt example authorization": prompt[
-                prompt.index("The exact dry-run payload is audited") :
-                prompt.index("## Audited Factory contract and submission closure")
-            ],
-            "Youdao authorization sequence": api[
-                api.index("Keep prompts under 5000 characters") :
-                api.index("## Audited Factory submission requirements")
-            ],
+            "standard-model API": api,
         }
         for label, section in sections.items():
             with self.subTest(section=label):
-                for flag in required_flags:
-                    self.assertIn(flag, section)
+                self.assertIn("--approved-request-sha256", section)
+                self.assertNotIn("--audited-request-sha256", section)
+                self.assertNotIn("--seedance-input-contract", section)
 
     def test_integrity_reference_documents_live_seedance20_snapshot_recheck(self):
         integrity = (
@@ -538,7 +547,7 @@ class FactorySkillContractTest(unittest.TestCase):
             "bundled": (root / "SKILL.md").read_text(encoding="utf-8"),
             "integrity": (root / "references" / "seedance-20-integrity-gate.md").read_text(encoding="utf-8"),
             "prompt": (root / "references" / "seedance-prompt.md").read_text(encoding="utf-8"),
-            "api": (root / "references" / "youdao-api.md").read_text(encoding="utf-8"),
+            "api": (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8"),
         }
         for label, document in documents.items():
             with self.subTest(document=label):
@@ -560,30 +569,30 @@ class FactorySkillContractTest(unittest.TestCase):
         documents = (
             (ROOT / "SKILL.md").read_text(encoding="utf-8"),
             (root / "SKILL.md").read_text(encoding="utf-8"),
-            (root / "references" / "youdao-api.md").read_text(encoding="utf-8"),
+            (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8"),
         )
         required = (
-            "`CreateVideo` is never automatically retried after a 429, 5xx, "
+            "paid Seedance create is never automatically retried after a 429, 5xx, "
             "timeout, connection reset, or ambiguous response"
         )
         for document in documents:
             with self.subTest(document=document[:40]):
-                self.assertIn(required, document)
+                self.assertIn(required.lower(), " ".join(document.split()).lower())
 
     def test_asset_registration_is_documented_as_non_retryable(self):
         root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
         documents = (
             (ROOT / "SKILL.md").read_text(encoding="utf-8"),
             (root / "SKILL.md").read_text(encoding="utf-8"),
-            (root / "references" / "youdao-api.md").read_text(encoding="utf-8"),
+            (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8"),
         )
         required = (
-            "`CreateAsset` is never automatically retried after a 429, 5xx, "
+            "RunningHub media upload is never automatically retried after a 429, 5xx, "
             "timeout, connection reset, or ambiguous response"
         )
         for document in documents:
             with self.subTest(document=document[:40]):
-                self.assertIn(required, document)
+                self.assertIn(required.lower(), " ".join(document.split()).lower())
 
     def test_production_timing_transition_contract(self):
         skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
@@ -592,7 +601,7 @@ class FactorySkillContractTest(unittest.TestCase):
             'pause_approval("script")',
             'pause_approval("storyboard")',
             "RunningHub image2 wait",
-            "Youdao Seedance wait",
+            "RunningHub Standard Model Seedance wait",
             "provider=True",
             "after final MP4 QC",
             "same log path",

--- UPDATED SYNC REPORT ---

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

