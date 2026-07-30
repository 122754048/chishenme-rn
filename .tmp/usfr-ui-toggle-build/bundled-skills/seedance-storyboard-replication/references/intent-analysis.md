# Weighted Intent Analysis

Use this once before Route 2 reverse-writing and cache the result as
`analysis/intent_weighted_contract.json`. Keep the pass short and evidence-led.
Do not invent a marketing intention from a single attractive face, logo, or
generic walk cycle.

## Required Schema

```json
{
  "primary_intent": "one sentence",
  "audience_and_platform": "who and where",
  "evidence": [
    {"time_range": "0.00-2.00s", "observation": "visible action/copy/edit", "supports": ["attention_hook"]}
  ],
  "weights": {
    "commercial_goal": 0,
    "attention_hook": 0,
    "character_or_creator_appeal": 0,
    "product_proof": 0,
    "emotional_promise": 0,
    "social_or_trust_signal": 0,
    "cta_conversion": 0,
    "pacing_and_format": 0,
    "platform_compliance": 0
  },
  "cut_allocation": [
    {"cut": "1-2", "intent": "attention_hook", "weight": 20, "script_instruction": "..."}
  ],
  "compliance_boundary": ["..."],
  "uncertainties": ["..."]
}
```

All weights are integers and must total 100. The weight table describes the
relative importance of intent, not seconds. The `cut_allocation` maps the
highest-weight categories to concrete Cuts and required script behavior.

## Evidence Rules

- `commercial_goal` comes from the product/App, offer, download CTA, or spoken
  claim, not from the source brand identity alone.
- `attention_hook` may include camera movement, a visual reveal, contrast,
  beauty/fashion appeal, surprise, humor, or a strong first-frame action.
- An attractive adult model or mild body movement can be labeled
  `character_or_creator_appeal` or `attention_hook` when the video repeatedly
  frames the adult's appearance, silhouette, walk, turn, or outfit to hold
  attention. Describe the observed tactic neutrally as **成年人物吸引力/轻微
  暗示性动作**. Do not label it explicit sexual content unless the source shows
  explicit sexual behavior or exposed intimate areas.
- `product_proof` requires visible product/UI use, feature demonstration,
  screenshots, packaging, or a concrete product result.
- `cta_conversion` requires a download, purchase, follow, message, click, or
  other explicit next action.
- `platform_compliance` is always present. It captures the boundary that keeps
  the hook suggestive but non-explicit: adult subjects only, no nudity, no
  exposed intimate areas, no fetishized close-ups, no sexual acts, no coercion,
  and no misleading product claim.
- If evidence is weak, lower the category weight and record the uncertainty;
  never compensate with extra speculation.

## Example: Social App With Adult Attention Hook

For a social-App ad with an adult woman walking, turning toward camera, then
showing social UI and an App Store end card, a concise contract could allocate:

```json
{
  "primary_intent": "Use an adult woman's confident visual appeal to stop the scroll, then convert that attention into a Tantan download by showing discovery, matching, chat, and a clear App Store CTA.",
  "weights": {
    "commercial_goal": 25,
    "attention_hook": 20,
    "character_or_creator_appeal": 20,
    "product_proof": 15,
    "emotional_promise": 5,
    "social_or_trust_signal": 5,
    "cta_conversion": 5,
    "pacing_and_format": 3,
    "platform_compliance": 2
  },
  "cut_allocation": [
    {"cut": "1-4", "intent": "attention_hook + character_or_creator_appeal", "weight": 40, "script_instruction": "Keep the adult woman fully clothed, confident, naturally walking and making a brief body/face turn that shows silhouette and presence without explicit sexual framing."},
    {"cut": "5-6", "intent": "product_proof", "weight": 15, "script_instruction": "Show complete official discovery, match, message, and chat UI pages with readable structure and upward scroll."},
    {"cut": "7-9", "intent": "commercial_goal + cta_conversion", "weight": 30, "script_instruction": "Move the supported CTA logic into the last non-tail generated Cut. Treat any terminal icon, wordmark, App Store badge, or download-only card as excluded_app_end_card and handle it only by supplied opaque splice or omission."}
  ],
  "compliance_boundary": ["adult subject", "fully clothed", "non-explicit movement", "no nudity or intimate-area focus", "no sexual acts", "no misleading claim"]
}
```

This example must be adapted to evidence and product truth. It is a reasoning
template, not a license to add sexualized movement when the source does not show
it.

## Evidence-backed selling-point contract

Intent analysis also writes `selling_point_mapping.json`. Every source and target
selling point uses the same chain:

```text
Feature → Mechanism → Benefit → Proof → CTA
```

- **Feature**: the target capability or characteristic actually supported by
  supplied evidence.
- **Mechanism**: how the feature works, stated only when the target evidence
  explains or demonstrates the mechanism.
- **Benefit**: the user outcome that follows from that mechanism; keep it
  proportional to the proof.
- **Proof**: a visible product/UI state, result, official screenshot,
  packaging/detail, spoken claim, or other timecoded evidence. Source-brand
  pixels and unsupported competitor claims are not target proof.
- **CTA**: the next action supported by the offer and platform context (for
  example purchase, download, follow, message, or learn more).

Each mapping records source evidence, target evidence, Cut/time range,
confidence, criticality, and migration route. If a source claim cannot be
supported by the target product/service/App, mark it `unsupported`, lower it to
an evidence-backed experience statement, or remove it. Never invent a feature,
mechanism, result, review, number, certification, or guarantee to fill the
original selling-point position.

```json
{
  "source_claim": "observed claim or visual proof",
  "status": "supported|unsupported|reinterpreted",
  "feature": "target truth",
  "mechanism": "verified mechanism or null",
  "benefit": "bounded user outcome",
  "proof": [{"kind": "screenshot", "time_range": "05.2-06.8s", "ref": "..."}],
  "cta": "approved next action",
  "route": "REPLACE",
  "confidence": 0.9
}
```

## Optional high-fidelity analysis sidecar

When the run snapshot selects `high_fidelity_hybrid_v1`, produce the immutable
additive sidecar `analysis/high_fidelity_analysis.json`. It does not change the
public workflow, public inputs, approvals, stages, routes, provider calls, or
the authoritative legacy artifact names. Validate and project it with
`scripts/high_fidelity_analysis.py` before the existing script freeze.

The deep Source Intent Graph is always ordered:

```text
Attention -> Curiosity -> Understanding -> Belief -> Desire -> Action -> Loop
```

Every active node binds Cuts/time ranges, audience-state change, commercial
job, presentation archetype, attention/proof mechanism, emotional/trust/CTA
function, evidence, confidence, uncertainty, criticality, blocker threshold,
and a deterministic projection into the exact legacy nine-key weight contract.
The nine legacy integer weights remain authoritative and must total 100. Each
integer point is assigned exactly once to a legacy key and Cut allocation.

Build the Target Value Graph only from validated target-owned evidence:

```text
Target truth -> Feature -> Mechanism -> Benefit -> Proof
-> Audience relevance -> Objection resolved -> Trust signal -> CTA
```

Every source node has one migration edge with
`exact|functional|intent_only|unsupported`. An analogous `functional` proof is
Level 2 `REINTERPRET`; it is not silently treated as equivalent Level 1 proof.

Decompose every selling point into a claim atom. Its sidecar disposition
projects deterministically into the existing
`supported|unsupported|reinterpreted` enum. Unsupported claims remain present
for audit but are excluded from the script projection and use `REMOVE`; they
cannot be filled by model invention.

Before script writing, create an affordance ledger for observable source and
target state sequences, proof/audio events, feasibility, match level, fidelity
level, route, carrier, fallback, and evidence. For App targets, every UI state
needs state-matched target evidence or an operation-video record; a screenshot
does not prove an unseen navigation or result state.

Finally create a per-Cut layer ledger using only Level 0/1/2 and
`KEEP|REPLACE|COMPOSITE|REMOVE|REINTERPRET|OPAQUE_SPLICE`. Aggregate the Cut
from the actual carrier: opaque media wins, then Seedance generation, then
deterministic composite, otherwise source interval. Every high-criticality
factor requires evidence and a real carrier.
