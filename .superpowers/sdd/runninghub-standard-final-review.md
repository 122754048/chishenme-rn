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
diff --git a/backend/app/background_music_execution.py b/backend/app/background_music_execution.py
index 0e3d3db..e6ff91a 100644
--- a/backend/app/background_music_execution.py
+++ b/backend/app/background_music_execution.py
@@ -102,15 +102,44 @@ def _validated_audio_asset_receipt(
     receipt: Mapping[str, object],
     *,
     uploaded_audio_sha256: str,
+    music_timeline_contract: Mapping[str, object],
 ) -> dict[str, object]:
-    uri = receipt.get("asset_uri") if isinstance(receipt, Mapping) else None
+    audio_url = receipt.get("runninghub_audio_url") if isinstance(receipt, Mapping) else None
+    duration_seconds = receipt.get("duration_seconds") if isinstance(receipt, Mapping) else None
+    segment = receipt.get("seedance_segment") if isinstance(receipt, Mapping) else None
+    segment_start_ms = segment.get("start_ms") if isinstance(segment, Mapping) else None
+    segment_end_ms = segment.get("end_ms") if isinstance(segment, Mapping) else None
+    output_duration_ms = music_timeline_contract.get("output_duration_ms")
+    windows = music_timeline_contract.get("windows")
+    silence_windows = music_timeline_contract.get("meaningful_silence_output_intervals")
+    output_starts = [
+        item.get("output_start_ms")
+        for item in [*(windows if isinstance(windows, list) else []), *(silence_windows if isinstance(silence_windows, list) else [])]
+        if isinstance(item, Mapping)
+    ]
+    canonical_start_ms = min(output_starts) if output_starts and all(isinstance(value, int) and not isinstance(value, bool) for value in output_starts) else None
     if (
         not isinstance(receipt, Mapping)
         or receipt.get("asset_type") != "Audio"
-        or receipt.get("status") != "active"
+        or receipt.get("provider") != "runninghub"
+        or receipt.get("status") != "completed"
         or receipt.get("uploaded_audio_sha256") != uploaded_audio_sha256
-        or not isinstance(uri, str)
-        or not uri.startswith("asset://asset-")
+        or not isinstance(audio_url, str)
+        or not audio_url.startswith("https://")
+        or "asset://" in audio_url
+        or isinstance(duration_seconds, bool)
+        or not isinstance(duration_seconds, (int, float))
+        or not 2 <= duration_seconds <= 15
+        or receipt.get("clip_kind") != "seedance_segment"
+        or isinstance(segment_start_ms, bool)
+        or isinstance(segment_end_ms, bool)
+        or not isinstance(segment_start_ms, int)
+        or not isinstance(segment_end_ms, int)
+        or segment_start_ms < 0
+        or segment_end_ms <= segment_start_ms
+        or segment_end_ms - segment_start_ms != round(duration_seconds * 1_000)
+        or segment_start_ms != canonical_start_ms
+        or segment_end_ms != output_duration_ms
     ):
         raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
     return dict(receipt)
@@ -135,7 +164,7 @@ def _validated_music_windows(
     return [dict(window) for window in windows if isinstance(window, Mapping)]
 
 
-def _provider_payload(*, asset_uri: str, performance: Mapping[str, object]) -> dict[str, object]:
+def _provider_payload(*, runninghub_audio_url: str, performance: Mapping[str, object]) -> dict[str, object]:
     mode = performance.get("mode")
     if mode == "verified_singing":
         lines = performance.get("singing_lines")
@@ -222,10 +251,8 @@ def _provider_payload(*, asset_uri: str, performance: Mapping[str, object]) -> d
         raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")
     return {
         "model": "seedance-2.0",
-        "content": [
-            {"type": "text", "text": text},
-            {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": asset_uri}},
-        ],
+        "prompt": text,
+        "audioUrls": [runninghub_audio_url],
     }
 
 
@@ -293,6 +320,7 @@ def compile_background_music_execution_contract(
     asset_receipt = _validated_audio_asset_receipt(
         audio_asset_receipt,
         uploaded_audio_sha256=str(uploaded["sha256"]),
+        music_timeline_contract=music_timeline_contract,
     )
     try:
         uploaded_audio_route = route_uploaded_audio(source_content_timeline)
@@ -303,7 +331,10 @@ def compile_background_music_execution_contract(
     except ReplicationError as error:
         raise _background_music_error(error) from error
     _validate_verified_singing_windows(performance=performance, music_windows=windows)
-    payload = _provider_payload(asset_uri=str(asset_receipt["asset_uri"]), performance=performance)
+    payload = _provider_payload(
+        runninghub_audio_url=str(asset_receipt["runninghub_audio_url"]),
+        performance=performance,
+    )
     execution = {
         "contract": BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1,
         "mode": performance["mode"],
@@ -1650,27 +1681,48 @@ class BackgroundMusicStagePort:
                 or _canonical_json_bytes(execution_performance) != _canonical_json_bytes(frozen_performance[0])
             ):
                 raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
-        asset_uri = receipt.get("asset_uri")
+        runninghub_audio_url = receipt.get("runninghub_audio_url")
+        duration_seconds = receipt.get("duration_seconds")
+        segment = receipt.get("seedance_segment")
+        segment_start_ms = segment.get("start_ms") if isinstance(segment, Mapping) else None
+        segment_end_ms = segment.get("end_ms") if isinstance(segment, Mapping) else None
         if (
             receipt.get("asset_type") != "Audio"
             or receipt.get("uploaded_audio_sha256") != uploaded.get("sha256")
-            or receipt.get("status") != "active"
-            or not isinstance(asset_uri, str)
-            or not asset_uri.startswith("asset://asset-")
+            or receipt.get("provider") != "runninghub"
+            or receipt.get("status") != "completed"
+            or not isinstance(runninghub_audio_url, str)
+            or not runninghub_audio_url.startswith("https://")
+            or "asset://" in runninghub_audio_url
+            or isinstance(duration_seconds, bool)
+            or not isinstance(duration_seconds, (int, float))
+            or not 2 <= duration_seconds <= 15
+            or receipt.get("clip_kind") != "seedance_segment"
+            or isinstance(segment_start_ms, bool)
+            or isinstance(segment_end_ms, bool)
+            or not isinstance(segment_start_ms, int)
+            or not isinstance(segment_end_ms, int)
+            or segment_start_ms < 0
+            or segment_end_ms <= segment_start_ms
+            or segment_end_ms - segment_start_ms != round(duration_seconds * 1_000)
             or "reference_audios" in payload
         ):
             raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
-        content = payload.get("content")
-        if not isinstance(content, list):
-            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
-        text_items = [item.get("text") for item in content if isinstance(item, Mapping) and item.get("type") == "text"]
-        audio_items = [item for item in content if isinstance(item, Mapping) and item.get("type") == "audio_url"]
+        try:
+            _validated_audio_asset_receipt(
+                receipt,
+                uploaded_audio_sha256=str(uploaded.get("sha256")),
+                music_timeline_contract=execution_timeline,
+            )
+        except ValueError as error:
+            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID") from error
         if (
-            not any(isinstance(text, str) and "@Audio1" in text for text in text_items)
-            or len(audio_items) != 1
-            or audio_items[0].get("role") != "reference_audio"
-            or not isinstance(audio_items[0].get("audio_url"), Mapping)
-            or audio_items[0]["audio_url"].get("url") != asset_uri
+            not isinstance(payload.get("prompt"), str)
+            or "@Audio1" not in payload["prompt"]
+            or payload.get("audioUrls") != [runninghub_audio_url]
+            or "content" in payload
+            or "audio_url" in payload
+            or "asset://" in json.dumps(payload, ensure_ascii=False, sort_keys=True)
         ):
             raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
         enriched = dict(result)
diff --git a/backend/app/background_music_local_mvp.py b/backend/app/background_music_local_mvp.py
index 12e036c..8def58d 100644
--- a/backend/app/background_music_local_mvp.py
+++ b/backend/app/background_music_local_mvp.py
@@ -7,7 +7,7 @@ the commercial deployment adapter.
 
 from __future__ import annotations
 
-from collections.abc import Mapping, Sequence
+from collections.abc import Callable, Mapping, Sequence
 from contextlib import contextmanager
 from dataclasses import dataclass, field
 from fractions import Fraction
@@ -232,8 +232,14 @@ class _LocalProviderAdapter:
 class DevelopmentOnlyBackgroundMusicMvpHarness:
     """Run a deterministic local media loop without a network Provider or TTS."""
 
-    def __init__(self, *, run_root: Path) -> None:
+    def __init__(
+        self,
+        *,
+        run_root: Path,
+        runninghub_audio_upload: Callable[[Path, Mapping[str, object]], Mapping[str, object]],
+    ) -> None:
         self._run_root = Path(run_root)
+        self._runninghub_audio_upload = runninghub_audio_upload
 
     def run(
         self,
@@ -266,7 +272,15 @@ class DevelopmentOnlyBackgroundMusicMvpHarness:
         timeline_evidence = _evidence(timeline_result)
         timeline_reference = _mapping(timeline_evidence, "music_timeline_contract_artifact")
         frozen_contract = self._materialize_frozen_contract(context=context, reference=timeline_reference)
-        audio_asset_receipt = self._audio_asset_receipt(uploaded)
+        seedance_clip_path, seedance_clip = self._materialize_seedance_segment_clip(
+            uploaded_path=uploaded_path,
+            uploaded=uploaded,
+            music_timeline_contract=frozen_contract,
+        )
+        audio_asset_receipt = self._upload_audio_to_runninghub(
+            seedance_clip_path=seedance_clip_path,
+            seedance_clip=seedance_clip,
+        )
         performance_line_contract = self._performance_line_contract(
             contract=frozen_contract,
             visible_singer_regions=visible_singer_regions,
@@ -846,32 +860,91 @@ class DevelopmentOnlyBackgroundMusicMvpHarness:
         )
         return {**reference, "kind": kind}
 
-    def _audio_asset_receipt(self, uploaded: Mapping[str, object]) -> dict[str, object]:
-        digest = str(uploaded["sha256"])
-        return {
-            "AssetType": "Audio",
-            "asset_type": "Audio",
-            "asset_uri": f"asset://asset-{digest[:16]}",
-            "status": "active",
-            "uploaded_audio_sha256": digest,
+    def _upload_audio_to_runninghub(
+        self,
+        *,
+        seedance_clip_path: Path,
+        seedance_clip: Mapping[str, object],
+    ) -> dict[str, object]:
+        """Materialize a real provider upload receipt before Seedance submission."""
+
+        if not seedance_clip_path.is_file():
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID")
+        try:
+            receipt = self._runninghub_audio_upload(seedance_clip_path, seedance_clip)
+        except Exception as error:
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID") from error
+        if not isinstance(receipt, Mapping):
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID")
+        returned = dict(receipt)
+        if (
+            returned.get("uploaded_audio_sha256") != seedance_clip.get("uploaded_audio_sha256")
+            or returned.get("duration_seconds") != seedance_clip.get("duration_seconds")
+            or returned.get("clip_kind") != "seedance_segment"
+            or returned.get("seedance_segment") != seedance_clip.get("seedance_segment")
+        ):
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID")
+        return returned
+
+    def _materialize_seedance_segment_clip(
+        self,
+        *,
+        uploaded_path: Path,
+        uploaded: Mapping[str, object],
+        music_timeline_contract: Mapping[str, object],
+    ) -> tuple[Path, dict[str, object]]:
+        """Create the only provider-facing audio: a bounded Seedance segment clip."""
+
+        output_duration_ms = music_timeline_contract.get("output_duration_ms")
+        if (
+            isinstance(output_duration_ms, bool)
+            or not isinstance(output_duration_ms, int)
+            or not 2_000 <= output_duration_ms <= 15_000
+        ):
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID")
+        source_duration = self._probe_duration(uploaded_path)
+        clip_duration_seconds = output_duration_ms / 1_000
+        if source_duration < clip_duration_seconds:
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID")
+        clip_path = self._run_root / "provider" / "seedance_segment_clip.wav"
+        clip_path.parent.mkdir(parents=True, exist_ok=True)
+        self._run_command(
+            [
+                "ffmpeg",
+                "-hide_banner",
+                "-loglevel",
+                "error",
+                "-y",
+                "-i",
+                str(uploaded_path),
+                "-map",
+                "0:a:0",
+                "-vn",
+                "-t",
+                str(clip_duration_seconds),
+                "-c:a",
+                "pcm_s16le",
+                str(clip_path),
+            ]
+        )
+        if not clip_path.is_file() or abs(self._probe_duration(clip_path) - clip_duration_seconds) > 0.05:
+            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID")
+        return clip_path, {
+            "uploaded_audio_sha256": uploaded["sha256"],
+            "seedance_audio_sha256": _sha256_file(clip_path),
+            "content_type": "audio/wav",
+            "duration_seconds": clip_duration_seconds,
+            "clip_kind": "seedance_segment",
+            "seedance_segment": {"start_ms": 0, "end_ms": output_duration_ms},
         }
 
     @staticmethod
     def _provider_payload(audio_asset_receipt: Mapping[str, object]) -> dict[str, object]:
-        asset_uri = str(audio_asset_receipt["asset_uri"])
+        runninghub_audio_url = str(audio_asset_receipt["runninghub_audio_url"])
         return {
-            "content": [
-                {
-                    "text": "Use @Audio1 as the uploaded-song reference. Preserve the frozen frame windows without looping, time stretch, pitch shift, or generated replacement.",
-                    "type": "text",
-                },
-                {
-                    "audio_url": {"url": asset_uri},
-                    "role": "reference_audio",
-                    "type": "audio_url",
-                },
-            ],
             "model": "seedance-2.0",
+            "prompt": "Use @Audio1 as the uploaded-song reference. Preserve the frozen frame windows without looping, time stretch, pitch shift, or generated replacement.",
+            "audioUrls": [runninghub_audio_url],
         }
 
     def _mix_exact_uploaded_fragments(
diff --git a/backend/tests/test_background_music_execution.py b/backend/tests/test_background_music_execution.py
index 9c191eb..0bfee0a 100644
--- a/backend/tests/test_background_music_execution.py
+++ b/backend/tests/test_background_music_execution.py
@@ -289,9 +289,13 @@ class _AuditedMusicPort:
         evidence = {
             "audio_asset_receipt": {
                 "asset_type": "Audio",
-                "asset_uri": "asset://asset-song",
+                "provider": "runninghub",
+                "runninghub_audio_url": "https://runninghub.example/openapi/song-clip.mp3",
                 "uploaded_audio_sha256": "b" * 64,
-                "status": "active",
+                "duration_seconds": 2.0,
+                "clip_kind": "seedance_segment",
+                "seedance_segment": {"start_ms": 0, "end_ms": 2_000},
+                "status": "completed",
             },
             "provider_payload": self.payload,
         }
@@ -432,6 +436,13 @@ def _complete_music_timing(contract: dict[str, object]) -> None:
         "output_duration_ms",
         max((int(window["output_end_ms"]) for window in windows if isinstance(window, dict)), default=0),
     )
+    if int(contract["output_duration_ms"]) < 2_000:
+        prior_end = int(contract["output_duration_ms"])
+        contract["meaningful_silence_output_intervals"] = [
+            *contract["meaningful_silence_output_intervals"],
+            {"output_start_ms": prior_end, "output_end_ms": 2_000},
+        ]
+        contract["output_duration_ms"] = 2_000
 
 
 def _music_timeline() -> dict[str, object]:
@@ -458,8 +469,8 @@ def _music_timeline() -> dict[str, object]:
             }
         ],
         "visible_singer_regions": [],
-        "meaningful_silence_output_intervals": [],
-        "output_duration_ms": 1000,
+        "meaningful_silence_output_intervals": [{"output_start_ms": 1000, "output_end_ms": 2000}],
+        "output_duration_ms": 2000,
     }
 
 
@@ -534,12 +545,36 @@ def _non_singing_source_timeline() -> dict[str, object]:
 def _audio_asset_receipt() -> dict[str, object]:
     return {
         "asset_type": "Audio",
-        "asset_uri": "asset://asset-song",
-        "status": "active",
+        "provider": "runninghub",
+        "runninghub_audio_url": "https://runninghub.example/openapi/song-clip.mp3",
+        "duration_seconds": 2.0,
+        "clip_kind": "seedance_segment",
+        "seedance_segment": {"start_ms": 0, "end_ms": 2_000},
+        "status": "completed",
         "uploaded_audio_sha256": "b" * 64,
     }
 
 
+def _audio_asset_receipt_for_timeline(
+    contract: dict[str, object],
+    *,
+    uploaded_audio_sha256: str = "b" * 64,
+) -> dict[str, object]:
+    starts = [
+        item["output_start_ms"]
+        for item in [*contract["windows"], *contract["meaningful_silence_output_intervals"]]
+        if isinstance(item, dict)
+    ]
+    start_ms = min(starts)
+    end_ms = int(contract["output_duration_ms"])
+    return {
+        **_audio_asset_receipt(),
+        "uploaded_audio_sha256": uploaded_audio_sha256,
+        "duration_seconds": (end_ms - start_ms) / 1_000,
+        "seedance_segment": {"start_ms": start_ms, "end_ms": end_ms},
+    }
+
+
 def _execution_contract_for(
     music_timeline_contract: dict[str, object],
     *,
@@ -549,7 +584,7 @@ def _execution_contract_for(
     return background_music_execution.compile_background_music_execution_contract(
         uploaded_audio=_uploaded_music(),
         music_timeline_contract=music_timeline_contract,
-        audio_asset_receipt=_audio_asset_receipt(),
+        audio_asset_receipt=_audio_asset_receipt_for_timeline(music_timeline_contract),
         source_content_timeline=(
             _confirmed_sung_source_timeline()
             if intent == "verified_singing"
@@ -625,9 +660,10 @@ def _materialized_music_case(
 ) -> tuple[dict[str, object], dict[str, object], _MediaPortContext, dict[str, object], dict[str, object]]:
     tmp_path.mkdir(parents=True, exist_ok=True)
     _complete_music_timing(contract)
-    uploaded_pcm = b"\x01\x00\x01\x00" * 48_000
+    music_pcm = b"\x01\x00\x01\x00" * 48_000
+    uploaded_pcm = music_pcm * 2
     uploaded_bytes = _pcm_wav_bytes(uploaded_pcm)
-    final_audio_bytes = uploaded_bytes
+    final_audio_bytes = _pcm_wav_bytes(music_pcm + b"\0" * len(music_pcm))
     uploaded = {
         **_uploaded_music(),
         "object_key": "uploads/batch-scope/song.wav",
@@ -638,7 +674,10 @@ def _materialized_music_case(
     execution = background_music_execution.compile_background_music_execution_contract(
         uploaded_audio=uploaded,
         music_timeline_contract=contract,
-        audio_asset_receipt={**_audio_asset_receipt(), "uploaded_audio_sha256": uploaded["sha256"]},
+        audio_asset_receipt=_audio_asset_receipt_for_timeline(
+            contract,
+            uploaded_audio_sha256=uploaded["sha256"],
+        ),
         source_content_timeline=(
             _confirmed_sung_source_timeline()
             if intent == "verified_singing"
@@ -726,7 +765,7 @@ def _materialized_music_case(
             "-f",
             "lavfi",
             "-i",
-            "color=c=black:s=16x16:r=30:d=1",
+            "color=c=black:s=16x16:r=30:d=2",
             *offset_args,
             "-i",
             str(video_audio_path),
@@ -774,7 +813,7 @@ def _materialized_music_case(
             (final_video_reference, final_video_path),
         ),
     )
-    pcm_fragment_sha = hashlib.sha256(uploaded_pcm).hexdigest()
+    pcm_fragment_sha = hashlib.sha256(music_pcm).hexdigest()
     receipt = {
         "passed": True,
         "mode": execution["mode"],
@@ -872,7 +911,11 @@ def test_uploaded_song_is_the_final_audio_authority_without_time_or_pitch_transf
             final_mix_receipt=_final_mix_receipt(execution_contract=execution),
         )
 
-    text = execution["provider_payload"]["content"][0]["text"]
+    payload = execution["provider_payload"]
+    assert payload["audioUrls"] == ["https://runninghub.example/openapi/song-clip.mp3"]
+    assert "content" not in payload
+    assert "asset://" not in json.dumps(payload)
+    text = payload["prompt"]
     assert "@Audio1" in text
     assert '"Hold on"' in text
     assert "Line L01" in text
@@ -889,6 +932,75 @@ def test_uploaded_song_is_the_final_audio_authority_without_time_or_pitch_transf
     ).hexdigest()
 
 
+def test_background_music_execution_requires_a_duration_bound_runninghub_upload_receipt():
+    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
+        background_music_execution.compile_background_music_execution_contract(
+            uploaded_audio=_uploaded_music(),
+            music_timeline_contract=_music_timeline(),
+            audio_asset_receipt={**_audio_asset_receipt(), "duration_seconds": 29.0},
+            source_content_timeline=_non_singing_source_timeline(),
+            performance_line_contract=None,
+        )
+
+
+@pytest.mark.parametrize("duration_seconds", [16.0, 30.0])
+def test_background_music_execution_rejects_a_full_or_oversized_runninghub_audio_upload(
+    duration_seconds: float,
+):
+    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
+        background_music_execution.compile_background_music_execution_contract(
+            uploaded_audio={**_uploaded_music(), "duration_seconds": duration_seconds},
+            music_timeline_contract=_music_timeline(),
+            audio_asset_receipt={
+                **_audio_asset_receipt(),
+                "duration_seconds": duration_seconds,
+                "clip_kind": "seedance_segment",
+                "seedance_segment": {"start_ms": 0, "end_ms": int(duration_seconds * 1_000)},
+            },
+            source_content_timeline=_non_singing_source_timeline(),
+            performance_line_contract=None,
+        )
+
+
+def test_background_music_execution_accepts_a_two_second_runninghub_segment_clip_for_a_longer_song():
+    execution = background_music_execution.compile_background_music_execution_contract(
+        uploaded_audio=_uploaded_music(),
+        music_timeline_contract=_music_timeline(),
+        audio_asset_receipt={
+            **_audio_asset_receipt(),
+            "duration_seconds": 2.0,
+            "clip_kind": "seedance_segment",
+            "seedance_segment": {"start_ms": 0, "end_ms": 2_000},
+        },
+        source_content_timeline=_non_singing_source_timeline(),
+        performance_line_contract=None,
+    )
+
+    assert execution["provider_payload"]["audioUrls"] == [
+        "https://runninghub.example/openapi/song-clip.mp3"
+    ]
+    assert execution["uploaded_audio"]["duration_seconds"] == 30.0
+    assert execution["audio_asset_receipt"]["duration_seconds"] == 2.0
+
+
+def test_background_music_execution_rejects_a_self_consistent_clip_for_the_wrong_frozen_output_segment():
+    timeline = _music_timeline()
+    timeline["output_duration_ms"] = 2_000
+    timeline["meaningful_silence_output_intervals"] = [{"output_start_ms": 1_000, "output_end_ms": 2_000}]
+
+    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
+        background_music_execution.compile_background_music_execution_contract(
+            uploaded_audio=_uploaded_music(),
+            music_timeline_contract=timeline,
+            audio_asset_receipt={
+                **_audio_asset_receipt(),
+                "seedance_segment": {"start_ms": 2_000, "end_ms": 4_000},
+            },
+            source_content_timeline=_non_singing_source_timeline(),
+            performance_line_contract=None,
+        )
+
+
 def test_background_music_execution_rejects_a_final_segment_sha_that_does_not_match_the_uploaded_segment():
     execution = _execution_contract_for(_music_timeline())
     receipt = _final_mix_receipt(execution_contract=execution)
@@ -1023,13 +1135,13 @@ def test_background_music_mode_has_explicit_no_lyric_lip_sync_when_singing_evide
 
     assert execution["mode"] == "background_music_replacement"
     assert execution["lyric_lip_sync_policy"] == "No lyric lip-sync"
-    assert "No lyric lip-sync" in execution["provider_payload"]["content"][0]["text"]
+    assert "No lyric lip-sync" in execution["provider_payload"]["prompt"]
 
 
 def test_verified_singing_seedance_prompt_locks_the_confirmed_singer_to_the_exact_audio1_lyrics():
     execution = _execution_contract_for(_music_timeline(), intent="verified_singing")
 
-    text = execution["provider_payload"]["content"][0]["text"]
+    text = execution["provider_payload"]["prompt"]
 
     assert "Song to perform: the exact uploaded track @Audio1." in text
     assert "CHARACTER_A is the only on-camera singer for this line." in text
@@ -1040,7 +1152,7 @@ def test_verified_singing_seedance_prompt_locks_the_confirmed_singer_to_the_exac
 def test_verified_singing_seedance_prompt_forbids_any_song_except_audio1_and_assigns_exact_lyrics_to_the_singer():
     execution = _execution_contract_for(_music_timeline(), intent="verified_singing")
 
-    text = execution["provider_payload"]["content"][0]["text"]
+    text = execution["provider_payload"]["prompt"]
 
     assert "@Audio1 is the only song that may be performed." in text
     assert 'CHARACTER_A must sing only this exact lyric from @Audio1: "Hold on".' in text
@@ -1264,7 +1376,7 @@ def test_background_music_provider_audit_requires_the_uploaded_audio_asset_and_e
         "execution_contract_sha256"
     ]
 
-    invalid_payload = {**valid_payload, "reference_audios": ["asset://asset-song"]}
+    invalid_payload = {**valid_payload, "reference_audios": ["https://runninghub.example/openapi/other.mp3"]}
     invalid_port = BackgroundMusicStagePort(
         stage="audit_seedance_request",
         delegate=_Port("canonical"),
@@ -1305,10 +1417,7 @@ def test_seedance_compile_stage_requires_the_canonical_background_music_executio
     execution = _execution_contract_for(_music_timeline())
     altered_payload = {
         **execution["provider_payload"],
-        "content": [
-            {"type": "text", "text": "Use @Audio1 but transform the uploaded song."},
-            execution["provider_payload"]["content"][1],
-        ],
+        "prompt": "Use @Audio1 but transform the uploaded song.",
     }
     port = BackgroundMusicStagePort(
         stage="compile_seedance20_prompt",
@@ -1364,10 +1473,7 @@ def test_background_music_provider_audit_rejects_a_payload_that_differs_from_the
     )
     altered_payload = {
         **execution["provider_payload"],
-        "content": [
-            {"type": "text", "text": "Use @Audio1 and invent a new lyric."},
-            execution["provider_payload"]["content"][1],
-        ],
+        "prompt": "Use @Audio1 and invent a new lyric.",
     }
     port = BackgroundMusicStagePort(
         stage="audit_seedance_request",
@@ -1396,7 +1502,10 @@ def test_provider_submission_rejects_a_post_audit_self_consistent_contract_swap(
     swapped = background_music_execution.compile_background_music_execution_contract(
         uploaded_audio=_uploaded_music(),
         music_timeline_contract=_music_timeline(),
-        audio_asset_receipt={**_audio_asset_receipt(), "asset_uri": "asset://asset-replaced-song"},
+        audio_asset_receipt={
+            **_audio_asset_receipt(),
+            "runninghub_audio_url": "https://runninghub.example/openapi/replaced-song.mp3",
+        },
         source_content_timeline=_non_singing_source_timeline(),
         performance_line_contract=None,
     )
@@ -1770,7 +1879,7 @@ def test_provider_submit_rejects_a_self_consistent_request_with_a_different_audi
         audio_asset_receipt={
             **_audio_asset_receipt(),
             "uploaded_audio_sha256": execution["uploaded_audio_sha256"],
-            "asset_uri": "asset://asset-forged",
+            "runninghub_audio_url": "https://runninghub.example/openapi/forged-song.mp3",
         },
         source_content_timeline=_non_singing_source_timeline(),
         performance_line_contract=None,
@@ -1867,7 +1976,7 @@ def test_background_music_splice_rejects_submission_not_bound_to_the_current_fro
         audio_asset_receipt={
             **_audio_asset_receipt(),
             "uploaded_audio_sha256": execution["uploaded_audio_sha256"],
-            "asset_uri": "asset://asset-another-audited-request",
+            "runninghub_audio_url": "https://runninghub.example/openapi/another-audited-song.mp3",
         },
         source_content_timeline=_non_singing_source_timeline(),
         performance_line_contract=None,
@@ -2038,10 +2147,7 @@ def test_background_music_provider_audit_revalidates_the_mode_contract_instead_o
     execution = _execution_contract_for(_music_timeline())
     unsafe_payload = {
         **execution["provider_payload"],
-        "content": [
-            {"type": "text", "text": "Use @Audio1 and make the performer lyric lip-sync every word."},
-            execution["provider_payload"]["content"][1],
-        ],
+        "prompt": "Use @Audio1 and make the performer lyric lip-sync every word.",
     }
     forged_execution = {**execution, "provider_payload": unsafe_payload}
     port = BackgroundMusicStagePort(
diff --git a/backend/tests/test_background_music_local_mvp.py b/backend/tests/test_background_music_local_mvp.py
index 3d99f1c..945020c 100644
--- a/backend/tests/test_background_music_local_mvp.py
+++ b/backend/tests/test_background_music_local_mvp.py
@@ -1,6 +1,7 @@
 from __future__ import annotations
 
 from pathlib import Path
+import json
 import math
 import shutil
 import subprocess
@@ -122,20 +123,60 @@ def _make_source_video(tmp_path: Path) -> Path:
     return source_video
 
 
+def _upload_audio_to_runninghub(source: Path, uploaded: dict[str, object]) -> dict[str, object]:
+    assert source.is_file()
+    assert source.name == "seedance_segment_clip.wav"
+    assert uploaded["duration_seconds"] == 3.0
+    assert uploaded["clip_kind"] == "seedance_segment"
+    assert uploaded["seedance_segment"] == {"start_ms": 0, "end_ms": 3_000}
+    return {
+        "AssetType": "Audio",
+        "asset_type": "Audio",
+        "provider": "runninghub",
+        "runninghub_audio_url": "https://runninghub.example/openapi/song-clip.mp3",
+        "duration_seconds": 3.0,
+        "clip_kind": "seedance_segment",
+        "seedance_segment": {"start_ms": 0, "end_ms": 3_000},
+        "status": "completed",
+        "uploaded_audio_sha256": uploaded["uploaded_audio_sha256"],
+    }
+
+
+def test_development_only_local_mvp_rejects_an_audio_clip_that_cannot_cover_the_frozen_generated_segment(
+    tmp_path: Path,
+):
+    source_video = _make_source_video(tmp_path)
+    uploaded_song = tmp_path / "two-second-song.wav"
+    _write_tone_wave(uploaded_song, seconds=2, active_ranges=[(0, 2)], frequency=220)
+
+    with pytest.raises(ValueError, match="LOCAL_MVP_RUNNINGHUB_AUDIO_UPLOAD_INVALID"):
+        DevelopmentOnlyBackgroundMusicMvpHarness(
+            run_root=tmp_path / "mvp-run",
+            runninghub_audio_upload=_upload_audio_to_runninghub,
+        ).run(
+            source_video=source_video,
+            background_music=uploaded_song,
+            visible_singer_regions=[],
+        )
+
+
 def test_development_only_local_mvp_archives_routes_and_preserves_source_music_windows(tmp_path: Path):
     source_video = _make_source_video(tmp_path)
     uploaded_song = tmp_path / "uploaded_song.wav"
     _write_tone_wave(
         uploaded_song,
-        seconds=2,
-        active_ranges=[(0, 2)],
+        seconds=3,
+        active_ranges=[(0, 3)],
         frequency=220,
         sample_rate=44_100,
         channels=2,
-        frequencies_by_second=[220, 880],
+        frequencies_by_second=[220, 880, 880],
     )
 
-    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
+    result = DevelopmentOnlyBackgroundMusicMvpHarness(
+        run_root=tmp_path / "mvp-run",
+        runninghub_audio_upload=_upload_audio_to_runninghub,
+    ).run(
         source_video=source_video,
         background_music=uploaded_song,
         visible_singer_regions=[],
@@ -153,15 +194,13 @@ def test_development_only_local_mvp_archives_routes_and_preserves_source_music_w
     assert Path(result["intake"]["background_music"]["archive_path"]).is_file()
     assert result["audio_asset_receipt"]["AssetType"] == "Audio"
     assert result["audio_asset_receipt"]["asset_type"] == "Audio"
-    assert result["provider_payload"]["content"] == [
-        {"type": "text", "text": result["provider_payload"]["content"][0]["text"]},
-        {
-            "type": "audio_url",
-            "role": "reference_audio",
-            "audio_url": {"url": result["audio_asset_receipt"]["asset_uri"]},
-        },
-    ]
-    assert "@Audio1" in result["provider_payload"]["content"][0]["text"]
+    assert result["audio_asset_receipt"]["duration_seconds"] == 3.0
+    assert result["audio_asset_receipt"]["seedance_segment"] == {"start_ms": 0, "end_ms": 3_000}
+    payload = result["provider_payload"]
+    assert payload["audioUrls"] == ["https://runninghub.example/openapi/song-clip.mp3"]
+    assert "content" not in payload
+    assert "asset://" not in json.dumps(payload)
+    assert "@Audio1" in payload["prompt"]
     assert "reference_audios" not in result["provider_payload"]
     assert result["provider_execution"] == {
         "environment": "development-only",
@@ -266,9 +305,12 @@ def test_development_only_local_mvp_archives_routes_and_preserves_source_music_w
 def test_development_only_local_mvp_binds_visible_singer_alignment_and_lip_sync_to_final_mix(tmp_path: Path):
     source_video = _make_source_video(tmp_path)
     uploaded_song = tmp_path / "uploaded_song.wav"
-    _write_tone_wave(uploaded_song, seconds=2, active_ranges=[(0, 2)], frequency=220)
+    _write_tone_wave(uploaded_song, seconds=3, active_ranges=[(0, 3)], frequency=220)
 
-    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
+    result = DevelopmentOnlyBackgroundMusicMvpHarness(
+        run_root=tmp_path / "mvp-run",
+        runninghub_audio_upload=_upload_audio_to_runninghub,
+    ).run(
         source_video=source_video,
         background_music=uploaded_song,
         visible_singer_regions=[
@@ -324,16 +366,19 @@ def test_development_only_local_mvp_preserves_32_bit_pcm_fragment_format(tmp_pat
     uploaded_song = tmp_path / "uploaded_song_32bit.wav"
     _write_tone_wave(
         uploaded_song,
-        seconds=2,
-        active_ranges=[(0, 2)],
+        seconds=3,
+        active_ranges=[(0, 3)],
         frequency=220,
         sample_rate=44_100,
         channels=2,
         sample_width=4,
-        frequencies_by_second=[220, 880],
+        frequencies_by_second=[220, 880, 880],
     )
 
-    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
+    result = DevelopmentOnlyBackgroundMusicMvpHarness(
+        run_root=tmp_path / "mvp-run",
+        runninghub_audio_upload=_upload_audio_to_runninghub,
+    ).run(
         source_video=source_video,
         background_music=uploaded_song,
         visible_singer_regions=[],
@@ -363,16 +408,19 @@ def test_development_only_local_mvp_validates_compressed_upload_fragments_as_dec
     uploaded_song = tmp_path / f"uploaded_song.{codec}"
     _write_tone_wave(
         uncompressed_song,
-        seconds=2,
-        active_ranges=[(0, 2)],
+        seconds=3,
+        active_ranges=[(0, 3)],
         frequency=220,
         sample_rate=44_100,
         channels=2,
-        frequencies_by_second=[220, 880],
+        frequencies_by_second=[220, 880, 880],
     )
     _encode_uploaded_audio(uncompressed_song, uploaded_song, codec=codec)
 
-    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
+    result = DevelopmentOnlyBackgroundMusicMvpHarness(
+        run_root=tmp_path / "mvp-run",
+        runninghub_audio_upload=_upload_audio_to_runninghub,
+    ).run(
         source_video=source_video,
         background_music=uploaded_song,
         visible_singer_regions=[],
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
diff --git a/usfr-server/server/high_fidelity_ports.py b/usfr-server/server/high_fidelity_ports.py
index c882055..150a455 100644
--- a/usfr-server/server/high_fidelity_ports.py
+++ b/usfr-server/server/high_fidelity_ports.py
@@ -24,24 +24,24 @@ from typing import Any, Callable
 from .errors import ReplicationError
 
 
-_SEEDANCE_SUBMIT_MODULE: Any | None = None
+_RUNNINGHUB_SUBMIT_MODULE: Any | None = None
 _SHA256 = re.compile(r"^[0-9a-f]{64}$")
 
 
-def _load_seedance_submit_module() -> Any:
-    """Load the bundled fixed-B payload authority from deployed bytes."""
+def _load_runninghub_submit_module() -> Any:
+    """Load the bundled RunningHub fixed-B payload authority from deployed bytes."""
 
-    global _SEEDANCE_SUBMIT_MODULE
-    if _SEEDANCE_SUBMIT_MODULE is not None:
-        return _SEEDANCE_SUBMIT_MODULE
+    global _RUNNINGHUB_SUBMIT_MODULE
+    if _RUNNINGHUB_SUBMIT_MODULE is not None:
+        return _RUNNINGHUB_SUBMIT_MODULE
     script = (
         Path(__file__).resolve().parents[1]
         / "bundled-skills"
         / "seedance-storyboard-replication"
         / "scripts"
-        / "seedance_submit.py"
+        / "runninghub_seedance_submit.py"
     )
-    module_name = "usfr_high_fidelity_seedance_submit"
+    module_name = "usfr_high_fidelity_runninghub_submit"
     spec = importlib.util.spec_from_file_location(module_name, script)
     if spec is None or spec.loader is None:
         raise RuntimeError("bundled Seedance payload validator cannot be loaded")
@@ -52,7 +52,7 @@ def _load_seedance_submit_module() -> Any:
         spec.loader.exec_module(module)
     finally:
         sys.path.pop(0)
-    _SEEDANCE_SUBMIT_MODULE = module
+    _RUNNINGHUB_SUBMIT_MODULE = module
     return module
 
 
@@ -652,21 +652,16 @@ class HighFidelityStageAdapter:
             raw_payload = json.loads(
                 json.dumps(template, ensure_ascii=False)
             )
-            content = raw_payload.get("content")
-            if (
-                not isinstance(content, list)
-                or not content
-                or not isinstance(content[0], Mapping)
-            ):
+            if not isinstance(raw_payload.get("prompt"), str):
                 raise ReplicationError(
                     "PROMPT_INTEGRITY_FAILED",
-                    "provider_payload_template is missing its text carrier",
+                    "provider_payload_template is missing its direct prompt",
                     category="contract",
                     user_action_required=True,
                     details={"segment_id": segment_id},
                     http_status=422,
                 )
-            content[0] = {**dict(content[0]), "text": compiled_prompt}
+            raw_payload["prompt"] = compiled_prompt
         if not isinstance(raw_payload, Mapping):
             raise ReplicationError(
                 "PROMPT_INTEGRITY_FAILED",
@@ -677,15 +672,13 @@ class HighFidelityStageAdapter:
                 http_status=422,
             )
         payload = dict(raw_payload)
-        validator = _load_seedance_submit_module()
+        validator = _load_runninghub_submit_module()
         try:
-            validator._validate_audited_fixed_b_payload(payload)  # noqa: SLF001 - bundled authority
-            prompt = validator._payload_prompt(payload)  # noqa: SLF001 - bundled authority
-            validator._validate_route_integrity(payload, prompt)  # noqa: SLF001 - bundled authority
+            prompt = validator.validate_runninghub_standard_payload(payload, fixed_b=True)
             compiled_prompt = result.get("compiled_prompt")
             if compiled_prompt is not None and prompt != compiled_prompt:
                 raise ValueError("provider payload prompt differs from Invocation B output")
-            request_sha256 = validator.request_sha256(payload)
+            request_sha256 = validator.runninghub_standard_request_sha256(payload, fixed_b=True)
             for source_name, source in (("request", request), ("result", result)):
                 declared = source.get("request_sha256")
                 if declared is not None and declared != request_sha256:
diff --git a/usfr-server/server/production_ports.py b/usfr-server/server/production_ports.py
index eb2385f..afd65be 100644
--- a/usfr-server/server/production_ports.py
+++ b/usfr-server/server/production_ports.py
@@ -32,6 +32,20 @@ _RUNNINGHUB_IMAGE_CREATE_PATH = "/openapi/v2/rhart-image-g-2-official/image-to-i
 _RUNNINGHUB_RUNNING_STATUSES = {"QUEUED", "RUNNING"}
 _RUNNINGHUB_FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED"}
 _RUNNINGHUB_STATUSES = _RUNNINGHUB_RUNNING_STATUSES | _RUNNINGHUB_FAILURE_STATUSES | {"SUCCESS"}
+_RUNNINGHUB_STANDARD_SEEDANCE_FIELDS = {
+    "prompt",
+    "resolution",
+    "duration",
+    "imageUrls",
+    "videoUrls",
+    "audioUrls",
+    "generateAudio",
+    "ratio",
+    "realPersonMode",
+    "conversionSlots",
+    "returnLastFrame",
+    "seed",
+}
 _REVISION_SCHEMA_VERSION = "usfr-creative-revision/v1"
 _REPLACEMENT_SLOT_IDS = (
     "new_product_image",
@@ -359,9 +373,9 @@ class ProductionEnvironment:
     openai_model_config_sha256: str
     runninghub_api_key_env: str
     runninghub_base_url: str
+    runninghub_seedance_api_key_env: str
     runninghub_seedance_create_url: str
     runninghub_seedance_query_url: str
-    runninghub_seedance_workflow_id: str
     runninghub_seedance_model_id: str
     runninghub_seedance_config_sha256: str
 
@@ -370,6 +384,7 @@ class ProductionEnvironment:
         source: Mapping[str, str] = os.environ if environ is None else environ
         _require_secret(source, "OPENAI_API_KEY")
         _require_secret(source, "RUNNINGHUB_API_KEY")
+        _require_secret(source, "RUNNINGHUB_SEEDANCE_API_KEY")
         return cls(
             openai_api_key_env="OPENAI_API_KEY",
             openai_base_url=_require_https_url(source, "OPENAI_BASE_URL"),
@@ -377,10 +392,10 @@ class ProductionEnvironment:
             openai_model_config_sha256=_require_sha256(source, "OPENAI_MODEL_CONFIG_SHA256"),
             runninghub_api_key_env="RUNNINGHUB_API_KEY",
             runninghub_base_url=_require_https_url(source, "RUNNINGHUB_BASE_URL"),
+            runninghub_seedance_api_key_env="RUNNINGHUB_SEEDANCE_API_KEY",
             runninghub_seedance_create_url=_require_https_url(source, "RUNNINGHUB_SEEDANCE_CREATE_URL"),
             runninghub_seedance_query_url=_require_https_url(source, "RUNNINGHUB_SEEDANCE_QUERY_URL"),
-            runninghub_seedance_workflow_id=_require_text(source, "RUNNINGHUB_SEEDANCE_WORKFLOW_ID"),
-            runninghub_seedance_model_id=_require_text(source, "RUNNINGHUB_SEEDANCE_MODEL_ID"),
+            runninghub_seedance_model_id="seedance-2.0-fast-token",
             runninghub_seedance_config_sha256=_require_sha256(source, "RUNNINGHUB_SEEDANCE_CONFIG_SHA256"),
         )
 
@@ -1519,7 +1534,6 @@ class RunningHubSeedanceProvider:
             "version": "1.0.0",
             "provider": "runninghub",
             "base_url": self.config.runninghub_base_url,
-            "workflow_id": self.config.runninghub_seedance_workflow_id,
             "model_id": self.config.runninghub_seedance_model_id,
             "configuration_sha256": self.config.runninghub_seedance_config_sha256,
         }
@@ -1537,19 +1551,24 @@ class RunningHubSeedanceProvider:
     def create_video(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
         if not isinstance(request, Mapping):
             raise ProductionPortsError("RunningHub video request must be a JSON object")
+        _validate_runninghub_standard_seedance_payload(request)
         return self._create(
             operation="video",
             url=self.config.runninghub_seedance_create_url,
-            payload={
-                "workflowId": self.config.runninghub_seedance_workflow_id,
-                "modelId": self.config.runninghub_seedance_model_id,
-                "request": dict(request),
-            },
+            payload=dict(request),
+            api_key_env=self.config.runninghub_seedance_api_key_env,
         )
 
-    def _create(self, *, operation: str, url: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
+    def _create(
+        self,
+        *,
+        operation: str,
+        url: str,
+        payload: Mapping[str, Any],
+        api_key_env: str | None = None,
+    ) -> Mapping[str, Any]:
         request_sha256 = _sha256(dict(payload))
-        api_key = _read_environment_secret(self.config.runninghub_api_key_env)
+        api_key = _read_environment_secret(api_key_env or self.config.runninghub_api_key_env)
         try:
             response = self._request_json(
                 url=url,
@@ -1598,7 +1617,7 @@ class RunningHubSeedanceProvider:
                 url=self.config.runninghub_seedance_query_url,
                 headers={
                     "Accept": "application/json",
-                    "Authorization": f"Bearer {_read_environment_secret(self.config.runninghub_api_key_env)}",
+                    "Authorization": f"Bearer {_read_environment_secret(self.config.runninghub_seedance_api_key_env)}",
                     "Content-Type": "application/json; charset=utf-8",
                 },
                 payload=payload,
@@ -1669,6 +1688,47 @@ def _require_result_https_url(value: str) -> None:
     _validated_https_url(value, "RunningHub result URL", allow_query=True)
 
 
+def _validate_runninghub_standard_seedance_payload(payload: Mapping[str, Any]) -> None:
+    """Reject legacy wrappers and source/opaque references before a paid call."""
+
+    if set(payload) != _RUNNINGHUB_STANDARD_SEEDANCE_FIELDS:
+        raise ProductionPortsError("RunningHub Seedance payload must contain only documented standard-model fields")
+    prompt = payload.get("prompt")
+    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 20_480:
+        raise ProductionPortsError("RunningHub Seedance prompt must contain 1-20480 characters")
+    if payload.get("resolution") not in {"480p", "720p", "1080p", "2k", "4k"}:
+        raise ProductionPortsError("RunningHub Seedance resolution is invalid")
+    if payload.get("duration") not in {str(value) for value in range(4, 16)}:
+        raise ProductionPortsError("RunningHub Seedance duration must be a string from 4 through 15")
+    if payload.get("ratio") not in {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
+        raise ProductionPortsError("RunningHub Seedance ratio is invalid")
+    image_urls = payload.get("imageUrls")
+    audio_urls = payload.get("audioUrls")
+    if not isinstance(image_urls, list) or len(image_urls) > 9:
+        raise ProductionPortsError("RunningHub Seedance imageUrls must contain at most 9 items")
+    if not isinstance(audio_urls, list) or len(audio_urls) > 1:
+        raise ProductionPortsError("RunningHub Seedance audioUrls must contain at most one USFR audio reference")
+    for value in [*image_urls, *audio_urls]:
+        parsed = urlparse.urlparse(str(value))
+        if parsed.scheme != "https" or not parsed.netloc:
+            raise ProductionPortsError("RunningHub Seedance media references must be public HTTPS URLs")
+    if payload.get("videoUrls") != []:
+        raise ProductionPortsError("RunningHub Seedance videoUrls must be empty for the USFR fixed-B route")
+    if payload.get("generateAudio") is not True:
+        raise ProductionPortsError("RunningHub Seedance generateAudio must be true")
+    real_person_mode = payload.get("realPersonMode")
+    conversion_slots = payload.get("conversionSlots")
+    if not isinstance(real_person_mode, bool):
+        raise ProductionPortsError("RunningHub Seedance realPersonMode must be boolean")
+    if conversion_slots != (["all"] if real_person_mode else []):
+        raise ProductionPortsError("RunningHub Seedance conversionSlots do not match realPersonMode")
+    if payload.get("returnLastFrame") is not False:
+        raise ProductionPortsError("RunningHub Seedance returnLastFrame must be false")
+    seed = payload.get("seed")
+    if isinstance(seed, bool) or not isinstance(seed, int) or not -1 <= seed <= 2_147_483_647:
+        raise ProductionPortsError("RunningHub Seedance seed is invalid")
+
+
 def _receipt_result_url(value: str) -> str:
     """Retain the stable media location without copying a signed query token."""
 
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
diff --git a/usfr-server/tests/test_high_fidelity_ports.py b/usfr-server/tests/test_high_fidelity_ports.py
index 44c95f3..2f195a6 100644
--- a/usfr-server/tests/test_high_fidelity_ports.py
+++ b/usfr-server/tests/test_high_fidelity_ports.py
@@ -47,13 +47,18 @@ def _factor_coverage() -> list[dict]:
 
 def _provider_payload(prompt: str, *, duration: int = 8) -> dict:
     return {
-        "model": "seedance-2.0",
-        "content": [{"type": "text", "text": prompt}],
-        "generate_audio": True,
-        "ratio": "9:16",
-        "duration": duration,
-        "watermark": False,
+        "prompt": prompt,
         "resolution": "720p",
+        "duration": str(duration),
+        "imageUrls": ["https://media.example/board.png"],
+        "videoUrls": [],
+        "audioUrls": [],
+        "generateAudio": True,
+        "ratio": "9:16",
+        "realPersonMode": False,
+        "conversionSlots": [],
+        "returnLastFrame": False,
+        "seed": -1,
     }
 
 
@@ -69,6 +74,67 @@ def _request_sha(payload: dict) -> str:
 
 
 class HighFidelityPortsTest(unittest.TestCase):
+    def test_provider_binding_accepts_exact_runninghub_standard_payload(self):
+        payload = _provider_payload("Prompt for S01")
+
+        binding = HighFidelityStageAdapter._provider_binding(
+            segment_id="S01",
+            segment_plan_sha256="a" * 64,
+            request={"provider_payload": payload},
+            result={"compiled_prompt": "Prompt for S01"},
+        )
+
+        self.assertEqual(binding["provider_payload"], payload)
+        self.assertEqual(binding["request_sha256"], _request_sha(payload))
+
+    def test_provider_binding_substitutes_compiled_prompt_into_direct_template_prompt(self):
+        template = _provider_payload("stale template prompt")
+
+        binding = HighFidelityStageAdapter._provider_binding(
+            segment_id="S01",
+            segment_plan_sha256="a" * 64,
+            request={"provider_payload_template": template},
+            result={"compiled_prompt": "Exact approved prompt"},
+        )
+
+        self.assertEqual(binding["provider_payload"]["prompt"], "Exact approved prompt")
+        self.assertNotIn("content", binding["provider_payload"])
+
+    def test_provider_binding_rejects_legacy_content_asset_payload(self):
+        legacy_payload = {
+            "model": "seedance-2.0",
+            "content": [
+                {"type": "text", "text": "Prompt for S01"},
+                {
+                    "type": "image_url",
+                    "role": "reference_image",
+                    "image_url": {"url": "asset://asset-source-frame"},
+                },
+            ],
+            "generate_audio": True,
+            "ratio": "9:16",
+            "duration": 8,
+            "watermark": False,
+            "resolution": "720p",
+        }
+
+        with self.assertRaisesRegex(ReplicationError, "canonical"):
+            HighFidelityStageAdapter._provider_binding(
+                segment_id="S01",
+                segment_plan_sha256="a" * 64,
+                request={"provider_payload": legacy_payload},
+                result={"compiled_prompt": "Prompt for S01"},
+            )
+
+    def test_provider_binding_rejects_route_excluded_prompt_through_runninghub_validator(self):
+        with self.assertRaisesRegex(ReplicationError, "canonical"):
+            HighFidelityStageAdapter._provider_binding(
+                segment_id="S01",
+                segment_plan_sha256="a" * 64,
+                request={"provider_payload": _provider_payload("Preserve the source video framing.")},
+                result={"compiled_prompt": "Preserve the source video framing."},
+            )
+
     def test_invocation_b_blocks_source_audio_when_confirmed_performance_artifact_is_missing(self):
         with tempfile.TemporaryDirectory() as tmp:
             root = Path(tmp)
diff --git a/usfr-server/tests/test_production_ports.py b/usfr-server/tests/test_production_ports.py
index 22a3450..0a72801 100644
--- a/usfr-server/tests/test_production_ports.py
+++ b/usfr-server/tests/test_production_ports.py
@@ -34,14 +34,35 @@ def _set_complete_environment(monkeypatch: pytest.MonkeyPatch) -> None:
     monkeypatch.setenv("OPENAI_MODEL", "gpt-test-2026-07-22")
     monkeypatch.setenv("OPENAI_MODEL_CONFIG_SHA256", "a" * 64)
     monkeypatch.setenv("RUNNINGHUB_API_KEY", "runninghub-secret")
+    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_API_KEY", "runninghub-standard-secret")
     monkeypatch.setenv("RUNNINGHUB_BASE_URL", "https://runninghub.example")
-    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_CREATE_URL", "https://runninghub.example/seedance/create")
-    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_QUERY_URL", "https://runninghub.example/seedance/query")
+    monkeypatch.setenv(
+        "RUNNINGHUB_SEEDANCE_CREATE_URL",
+        "https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
+    )
+    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_QUERY_URL", "https://www.runninghub.cn/openapi/v2/query")
     monkeypatch.setenv("RUNNINGHUB_SEEDANCE_WORKFLOW_ID", "workflow-123")
     monkeypatch.setenv("RUNNINGHUB_SEEDANCE_MODEL_ID", "seedance-2.0")
     monkeypatch.setenv("RUNNINGHUB_SEEDANCE_CONFIG_SHA256", "b" * 64)
 
 
+def _standard_video_payload(prompt: str) -> dict[str, object]:
+    return {
+        "prompt": prompt,
+        "resolution": "720p",
+        "duration": "5",
+        "imageUrls": ["https://media.example/board.png"],
+        "videoUrls": [],
+        "audioUrls": [],
+        "generateAudio": True,
+        "ratio": "9:16",
+        "realPersonMode": False,
+        "conversionSlots": [],
+        "returnLastFrame": False,
+        "seed": -1,
+    }
+
+
 def _strict_schema() -> dict[str, Any]:
     return {
         "type": "object",
@@ -769,9 +790,9 @@ def test_environment_is_frozen_and_contains_only_redacted_credential_references(
         "openai_model_config_sha256",
         "runninghub_api_key_env",
         "runninghub_base_url",
+        "runninghub_seedance_api_key_env",
         "runninghub_seedance_create_url",
         "runninghub_seedance_query_url",
-        "runninghub_seedance_workflow_id",
         "runninghub_seedance_model_id",
         "runninghub_seedance_config_sha256",
     }
@@ -1005,7 +1026,7 @@ def test_pinned_https_connection_uses_the_verified_address_and_original_sni(monk
     assert connection.sock is tls_socket
 
 
-def test_runninghub_video_create_uses_one_paid_task_envelope_and_redacted_identity(
+def test_runninghub_video_create_uses_standard_model_payload_and_dedicated_key(
     monkeypatch: pytest.MonkeyPatch,
 ) -> None:
     _set_complete_environment(monkeypatch)
@@ -1016,28 +1037,25 @@ def test_runninghub_video_create_uses_one_paid_task_envelope_and_redacted_identi
         return {"taskId": "task-123"}
 
     provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
-    result = provider.create_video({"prompt": "preserve the approved storyboard"})
+    payload = _standard_video_payload("preserve the approved storyboard")
+    result = provider.create_video(payload)
 
     assert result["task_id"] == "task-123"
     assert calls == [
         {
-            "url": "https://runninghub.example/seedance/create",
+            "url": "https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
             "headers": {
                 "Accept": "application/json",
-                "Authorization": "Bearer runninghub-secret",
+                "Authorization": "Bearer runninghub-standard-secret",
                 "Content-Type": "application/json; charset=utf-8",
             },
-            "payload": {
-                "workflowId": "workflow-123",
-                "modelId": "seedance-2.0",
-                "request": {"prompt": "preserve the approved storyboard"},
-            },
+            "payload": payload,
             "timeout_seconds": 120.0,
         }
     ]
     identity = provider.capability_identity()
     assert identity["provider"] == "runninghub"
-    assert identity["model_id"] == "seedance-2.0"
+    assert identity["model_id"] == "seedance-2.0-fast-token"
     assert identity["sha256"] == hashlib.sha256(
         json.dumps(
             {key: value for key, value in identity.items() if key != "sha256"},
@@ -1046,7 +1064,37 @@ def test_runninghub_video_create_uses_one_paid_task_envelope_and_redacted_identi
             separators=(",", ":"),
         ).encode("utf-8")
     ).hexdigest()
-    assert "runninghub-secret" not in json.dumps({"identity": identity, "receipt": result}, sort_keys=True)
+    serialized = json.dumps({"identity": identity, "receipt": result}, sort_keys=True)
+    assert "runninghub-secret" not in serialized
+    assert "runninghub-standard-secret" not in serialized
+
+
+def test_runninghub_video_create_rejects_source_or_opaque_video_references(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    _set_complete_environment(monkeypatch)
+    provider = RunningHubSeedanceProvider(
+        ProductionEnvironment.from_environ(),
+        request_json=lambda **_kwargs: {"taskId": "unexpected"},
+    )
+
+    with pytest.raises(ProductionPortsError, match="videoUrls"):
+        provider.create_video(
+            {
+                "prompt": "source video must stay out of this route",
+                "resolution": "720p",
+                "duration": "5",
+                "imageUrls": [],
+                "videoUrls": ["https://media.example/source.mp4"],
+                "audioUrls": [],
+                "generateAudio": True,
+                "ratio": "9:16",
+                "realPersonMode": False,
+                "conversionSlots": [],
+                "returnLastFrame": False,
+                "seed": -1,
+            }
+        )
 
 
 def test_runninghub_video_create_does_not_retry_an_ambiguous_paid_request(monkeypatch: pytest.MonkeyPatch) -> None:
@@ -1060,7 +1108,7 @@ def test_runninghub_video_create_does_not_retry_an_ambiguous_paid_request(monkey
     provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
 
     with pytest.raises(RunningHubCreateAmbiguousError, match="ambiguous") as error:
-        provider.create_video({"prompt": "no automatic retry"})
+        provider.create_video(_standard_video_payload("no automatic retry"))
     assert error.value.retryable is False
     assert error.value.reconciliation_required is True
     assert len(calls) == 1
@@ -1077,7 +1125,7 @@ def test_runninghub_paid_create_turns_http_failure_into_non_retryable_ambiguity(
     provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
 
     with pytest.raises(RunningHubCreateAmbiguousError, match="ambiguous") as error:
-        provider.create_video({"prompt": "provider may have accepted this"})
+        provider.create_video(_standard_video_payload("provider may have accepted this"))
     assert error.value.retryable is False
     assert error.value.reconciliation_required is True
 
@@ -1093,7 +1141,7 @@ def test_runninghub_paid_create_turns_malformed_response_into_non_retryable_ambi
     provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
 
     with pytest.raises(RunningHubCreateAmbiguousError, match="ambiguous"):
-        provider.create_video({"prompt": "malformed response"})
+        provider.create_video(_standard_video_payload("malformed response"))
 
 
 def test_runninghub_paid_create_turns_missing_task_id_into_non_retryable_ambiguity(
@@ -1107,7 +1155,7 @@ def test_runninghub_paid_create_turns_missing_task_id_into_non_retryable_ambigui
     provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
 
     with pytest.raises(RunningHubCreateAmbiguousError, match="taskId") as error:
-        provider.create_video({"prompt": "response omitted task id"})
+        provider.create_video(_standard_video_payload("response omitted task id"))
     assert error.value.retryable is False
     assert error.value.reconciliation_required is True
 
@@ -1117,7 +1165,7 @@ def test_runninghub_video_create_reports_a_missing_runtime_key_as_configuration_
 ) -> None:
     _set_complete_environment(monkeypatch)
     config = ProductionEnvironment.from_environ()
-    monkeypatch.delenv("RUNNINGHUB_API_KEY")
+    monkeypatch.delenv("RUNNINGHUB_SEEDANCE_API_KEY")
     calls: list[dict[str, Any]] = []
 
     def request_json(**kwargs: Any) -> dict[str, Any]:
@@ -1126,8 +1174,8 @@ def test_runninghub_video_create_reports_a_missing_runtime_key_as_configuration_
 
     provider = RunningHubSeedanceProvider(config, request_json=request_json)
 
-    with pytest.raises(ProductionPortsError, match="RUNNINGHUB_API_KEY is required") as error:
-        provider.create_video({"prompt": "missing key"})
+    with pytest.raises(ProductionPortsError, match="RUNNINGHUB_SEEDANCE_API_KEY is required") as error:
+        provider.create_video(_standard_video_payload("missing key"))
     assert "ambiguous" not in str(error.value)
     assert calls == []
 
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

--- UNTRACKED RUNNINGHUB STANDARD SUBMITTER ---

from __future__ import annotations

"""RunningHub Standard Model adapter for USFR Seedance video tasks.

The adapter deliberately accepts only storyboard/target-image and optional
segment-bounded audio references.  Source-video, opaque UI and tail-video
references are not supported by this fixed-B USFR route and therefore cannot
reach the Seedance endpoint through this command.
"""

import argparse
import hashlib
import ipaddress
import json
import math
import mimetypes
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from config import DEFAULT_ENV_FILE, build_redacted_provider_preflight, load_settings


RUNNINGHUB_STANDARD_CREATE_URL = (
    "https://www.runninghub.cn/openapi/v2/bytedance/"
    "seedance-2.0-fast-token/multimodal-video"
)
RUNNINGHUB_STANDARD_QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"
RUNNINGHUB_STANDARD_UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
RUNNINGHUB_RUNNING_STATUSES = {"QUEUED", "RUNNING"}
RUNNINGHUB_FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED"}
RUNNINGHUB_STANDARD_PAYLOAD_FIELDS = frozenset(
    {
        "prompt",
        "resolution",
        "duration",
        "imageUrls",
        "videoUrls",
        "audioUrls",
        "generateAudio",
        "ratio",
        "realPersonMode",
        "conversionSlots",
        "returnLastFrame",
        "seed",
    }
)
_ROUTE_LEAKAGE_MARKERS = (
    "source_video",
    "opaque_ui",
    "ui_demo",
    "opaque_ui_demo",
    "opaque_ui_video",
    "ui_demo_video",
    "generated_ui_demo",
    "generated_ui",
    "ui_render_contract",
    "ui_truth_card",
    "ui_qc_report",
    "ui_operation_video",
    "ui_media",
    "ui_rendered_media",
    "ui_media_sha256",
    "ui_ocr_evidence",
    "ui_layout_evidence",
    "animation_interval_evidence",
    "tail_video",
    "tail_card",
    "tail_card_video",
    "app_tail_card_video",
    "opaque_app_tail_card",
    "opaque_tail",
    "append_opaque_tail",
    "tail_truth_card",
    "tail_render_contract",
    "tail_qc_report",
    "tail_media",
    "tail_media_sha256",
    "rendered_media",
    "media_sha256",
    "qc_report",
    "transition_render_receipt",
    "transition_render_receipts",
    "source_ui_frames",
    "source_interval",
    "source_ui_keep",
    "transition_shell",
    "reference_videos",
    "reference_audios",
    "excluded_app_end_card",
    "omit_source_end_card",
    "excluded_region",
)
_ROUTE_LEAKAGE_EXACT_KEYS = {
    "ui_truth",
    "tail_truth",
    "ui_render",
    "tail_render",
    "ui_qc",
    "tail_qc",
}
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]", re.DOTALL)


class PayloadError(ValueError):
    pass


class RunningHubSeedanceError(RuntimeError):
    pass


class TaskFailedError(RunningHubSeedanceError):
    pass


class PollTimeoutError(RunningHubSeedanceError):
    pass


def _require_public_https_urls(urls: list[str]) -> None:
    for value in urls:
        parsed = urlparse(value)
        try:
            hostname = parsed.hostname
        except ValueError as error:
            raise PayloadError("media URLs must be public HTTPS URLs") from error
        if parsed.scheme != "https" or not hostname:
            raise PayloadError("media URLs must be public HTTPS URLs")
        normalized_host = hostname.rstrip(".").casefold()
        if normalized_host == "localhost":
            raise PayloadError("media URLs must be public HTTPS URLs")
        try:
            address = ipaddress.ip_address(unquote(hostname).split("%", 1)[0])
        except ValueError:
            continue
        if not address.is_global:
            raise PayloadError("media URLs must be public HTTPS URLs")


def _route_tokens(value: str) -> list[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return re.findall(r"[a-z0-9]+", separated.casefold())


def _canonical_route_key(value: str) -> str:
    return "_".join(_route_tokens(value))


def _route_leakage_matches(value: str) -> list[str]:
    tokens = _route_tokens(value)
    if not tokens:
        return []
    token_set = set(tokens)
    matches: list[str] = []
    for marker in _ROUTE_LEAKAGE_MARKERS:
        marker_tokens = _route_tokens(marker)
        width = len(marker_tokens)
        compact = "".join(marker_tokens)
        if compact in token_set or any(
            tokens[index : index + width] == marker_tokens
            for index in range(len(tokens) - width + 1)
        ):
            matches.append(marker)
    return matches


def _route_leakage_in_value(value: object) -> list[str]:
    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                canonical_key = _canonical_route_key(key)
                if canonical_key in _ROUTE_LEAKAGE_EXACT_KEYS:
                    matches.append(key)
                matches.extend(_route_leakage_matches(key))
            matches.extend(_route_leakage_in_value(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            matches.extend(_route_leakage_in_value(child))
    elif isinstance(value, str):
        matches.extend(_route_leakage_matches(value))
    return list(dict.fromkeys(matches))


def _contains_unresolved_placeholder(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_unresolved_placeholder(key)
            or _contains_unresolved_placeholder(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unresolved_placeholder(child) for child in value)
    return isinstance(value, str) and _PLACEHOLDER_RE.search(value) is not None


def _validate_route_integrity(payload: Mapping[str, object]) -> None:
    leaked = _route_leakage_in_value(payload)
    if leaked:
        raise PayloadError(
            "route leakage detected in Seedance prompt or provider payload: "
            + ", ".join(leaked)
        )
    if _contains_unresolved_placeholder(payload):
        raise PayloadError("compiled prompt contains unresolved placeholders")


def _provider_duration(duration: int | float) -> int:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise PayloadError("duration must be a number of seconds")
    if not math.isfinite(duration):
        raise PayloadError("duration must be a finite number of seconds")
    provider_duration = math.ceil(duration)
    if not 4 <= provider_duration <= 15:
        raise PayloadError("duration must be between 4 and 15 seconds")
    return provider_duration


def validate_runninghub_standard_payload(
    payload: Mapping[str, object], *, fixed_b: bool = False
) -> str:
    """Validate an exact RunningHub standard-model payload and return its prompt."""

    if not isinstance(payload, Mapping) or set(payload) != RUNNINGHUB_STANDARD_PAYLOAD_FIELDS:
        raise PayloadError("standard Seedance payload contains unknown or missing provider fields")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or prompt != prompt.strip() or not 1 <= len(prompt) <= 20_480:
        raise PayloadError("prompt must contain 1-20480 trimmed characters")
    _validate_route_integrity(payload)
    resolution = payload.get("resolution")
    if resolution not in {"480p", "720p", "1080p", "2k", "4k"}:
        raise PayloadError("resolution is not supported by RunningHub Seedance")
    ratio = payload.get("ratio")
    if ratio not in {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
        raise PayloadError("ratio is not supported by RunningHub Seedance")
    duration = payload.get("duration")
    if not isinstance(duration, str) or duration not in {str(value) for value in range(4, 16)}:
        raise PayloadError("duration must be a string between 4 and 15 seconds")
    image_urls = payload.get("imageUrls")
    audio_urls = payload.get("audioUrls")
    if not isinstance(image_urls, list) or not all(isinstance(url, str) for url in image_urls):
        raise PayloadError("imageUrls must be a list of public HTTPS URLs")
    if not isinstance(audio_urls, list) or not all(isinstance(url, str) for url in audio_urls):
        raise PayloadError("audioUrls must be a list of public HTTPS URLs")
    if len(image_urls) > 9:
        raise PayloadError("RunningHub Seedance accepts at most 9 images")
    if len(audio_urls) > 1:
        raise PayloadError("USFR accepts at most one segment audio reference")
    if payload.get("videoUrls") != []:
        raise PayloadError("standard Seedance payload cannot include video references")
    _require_public_https_urls([*image_urls, *audio_urls])
    if audio_urls and "@Audio1" not in prompt:
        raise PayloadError("uploaded-song audio requires @Audio1 in the prompt")
    real_person_mode = payload.get("realPersonMode")
    if not isinstance(real_person_mode, bool):
        raise PayloadError("realPersonMode must be a boolean")
    if payload.get("generateAudio") is not True:
        raise PayloadError("generateAudio must be enabled")
    if payload.get("conversionSlots") != (["all"] if real_person_mode else []):
        raise PayloadError("conversionSlots must match realPersonMode")
    if payload.get("returnLastFrame") is not False or payload.get("seed") != -1:
        raise PayloadError("returnLastFrame and seed must use the fixed USFR values")
    if fixed_b and (resolution != "720p" or ratio != "9:16"):
        raise PayloadError("fixed-B payload requires 720p and 9:16")
    return prompt


def runninghub_standard_request_sha256(
    payload: Mapping[str, object], *, fixed_b: bool = False
) -> str:
    """Return the immutable digest of a validated RunningHub standard payload."""

    validate_runninghub_standard_payload(payload, fixed_b=fixed_b)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_runninghub_standard_payload(
    prompt: str,
    duration: int | float,
    ratio: str,
    image_urls: list[str],
    audio_urls: list[str],
    *,
    real_person_mode: bool,
    resolution: str = "720p",
) -> dict[str, object]:
    """Build the exact documented RunningHub standard-model request body."""

    normalized_prompt = str(prompt or "").strip()
    if not 1 <= len(normalized_prompt) <= 20_480:
        raise PayloadError("prompt must contain 1-20480 characters")
    if resolution not in {"480p", "720p", "1080p", "2k", "4k"}:
        raise PayloadError("resolution is not supported by RunningHub Seedance")
    if ratio not in {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
        raise PayloadError("ratio is not supported by RunningHub Seedance")
    if len(image_urls) > 9:
        raise PayloadError("RunningHub Seedance accepts at most 9 images")
    if len(audio_urls) > 1:
        raise PayloadError("USFR accepts at most one segment audio reference")
    if audio_urls and "@Audio1" not in normalized_prompt:
        raise PayloadError("uploaded-song audio requires @Audio1 in the prompt")
    _require_public_https_urls(list(image_urls) + list(audio_urls))
    payload: dict[str, object] = {
        "prompt": normalized_prompt,
        "resolution": resolution,
        "duration": str(_provider_duration(duration)),
        "imageUrls": list(image_urls),
        # Deliberately frozen for source-fidelity fixed-B generation: source
        # video and non-generated UI/tail media must never become model input.
        "videoUrls": [],
        "audioUrls": list(audio_urls),
        "generateAudio": True,
        "ratio": ratio,
        "realPersonMode": bool(real_person_mode),
        "conversionSlots": ["all"] if real_person_mode else [],
        "returnLastFrame": False,
        "seed": -1,
    }
    validate_runninghub_standard_payload(payload)
    return payload


def _read_json(response: Any) -> dict[str, Any]:
    raw = response.read()
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunningHubSeedanceError("RunningHub returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RunningHubSeedanceError("RunningHub response must be a JSON object")
    return value


def _urllib_request_json(
    *, method: str, url: str, headers: dict[str, str], json_body: dict[str, object], timeout: float
) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), _read_json(response)
    except HTTPError as error:
        return int(error.code), _read_json(error)


def _download_file(url: str, output_path: Path) -> None:
    request = Request(url, method="GET")
    with urlopen(request, timeout=180) as response:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.read())


class RunningHubStandardSeedanceClient:
    """No-retry client for the RunningHub Seedance standard model."""

    def __init__(
        self,
        api_key: str,
        *,
        create_url: str = RUNNINGHUB_STANDARD_CREATE_URL,
        query_url: str = RUNNINGHUB_STANDARD_QUERY_URL,
        upload_url: str = RUNNINGHUB_STANDARD_UPLOAD_URL,
        request_json: Callable[..., tuple[int, dict[str, Any]]] | None = None,
        download: Callable[[str, Path], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not str(api_key or "").strip():
            raise RunningHubSeedanceError("RUNNINGHUB_SEEDANCE_API_KEY is required")
        self.api_key = str(api_key)
        self.create_url = create_url
        self.query_url = query_url
        self.upload_url = upload_url
        self.request_json = request_json or _urllib_request_json
        self.download = download or _download_file
        self.sleep = sleep
        self.clock = clock
        self.last_response: dict[str, Any] = {}
        self.last_status_response: dict[str, Any] = {}

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, url: str, body: dict[str, object]) -> dict[str, Any]:
        try:
            status, response = self.request_json(
                method="POST", url=url, headers=self._headers, json_body=body, timeout=90
            )
        except Exception as error:
            raise RunningHubSeedanceError(
                "RunningHub request failed; paid create outcome is ambiguous and was not retried"
            ) from error
        if status in {401, 403}:
            raise RunningHubSeedanceError(
                f"RunningHub request rejected with HTTP {status}; check RUNNINGHUB_SEEDANCE_API_KEY"
            )
        if not 200 <= status < 300:
            message = str(response.get("errorMessage") or response.get("message") or "request failed")
            raise RunningHubSeedanceError(f"RunningHub request failed with HTTP {status}: {message}")
        return response

    def create_video(self, payload: dict[str, object]) -> str:
        validate_runninghub_standard_payload(payload)
        response = self._post(self.create_url, payload)
        self.last_response = response
        task_id = str(response.get("taskId") or "").strip()
        if not task_id:
            raise RunningHubSeedanceError(
                "RunningHub paid create response omitted taskId; do not retry automatically"
            )
        return task_id

    def get_status(self, task_id: str) -> dict[str, Any]:
        task = str(task_id or "").strip()
        if not task:
            raise RunningHubSeedanceError("taskId is required")
        response = self._post(self.query_url, {"taskId": task})
        self.last_status_response = response
        return response

    def upload_file(self, path: Path) -> str:
        source = Path(path)
        if not source.is_file():
            raise PayloadError(f"upload file does not exist: {source}")
        boundary = f"----usfr-{uuid4().hex}"
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body = b"".join(
            (
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="file"; filename="{source.name}"\r\n'
                    f"Content-Type: {mime_type}\r\n\r\n"
                ).encode(),
                source.read_bytes(),
                f"\r\n--{boundary}--\r\n".encode(),
            )
        )
        request = Request(
            self.upload_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                result = _read_json(response)
        except HTTPError as error:
            result = _read_json(error)
            message = str(result.get("message") or result.get("errorMessage") or "upload failed")
            raise RunningHubSeedanceError(f"RunningHub upload failed with HTTP {error.code}: {message}") from error
        data = result.get("data")
        url = str(data.get("download_url") if isinstance(data, dict) else "").strip()
        _require_public_https_urls([url])
        return url

    def download_video(self, video_url: str, output_path: Path) -> None:
        _require_public_https_urls([video_url])
        self.download(video_url, output_path)


def poll_runninghub_task(
    client: RunningHubStandardSeedanceClient,
    task_id: str,
    *,
    timeout: float | None = None,
    poll_interval: float = 20,
) -> str:
    deadline = None if timeout is None else client.clock() + timeout
    while True:
        response = client.get_status(task_id)
        status = str(response.get("status") or "").upper()
        if status == "SUCCESS":
            results = response.get("results")
            if not isinstance(results, list):
                raise RunningHubSeedanceError("RunningHub success response omitted results")
            for item in results:
                if isinstance(item, Mapping) and str(item.get("outputType") or "").lower() == "mp4":
                    url = str(item.get("url") or "").strip()
                    _require_public_https_urls([url])
                    return url
            raise RunningHubSeedanceError("RunningHub success response omitted an MP4 result")
        if status in RUNNINGHUB_FAILURE_STATUSES:
            message = str(response.get("errorMessage") or response.get("message") or status)
            raise TaskFailedError(message)
        if status not in RUNNINGHUB_RUNNING_STATUSES:
            raise RunningHubSeedanceError(f"unknown RunningHub task status: {status or '<empty>'}")
        if deadline is not None and client.clock() >= deadline:
            raise PollTimeoutError(f"RunningHub task {task_id} timed out")
        client.sleep(poll_interval)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _request_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit an audited USFR Seedance task to RunningHub Standard Model API.")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--image-file", action="append", type=Path, default=[])
    parser.add_argument("--audio-url", action="append", default=[])
    parser.add_argument("--audio-file", action="append", type=Path, default=[])
    parser.add_argument("--duration", type=float)
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--real-person-mode", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approved-request-sha256")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--resume-task-id")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=20)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(args.env_file)
    if args.preflight:
        if any((args.prompt_file, args.image_url, args.image_file, args.audio_url, args.audio_file, args.duration, args.dry_run, args.poll, args.resume_task_id, args.approved_request_sha256)):
            raise PayloadError("--preflight cannot be combined with a Seedance task option")
        _write_json(args.output_dir / "provider_preflight.json", build_redacted_provider_preflight(args.env_file))
        return 0
    settings.require_seedance()
    client = RunningHubStandardSeedanceClient(
        settings.runninghub_seedance_api_key,
        create_url=settings.runninghub_seedance_create_url,
        query_url=settings.runninghub_seedance_query_url,
        upload_url=settings.runninghub_seedance_upload_url,
    )
    if args.resume_task_id:
        if args.dry_run or args.approved_request_sha256:
            raise PayloadError("resume-task-id cannot be combined with a new request option")
        task_id = args.resume_task_id
    else:
        if args.prompt_file is None or args.duration is None:
            raise PayloadError("--prompt-file and --duration are required for a new Seedance request")
        prompt = args.prompt_file.read_text(encoding="utf-8-sig")
        image_urls = [*args.image_url, *(client.upload_file(path) for path in args.image_file)]
        audio_urls = [*args.audio_url, *(client.upload_file(path) for path in args.audio_file)]
        payload = build_runninghub_standard_payload(
            prompt, args.duration, args.ratio, image_urls, audio_urls, real_person_mode=args.real_person_mode
        )
        request_sha256 = _request_sha256(payload)
        _write_json(args.output_dir / "request.redacted.json", payload)
        _write_json(args.output_dir / "approval_preview.json", {"request_sha256": request_sha256})
        if args.dry_run:
            _write_json(args.output_dir / "status.json", {"status": "dry_run"})
            return 0
        if args.approved_request_sha256 != request_sha256:
            raise PayloadError("provide the exact --approved-request-sha256 from the audited dry run")
        task_id = client.create_video(payload)
        _write_json(args.output_dir / "create_response.json", client.last_response)
    (args.output_dir / "task_id.txt").write_text(str(task_id), encoding="utf-8")
    if args.poll:
        video_url = poll_runninghub_task(client, str(task_id), timeout=args.timeout, poll_interval=args.poll_interval)
        _write_json(args.output_dir / "status.json", client.last_status_response)
        client.download_video(video_url, args.output_dir / "result.mp4")
    else:
        _write_json(args.output_dir / "status.json", {"task_id": str(task_id), "status": "created"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


--- UNTRACKED STANDARD SUBMITTER TEST ---

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from config import build_redacted_provider_preflight, load_settings  # noqa: E402
from runninghub_seedance_submit import (  # noqa: E402
    PayloadError,
    RunningHubStandardSeedanceClient,
    build_runninghub_standard_payload,
    validate_runninghub_standard_payload,
)


def test_standard_payload_uses_documented_fields_and_keeps_source_video_out() -> None:
    payload = build_runninghub_standard_payload(
        "Use @Audio1 exactly.",
        13,
        "9:16",
        ["https://media.example/board.png", "https://media.example/model.jpg"],
        ["https://media.example/song-clip.mp3"],
        real_person_mode=True,
    )

    assert payload == {
        "prompt": "Use @Audio1 exactly.",
        "resolution": "720p",
        "duration": "13",
        "imageUrls": [
            "https://media.example/board.png",
            "https://media.example/model.jpg",
        ],
        "videoUrls": [],
        "audioUrls": ["https://media.example/song-clip.mp3"],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }


def test_standard_payload_validation_rejects_route_excluded_markers_in_all_values() -> None:
    payload = build_runninghub_standard_payload(
        "Keep the verified performance.",
        8,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    payload["prompt"] = "Recreate the source video framing."
    payload["imageUrls"] = ["https://media.example/opaque-ui-frame.png"]

    try:
        validate_runninghub_standard_payload(payload, fixed_b=True)
    except PayloadError as error:
        assert "route leakage" in str(error)
    else:
        raise AssertionError("route-excluded prompt and media values must be rejected")


def test_standard_payload_validation_rejects_unresolved_prompt_placeholder() -> None:
    payload = build_runninghub_standard_payload(
        "Keep the approved action in frame.",
        8,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    payload["prompt"] = "Keep {{approved_action}} in frame."

    try:
        validate_runninghub_standard_payload(payload, fixed_b=True)
    except PayloadError as error:
        assert "unresolved placeholders" in str(error)
    else:
        raise AssertionError("unresolved prompt placeholders must be rejected")


def test_standard_payload_validation_rejects_non_public_literal_media_hosts() -> None:
    for host in (
        "localhost",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "[::1]",
        "[fc00::1]",
        "[fe80::1]",
    ):
        payload = build_runninghub_standard_payload(
            "Keep the verified performance.",
            8,
            "9:16",
            ["https://media.example/board.png"],
            [],
            real_person_mode=False,
        )
        payload["imageUrls"] = [f"https://{host}/board.png"]
        try:
            validate_runninghub_standard_payload(payload, fixed_b=True)
        except PayloadError as error:
            assert "public HTTPS" in str(error)
        else:
            raise AssertionError(f"{host} must not be accepted as public media")


def test_standard_client_posts_payload_without_legacy_wrapper_or_generic_key() -> None:
    calls: list[dict[str, object]] = []

    def request_json(**kwargs: object) -> tuple[int, dict[str, object]]:
        calls.append(dict(kwargs))
        return 200, {"taskId": "task-123"}

    payload = build_runninghub_standard_payload(
        "Keep the verified performance.",
        5,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    client = RunningHubStandardSeedanceClient(
        "standard-key",
        request_json=request_json,
    )

    assert client.create_video(payload) == "task-123"
    assert calls == [
        {
            "method": "POST",
            "url": "https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
            "headers": {
                "Authorization": "Bearer standard-key",
                "Content-Type": "application/json",
            },
            "json_body": payload,
            "timeout": 90,
        }
    ]


def test_standard_provider_configuration_uses_a_dedicated_enterprise_key() -> None:
    settings = load_settings(
        environ={
            "RUNNINGHUB_API_KEY": "workflow-key",
            "RUNNINGHUB_SEEDANCE_API_KEY": "enterprise-standard-key",
        }
    )

    settings.require_seedance()
    assert settings.seedance_api_provider == "runninghub_standard"
    assert settings.runninghub_seedance_api_key == "enterprise-standard-key"
    preflight = build_redacted_provider_preflight(
        environ={"RUNNINGHUB_SEEDANCE_API_KEY": "enterprise-standard-key"}
    )
    assert preflight["runninghub_seedance_api_key"] == "present"
    assert set(settings.__dataclass_fields__) == {
        "runninghub_api_key",
        "runninghub_base_url",
        "runninghub_seedance_api_key",
        "runninghub_seedance_create_url",
        "runninghub_seedance_query_url",
        "runninghub_seedance_upload_url",
        "seedance_api_provider",
    }
    assert not any("youdao" in key.lower() for key in preflight)


--- IMPLEMENTATION PLAN ---

# RunningHub Standard Seedance Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every USFR Seedance video task through RunningHub鈥檚 documented `seedance-2.0-fast-token` standard-model API, without changing source analysis, the two user approvals, storyboard generation, ASR/TTS, lip-sync, or final QC.

**Architecture:** Keep USFR鈥檚 internal prompt, contract, approval and idempotency gates unchanged. Replace only the final video-provider boundary with a RunningHub standard-model adapter: it uploads only permitted storyboard/target/audio references to the new-key account, sends the documented direct request body, polls the documented query endpoint, and downloads a successful MP4 immediately. The source video, opaque UI media and tail media remain forbidden references for Seedance generation.

**Tech Stack:** Python 3, `urllib`, pytest, RunningHub Standard Model API, existing USFR payload/audit contracts.

## Global Constraints

- Use a dedicated `RUNNINGHUB_SEEDANCE_API_KEY`; keep `RUNNINGHUB_API_KEY` for existing storyboard/ASR/TTS/lip-sync workflows so a consumer workflow key is never accidentally used for the enterprise standard-model endpoint.
- Standard video endpoint: `https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video`; query endpoint: `https://www.runninghub.cn/openapi/v2/query`; upload endpoint: `https://www.runninghub.cn/openapi/v2/media/upload/binary`.
- Send only the documented standard-model fields: `prompt`, `resolution`, `duration`, `imageUrls`, `videoUrls`, `audioUrls`, `generateAudio`, `ratio`, `realPersonMode`, `conversionSlots`, `returnLastFrame`, `seed`.
- Do not send source video, source slices, opaque UI videos or tail videos to the video model. Fixed-B USFR generation sets `videoUrls` to `[]`.
- Keep normal replication at `720p`, `9:16`, 4鈥?5 seconds, and `generateAudio=true`; keep the approved `@Audio1` phrase in the prompt when the selected background-music/singing route supplies one segment-bounded audio reference.
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

Use multipart upload only for local permitted storyboard, target-image and segment-bounded audio files. Validate public HTTPS URLs, a 4鈥?5 second request duration, 0鈥? images, 0鈥? audio reference for USFR, no video references, and a direct `taskId` response. Poll `QUEUED`/`RUNNING`, fail on terminal failure, and download the first `results[].url` immediately after `SUCCESS`.

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
- Music/singing still uses `@Audio1` in the compiled prompt, while the external request uses RunningHub鈥檚 documented `audioUrls` field.

