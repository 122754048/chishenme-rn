# Commercial Productization Design

## Summary

This design upgrades the current Expo iOS app from a polished demo into a commercial-ready food decision product.

The main shift is product-level, not cosmetic:

- move the core promise from "swipe through dishes" to "help me decide what to eat now"
- delay monetization until after the user experiences recommendation value
- make preference data actually influence recommendations
- turn detail pages into decision tools instead of static presentation screens
- express paid value as better outcomes, not just more usage quota

This design keeps the existing React Native / Expo structure, Apple IAP stack, and current navigation model. It does not introduce live merchant integrations, maps, or ordering systems in this phase.

## Product Goal

Ship an iOS app that feels credible as a paid consumer product for daily meal decisions.

The product should help users:

- reduce decision fatigue
- find food that fits taste, restrictions, time, and budget
- build confidence in recommendations
- understand why the app is recommending something

The business goal is to improve:

- Day 0 activation
- recommendation engagement
- upgrade intent after first value realization
- paid-plan credibility

## Non-Goals

This phase does not include:

- live restaurant inventory
- native location-aware store discovery
- checkout for real-world meals
- social feeds or UGC reviews
- push notification CRM
- backend recommendation models beyond current app-side logic and existing backend membership/quota support

## User Problems To Solve

### Current Problems

1. Users are asked for cuisine and restriction preferences, but those preferences do not visibly affect home recommendations.
2. Users hit the paywall before experiencing a clear "this app gets me" moment.
3. The detail page looks premium but does not help the user make a real decision.
4. Search and discovery are too shallow to support repeat daily use.
5. Paid plans describe entitlement, not concrete user outcomes.

### Product Hypothesis

If the app gives users one or two high-confidence meal decisions before pushing subscription, and if each recommendation is transparently explained, users will trust the product more and convert at a higher-quality point.

## Target Experience

The product should feel like:

- fast enough for "what do I eat right now?"
- smart enough to reflect taste and restriction input
- clear enough that users understand why a suggestion fits
- premium enough that subscription feels justified

The app should not feel like:

- an image carousel
- a lifestyle mockup
- a restaurant marketplace with no actual commerce
- a quota-locked toy

## Core Experience Changes

### 1. Reframe The Main Product Loop

New loop:

1. user sets cuisine + restriction preferences
2. user lands in the recommendation experience directly
3. the app shows a recommendation with explanation and confidence
4. user likes, skips, or opens details
5. after meaningful usage, the app introduces paid upgrade

Upgrade should no longer be a required step immediately after onboarding preferences.

### 2. Make Recommendation Relevance Visible

Each recommendation needs visible reasoning such as:

- "matches your preferred cuisine"
- "avoids your restricted ingredients"
- "fits a quick lunch"
- "budget-friendly tonight"

The recommendation stack should use:

- selected cuisines
- selected restrictions
- price sensitivity buckets
- meal context tags
- quick-prep vs indulgent intent

Even if the underlying scoring remains client-side, the user should perceive recommendation intelligence.

### 3. Convert Detail From Showcase To Decision Assistant

The detail screen should answer:

- why this is recommended now
- whether it fits the user's restrictions
- whether it is better for lunch / dinner / solo / sharing
- how expensive and time-heavy it is
- what similar alternatives exist if the user is unsure

Primary CTA should move away from a fake transactional pattern ("estimated total price") toward a real decision action such as:

- choose this for today
- save to tonight list
- compare with similar options

### 4. Change Monetization Narrative

Current monetization reads like quota unlock.

Paid plans should instead sell:

- better recommendation quality
- more powerful decision filters
- richer AI explanation
- family decision support
- saved plans and multi-person preference blending

Quota can remain as part of free-vs-paid structure, but it should not be the hero message.

## Information Architecture

### Onboarding

Screen 1: cuisines
- select preferred cuisines
- lightweight skip remains available

Screen 2: restrictions
- select ingredients / allergy / dislike inputs
- custom restriction remains

After restrictions:
- go to home recommendation experience
- do not force upgrade

### Home

Home becomes the product center.

It should include:

- one primary recommendation card
- visible recommendation reason
- quick context chips such as lunch / dinner / quick / comfort / healthy
- action row: skip / save / choose
- secondary path into explore

If the user has not completed enough preference data:
- show a gentle prompt to improve personalization

If quota is low:
- show upgrade messaging tied to better results, not only count depletion

### Explore

Explore should shift from generic browse to scenario-based discovery.

Add stronger filtering concepts:

- cuisine
- meal type
- budget level
- dietary fit
- quick choice / group choice / healthy choice

Search should remain lightweight, but results should feel aligned with user intent rather than random content buckets.

### Detail

Sections should become:

- recommendation summary
- why it fits you
- nutrition / prep / cost snapshot
- restrictions compatibility
- alternatives
- save / choose actions

### Upgrade

Upgrade becomes a value page, not a forced interrupt.

It should be entered from:

- quota friction
- advanced filter intent
- detail comparison / family use cases
- profile

### Profile

Profile remains the account center, but should emphasize:

- plan status
- restore purchase
- preferences
- saved decisions
- family use case preview

Static persona content should be replaced over time by real user-derived state.

## Data And Recommendation Design

### Existing Data Constraints

The app currently uses local mock content pools.

This phase keeps mock content, but restructures it so it behaves like product data rather than demo data.

### Required Data Enrichment

Food items should support fields like:

- cuisine
- mealType
- budgetBand
- decisionTags
- restrictionConflicts
- healthTags
- groupFit
- soloFit
- comfortScore
- speedScore
- premiumScore

### Recommendation Scoring

Client-side scoring should rank items using:

- positive score for cuisine matches
- negative score for restriction conflicts
- positive score for current scenario tags
- positive score for underrepresented but relevant alternatives
- promotion of high-confidence items early in the journey

The output should drive:

- home card order
- recommendation explanation copy
- alternative suggestions in detail

### Explainability

For each recommendation, produce 2-3 explanation reasons from the actual scoring inputs.

Example:

- matches your Japanese / Korean preference
- avoids cilantro and dairy
- ready in 15 minutes for a quick meal

## Commercialization Design

### Free Plan

Free should include:

- onboarding preferences
- basic recommendation stream
- basic search and save
- limited daily AI decision count

### Pro Plan

Pro should include:

- unlimited recommendation sessions
- advanced filters
- richer recommendation explanations
- better comparison / alternatives
- decision history insights

### Family Plan

Family should include:

- multi-person preference blending
- family dinner suggestion mode
- shared saved choices
- collaborative conflict reduction across preferences

### Upgrade Triggers

Primary upgrade triggers:

- free quota exhaustion
- attempt to use advanced filters
- attempt to compare alternatives
- repeated engagement with recommendation details

Upgrade should not trigger before first recommendation value is delivered.

## UX Rules

### Navigation

- keep bottom tabs stable
- keep home as the core product entry
- reduce dead-end moments
- maintain predictable back behavior

### Interaction

- the first-use guide must match real supported gestures
- do not teach unsupported gestures
- primary CTA per screen must be unambiguous

### Visual Tone

- reduce dependence on emoji as structural branding
- keep warmth and approachability
- make the product feel more trustworthy and less novelty-driven

### Empty / Failure States

- explain what the user can do next
- tie empty states to discovery or personalization
- tie payment failures to recovery steps

## Testing And Validation

### Product Acceptance Criteria

1. Onboarding no longer hard-routes every user into upgrade before home.
2. Home recommendation ordering changes based on selected cuisines and restrictions.
3. Home cards visibly explain why an item is recommended.
4. Detail page supports decision-making, not fake purchasing.
5. Upgrade copy emphasizes premium outcomes instead of only quota unlock.
6. Search / explore reflect stronger scenario relevance.
7. First-use guidance matches implemented gestures and actions.

### Technical Validation

Continue running:

- `npm run lint`
- `npm test`
- `cd backend && python -m unittest discover -s tests -v`

Add or update smoke checks for:

- onboarding route no longer auto-forces upgrade
- recommendation explanation exists
- detail CTA no longer implies unsupported real-world transaction
- upgrade copy contains premium-value messaging

## Implementation Boundaries

This phase should stay inside the current app architecture:

- React Native screen updates
- local mock-data enrichment
- app-context recommendation logic
- lightweight copy / UX updates
- existing membership and Apple IAP infrastructure

Avoid backend-heavy expansion unless needed to preserve current subscription behavior.

## Risks

1. Overwriting the simple, fast home experience with too much explanatory UI.
2. Creating recommendation logic that looks complex but still feels arbitrary.
3. Introducing too many paid claims before the underlying product actually supports them.
4. Adding family-plan messaging without enough real family workflow support.

## Recommended Delivery Order

1. recommendation logic and content model
2. onboarding flow update
3. home redesign for recommendation explanation
4. detail page redesign into decision assistant
5. explore relevance improvements
6. upgrade value rewrite
7. smoke-test and release-gate updates
