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

