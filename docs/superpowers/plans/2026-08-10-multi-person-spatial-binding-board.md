# Multi-Person Spatial Binding Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Test one additional spatial binding map as the sole new variable in a single four-person Seedance edit request.

**Architecture:** A private Pillow builder creates an audited board from the four existing approved identity images. The existing submission script appends its uploaded URL as `@Image5` and adds one mapping-only role clause; all existing identity and Provider inputs remain unchanged.

**Tech Stack:** Python 3, Pillow, pytest, existing RunningHub uploader and Seedance prompt compiler.

## Global Constraints

- Never submit an unchanged request SHA.
- One request must attempt all four replacements simultaneously.
- Do not modify the formal USFR workflow until live QC reaches 4/4.
- Change only the spatial binding board variable for this paid attempt.

---

### Task 1: Deterministic board builder

**Files:**
- Create: `analysis/private/reinbow_person_replace/build_spatial_binding_board.py`
- Create: `analysis/private/reinbow_person_replace/test_spatial_binding_board.py`

**Interfaces:**
- Produces: `build_board(identity_dir: Path, output_path: Path) -> dict[str, object]`

- [ ] Write a failing test asserting 1080x1920 output, four stable tags, four source IDs, and deterministic SHA.
- [ ] Run the focused test and confirm failure because the builder is absent.
- [ ] Implement a neutral cast-position map with Pillow using the fixed four approved inputs.
- [ ] Run the focused test and confirm pass.

### Task 2: Private request integration

**Files:**
- Modify: `analysis/private/reinbow_person_replace/four_person_once.py`

**Interfaces:**
- Consumes: `spatial_binding_board_v1.png` and its manifest.
- Produces: a five-image request where image 5 is mapping-only.

- [ ] Add a dry-run assertion that `@Image1..4` SHA/order are unchanged and `@Image5` is the binding map.
- [ ] Upload/cache the board URL separately from identity URLs.
- [ ] Add the mapping-only prompt clause without changing the four subject definitions.
- [ ] Run one dry-run and record the new request SHA.

### Task 3: One paid generation and QC

**Files:**
- Produce: `analysis/private/reinbow_person_replace/four_person_once/result_<sha>.mp4`
- Produce: `analysis/private/reinbow_person_replace/four_person_once/qc_<sha-prefix>/`

- [ ] Submit the new SHA once.
- [ ] Reconcile the same task ID until terminal status.
- [ ] Download without overwriting earlier results.
- [ ] Extract matched frames and score TARGET_MAN, TARGET_BLONDE, TARGET_DARK, and TARGET_CAT separately.
- [ ] Only after 4/4, migrate the optional board builder and binding-map contract into USFR with regression tests.

### Task 4: Local two-track completion fallback

**Files:**
- Create: `analysis/private/reinbow_person_replace/local_multi_face_completion.py`
- Create: `analysis/private/reinbow_person_replace/test_local_multi_face_completion.py`

**Interfaces:**
- Consumes: best 2/4 Provider MP4, TARGET_BLONDE portrait, TARGET_DARK portrait, local InsightFace models.
- Produces: one MP4 with the original audio and two locally completed face tracks.

- [ ] Test unique embedding assignment independently of detector order.
- [ ] Decode the best Provider result and initialize left/center/right identities from the first frame.
- [ ] Match every decoded face uniquely by embedding similarity and motion continuity; swap only blonde and dark.
- [ ] Encode H.264 and copy the source audio without re-generation.
- [ ] QC matched frames and reject any frame that swaps the man or cat.
