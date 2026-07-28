# Task 3 Report — RunningHub standard Seedance audio payload

## Scope

Modified only the four Task 3 implementation/test files, plus this required report:

- `backend/app/background_music_execution.py`
- `backend/app/background_music_local_mvp.py`
- `backend/tests/test_background_music_execution.py`
- `backend/tests/test_background_music_local_mvp.py`

## Result

Background-music and singing execution contracts now submit the standard RunningHub Seedance video shape:

```json
{
  "model": "seedance-2.0",
  "prompt": "... @Audio1 ...",
  "audioUrls": ["https://runninghub.example/openapi/song-clip.mp3"]
}
```

The final provider payload rejects legacy `content`, `audio_url`, `reference_audios`, and `asset://` shapes.  The exact `@Audio1` lyric/singer prompt, route eligibility, frozen timing evidence, final exact-fragment mix, and singing QA remain in the existing execution contract.

## Upload boundary and bounded clip behavior

- The compiler accepts only a completed RunningHub upload receipt with `runninghub_audio_url`, `clip_kind: "seedance_segment"`, and segment timing that exactly matches the clip duration.
- Provider-facing clips must be 2–15 seconds.  Full-song and 16-second receipts are rejected.
- The local MVP requires an injected `runninghub_audio_upload` callback; it does not synthesize an upload URL.
- The MVP materializes a separate WAV clip for the frozen generated segment (`output_duration_ms`) and passes that clip—not the full archived song—to the callback.  The clip must cover the declared generated segment; missing/too-short source audio fails closed.
- The full uploaded track is still retained exclusively for the deterministic post-generation mix and its existing fragment/QA receipts.

## TDD evidence

### Initial standard-payload red

Command:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q -x
```

Observed expected failure before production changes:

```text
KeyError: 'audioUrls'
FAILED test_uploaded_song_is_the_final_audio_authority_without_time_or_pitch_transform
```

The original full focused run showed exactly two legacy-shape failures (execution payload and local MVP payload).

### Duration-bound receipt red / green

Red command:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py -q -k duration_bound_runninghub_upload_receipt
```

Red output:

```text
Failed: DID NOT RAISE <class 'ValueError'>
1 failed, 65 deselected
```

Green command/output:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py -q -k duration_bound_runninghub_upload_receipt
```

```text
1 passed, 65 deselected
```

### 2–15 second segment red / green

Red command:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py -q -k 'full_or_oversized_runninghub_audio_upload or two_second_runninghub_segment_clip'
```

Red output:

```text
3 failed, 66 deselected
```

The failures proved that 16s and 30s/full-song receipts were accepted and that a valid 2s segment for a longer uploaded track was incorrectly rejected.

Green command/output:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py -q -k 'full_or_oversized_runninghub_audio_upload or two_second_runninghub_segment_clip'
```

```text
3 passed, 66 deselected
```

### Frozen generated-segment binding red

Command:

```powershell
python -B -m pytest backend/tests/test_background_music_local_mvp.py -q -k frozen_generated_segment
```

Red output before binding extraction to the frozen output segment:

```text
Failed: DID NOT RAISE <class 'ValueError'>
1 failed, 6 deselected
```

This regression proves the former hard-coded first-two-seconds behavior was not safe; the implementation now derives the clip duration from `music_timeline_contract.output_duration_ms` and fails closed when the source cannot cover it.

### Focused suite green

Command:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q
```

Result: independently verified green by the controller after the final frozen-segment binding change.

## Concerns / deployment follow-up

- The production upload adapter must return a real, externally materialized HTTPS RunningHub URL and the exact receipt fields enforced here. No live keys or live provider calls were used in this work.
- The local MVP represents one provider request for the whole frozen output span. A future multi-segment provider flow must materialize and bind one receipt/clip per declared generated segment rather than reuse this single-span receipt.
- This shared worktree contains unrelated user changes. They were not altered or staged.

## Follow-up: immutable generated-segment binding

Review found that a receipt could be internally duration-consistent while referring to the wrong generated video segment.  This is now closed without introducing a caller-controlled timing source:

- The compiler derives the expected provider segment from the immutable music timeline's existing `output_start_ms` coverage and `output_duration_ms` end bound.
- `audio_asset_receipt.seedance_segment.start_ms` and `.end_ms` must exactly equal that canonical output span, in addition to satisfying the 2–15 second duration rule.
- The audit stage re-runs the same receipt validation against the frozen execution timeline before publishing the request artifact.
- The test helpers now materialize deterministic trailing silence where needed so their frozen provider segment is a valid 2-second minimum, while media validation continues to prove the music fragment itself remains exact.

### Follow-up TDD evidence

Red command:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py -q -k wrong_frozen_output_segment
```

Red output:

```text
Failed: DID NOT RAISE <class 'ValueError'>
1 failed, 69 deselected
```

The regression uses a 2-second receipt with valid internal duration but an incorrect `seedance_segment` (`2000–4000 ms`) while the frozen output segment is `0–2000 ms`.

Green verification:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py -q
```

```text
70 passed in 13.65s
```

Final focused verification:

```powershell
python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q
```

Completed successfully after the binding change (focused execution module: 70 passed; local-MVP module also completed in the same run).
