## Session 1 — 2026-07-30

**Strategy:** Rebuild the complete song-lip-sync delivery through the canonical USFR timeline splicer instead of slicing opaque media back out of an earlier final render.

**Decisions:** Use the uploaded UI video directly at its natural active duration of 4.7 seconds; start S02 immediately at output 9.7 seconds; detect and trim the supplied tail video's trailing full-black interval so only 0.0–2.1 seconds is appended; preserve 30 ms anti-pop audio fades at every non-source hard cut.

**Reasoning log:** The previous 9.7–10.0 second duplicate S02 pre-roll came from extracting UI from an old final render; the previous terminal black screen came from retaining the tail upload's 2.1–4.67 second full-black interval.

**Outstanding:** None. Future song-route assembly must use the immutable uploaded opaque UI/tail artifacts plus the canonical timeline manifest and must not publish when final black/freeze/splice QC fails.
