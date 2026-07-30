---
name: analyze-reference-video-dynamics
description: "Analyze any reference video from frame zero to its exact end and produce a platform-neutral, frame-accurate dynamics contract covering Cuts, body/object action phases, camera motion, scene progression, transitions, speech, subtitles, sound events, and uncertainty. Use when a video-generation, editing, recreation, storyboard, motion-transfer, or QA workflow needs source timing and movement structure without copying source identities or product/App truth."
---

# Analyze Reference Video Dynamics

## Objective

Describe what the source video does over time. Do not decide replacement identities, write an adapted story, generate images, or submit a video model.

## Required references

Read [references/dynamics-contract.md](references/dynamics-contract.md) before producing the final JSON.
Read [references/analysis-quality-contract.md](references/analysis-quality-contract.md)
before accepting any semantic analysis.

## Workflow

1. Probe the complete video:

   ```text
   python scripts/probe_video.py <video> --output <private-dir>/video_probe.json --detect-scenes
   ```

2. Inspect the complete timeline with GPT and frame-accurate decoder evidence.
   Build one adaptive evidence set containing:
   - complete-timeline contact sheets from frame zero through the exact end;
   - first/last decoded frames and scene/edit candidate neighborhoods;
   - boundary frames before and after every action, gesture, expression, gaze,
     object, camera, lighting, subtitle, overlay, and transition phase change;
   - intermediate adaptive keyframes for motion direction, speed, contact,
     reversal, and hold verification;
   - full-resolution frames or crops for small product, hand, face, UI, and text
     evidence;
   - separate audio transcription and timing evidence.
   Scene candidates and fixed-interval samples are hints only and must never be
   the sole analysis source.

   In the server runtime, `scripts/adaptive_evidence_plan.py` is the canonical
   request contract for that same pass. `FfmpegDynamicsAnalyzer` builds and
   validates exactly one `evidence_plan` from the verified probe, source SHA,
   and decoder boundary candidates, returns it in the existing analyze output,
   and passes the unchanged plan to the semantic backend. The packaged HTTP
   VLM adapter includes the plan in its request, so the existing request SHA-256
   binds the semantic response to the exact plan. The plan may contain hashes,
   media metadata, and timestamps, but never a lease-local path. This executable
   handoff remains Shadow evidence until the normal activation gates pass; it
   is not by itself proof of advertising-grade semantic fidelity.
3. Reconcile every observed boundary with decoder timestamps and retain
   uncertainty instead of guessing.
4. Split at every real edit, action phase, camera phase, subject state, object/App state, spoken phrase, subtitle interval, transition, important sound cue, or overlay visibility/motion phase change.
5. Record exact source Cuts and separate audio/text events.
6. Validate against both the dynamics contract and deterministic probe:

   ```text
   python scripts/validate_dynamics.py <source_dynamics_analysis.json> --probe <private-dir>/video_probe.json
   ```

   When the persisted run profile is `high_fidelity_hybrid_v1`, validate its
   optional extension from the same single semantic pass and cached evidence:

   ```text
   python scripts/validate_high_fidelity_extension.py <source_dynamics_analysis.json>
   ```

   Legacy runs skip this additive validator. Never perform a second routine
   full-video analysis merely to populate the extension.

7. Run semantic quality validation. During migration, compare against an
   approved historical analysis produced by the original workflow:

   ```text
   python scripts/validate_dynamics_quality.py <source_dynamics_analysis.json> --probe <private-dir>/video_probe.json --baseline <approved-original-analysis.json> --report <private-dir>/dynamics_quality_report.json
   ```

   A schema-valid but semantically coarse result is invalid.

For active `high_fidelity_hybrid_v1`, sampled-frame evidence is Cut-local and
must be bound to decoded timing, not just to a digest string. The server-side
VLM adapter verifies that every source/semantic Cut cites at least one decoded
sample in its half-open `[start_us, end_us)` interval. If identical pixels
produce one SHA at multiple times, the sidecar must include `timestamp_us` to
disambiguate the sample; otherwise the evidence is rejected as ambiguous.
An active frame budget that cannot cover every source Cut fails closed before
semantic facts are accepted. This is an evidence boundary, not an extra
analysis pass or public input.

## Analysis rules

- Cover `0` through the exact probed end without gaps or overlaps.
- Do not sample at fixed intervals or target a preset Cut count.
- Keep one motion direction/phase per Cut. Split when action or camera motion reverses, changes speed class, enters a hold, or exits a hold.
- Distinguish identifiable people, partial/hands, transition residue, screen-pixel people, none, and uncertain.
- Treat people and rooms inside device/UI pixels as screen content, not live scene truth.
- Separate observation from interpretation. Mark uncertain or inaudible content instead of guessing.
- A replacement image, prompt, or downstream product must not change this source analysis.
- GPT observations must not weaken, omit, rename, or reinterpret these rules.

## Identity boundary

The source video authorizes structural facts by default: timing, framing,
motion, action function, scene progression, edit rhythm, audio timing, and
transition behavior. When the fixed input manifest has no replacement slot for
an identity/product/UI layer, the top-level contract may additionally mark that
source layer as local KEEP/source-interval evidence. It must never become a new
target claim or be uploaded as a provider reference.

## Output boundary

Return `source_dynamics_analysis.json` plus a concise audit summary. Keep frames, waveforms, OCR crops, and temporary audio private and out of image/video generators.
