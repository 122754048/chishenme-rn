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
