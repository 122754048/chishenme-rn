# Dynamics Semantic Quality Contract

A result is not acceptable merely because its JSON schema and timeline coverage
are valid. It must be detailed enough to drive reverse scripting, storyboards,
motion replication, continuity, audio planning, and overlay routing.

## Cut quality

- Run a second semantic subdivision pass after detecting edits and scenes.
- Split on gesture direction, hand pose, facial expression, body pose, gaze,
  object state, camera direction/speed/hold, subtitle interval, overlay phase,
  spoken phrase, and important sound change.
- Do not target a preset Cut count, but do not merge multiple evidenced phases
  into vague labels such as `speaks and gestures`.
- Give every Cut a distinct action phase and a concrete physical end state.
- Prohibit `continues to next cut`, `same as before`, or other non-observational
  continuity placeholders.

## Event quality

- Record audible speech and visible matching subtitles as separate events.
- Record music, sound effects, ambience, and meaningful silence independently.
- Keep exact event time ranges and mapped Cut ranges.
- Mark uncertainty or inaudibility instead of inventing text.

## Source-truth boundary

- Source brands, identities, products, App names, UI claims, and selling points
  may be observed privately but must not become downstream replacement truth.
- Describe their structural role generically in the dynamics contract.
- Route exact overlay geometry to the overlay contract when required.

## Migration comparison

When replacing an established analyzer, compare the candidate with an approved
historical output from the original workflow. Compare analysis density, field
specificity, physical end-state quality, event coverage, uncertainty behavior,
and downstream usability rather than expecting identical content from different
videos. A materially coarser candidate fails unless the source itself contains
less observable phase change and that exception is documented with evidence.

## High-fidelity profile quality gate

The optional `extensions.high_fidelity_hybrid_v1` record is produced from the
same single semantic pass and the same cached frames/audio. It must not trigger
a second routine full-video inspection. For each semantic Cut, quality requires:

- normalized entity/anchor geometry whose boxes remain within `[0,1]`;
- an explicit framing migration strategy and topology constraint;
- lighting origin, direction, hardness, contrast, temperature, and shadow;
- observed expression, gaze, posture, and gesture phases when a performer is
  identifiable, with explicit not-applicable evidence otherwise;
- a contiguous physical state sequence ending in a concrete completed end state;
- every overlapping speech, music, Foley, ambience, and meaningful-silence
  event mapped to a visible action, proof factor, or preservation obligation;
- evidence, provenance, confidence, uncertainty, criticality, and blocker
  threshold for every high-criticality factor.

Opaque and source-origin intervals are route-excluded. Their extension rows are
technical metadata only; semantic description, identity, UI/OCR, claims, and
commercial analysis are invalid on that route.
