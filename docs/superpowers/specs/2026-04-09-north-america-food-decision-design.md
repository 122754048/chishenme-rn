# North America Food Decision App Design

## Summary

This document defines the next commercial product step for the current React Native iOS app. The goal is not to rebuild the app. The goal is to upgrade the existing swipe-based recommendation product into a launch-ready North America consumer app with stronger local relevance, English-first product language, better restaurant trust signals, and a premium food-app feel.

The app remains a daily food decision product for people who regularly do not know what to eat. The core interaction remains the swipe deck. The supporting features exist to make each swipe more useful, not to replace the swipe flow.

## Product Goal

Help users in North America decide what to eat faster by combining:

- their saved cuisine preferences
- their dietary restrictions
- their current location or manually entered area
- time-of-day context
- nearby restaurant trust signals from Google Places
- optional menu scanning for in-restaurant or screenshot-based dish recommendation

The app should feel like a real premium iOS food product, not a generic AI recommendation shell.

## Non-Goals

This phase does not include:

- rebuilding navigation or app architecture from scratch
- a marketplace-style restaurant discovery app
- direct ordering, reservation, or delivery checkout flows
- multi-user/family collaboration
- weekly reports, reminders, or habit loops from the later retention phase
- a complete restaurant menu database
- true third-party dish-level ratings

## Target Market

- Primary market: North America
- Primary platform: iOS
- Primary user: a person who often wastes time deciding what to eat
- Primary usage moments:
  - lunch near work
  - dinner near home
  - fast solo decisions
  - low-energy browsing when the user wants a confident default
  - at-table menu decisions after a restaurant has already been chosen

## Product Positioning

This product is not a restaurant review app and not a menu OCR utility.

It is a food decision app.

The promise is:

- less decision fatigue
- better fit for personal taste and dietary needs
- faster nearby choices
- higher confidence when ordering from a menu

## Brand Direction

The current product name should be replaced with a North America-friendly English name. The recommended working name is `Teller`.

Reasons:

- short and memorable
- easier to pronounce and share in English-speaking markets
- feels product-like rather than descriptive or gimmicky
- supports a calm premium brand voice

The brand system should be designed so the name can still be swapped later if legal or App Store naming conflicts appear. Product architecture, code structure, and copy should not hardcode brand assumptions beyond a centralized brand token/config layer.

## Product Principles

1. Swipe remains the main action.
2. Every card should feel more useful than a random food image.
3. Nearby context should improve recommendation quality without making onboarding heavier.
4. Menu scan should extend the product at the table, not distract from the core use case.
5. Premium value should come from better decisions, not from arbitrary paywalls.
6. The app should feel human, calm, and trustworthy, not exaggerated or AI-branded.

## Core User Journey

### 1. First Run

The user chooses:

- favorite cuisines
- dietary restrictions
- optional saved areas such as Home and Work

The onboarding should stay short and should not force monetization before first value.

### 2. Main Swipe Experience

The user lands in the swipe deck.

Each card represents:

- one nearby restaurant
- one recommended signature dish from that restaurant

Each card explains:

- why this pick fits now
- how far it is
- Google rating and review confidence
- whether it fits the user's restrictions or needs caution

### 3. Decision Detail

The user can tap into a detail page that explains:

- why this restaurant and dish fit the user
- what dietary issues have been filtered or flagged
- what alternatives from the same place are worth considering
- how to scan a menu if the user is already looking at one

### 4. Menu Scan

The user can either:

- take a photo of a physical menu
- upload a screenshot of a digital menu

The app extracts likely menu items and returns:

- best picks for the user
- safe picks
- items to avoid
- short reasons tied to preferences and restrictions

## Information Architecture

### Home

Home remains the primary tab and main product experience.

Changes:

- keep the swipe deck
- replace dish-only cards with restaurant-plus-signature-dish cards
- add lightweight context filters:
  - Quick
  - Comfort
  - Healthy
  - Budget
  - Treat
- add location context and an easy area switcher

Home should answer one question fast: "What is a good choice for me right now?"

### Detail

Detail remains the second-level decision screen.

Changes:

- emphasize recommendation reasoning
- show restaurant trust and dish suitability together
- show dietary fit or caution clearly
- provide same-restaurant alternatives
- provide Scan Menu entry

### Explore

Explore remains in the app, but becomes a supporting tool rather than the primary product identity.

Changes:

- manual neighborhood or address entry
- location fallback when permission is denied
- broader browsing around the user's current context
- restaurant search instead of generic food browsing emphasis

### Profile

Profile remains lightweight.

Changes:

- English-first identity
- clearer North America subscription language
- saved area management
- preference editing
- restore purchase and account deletion remain

### Upgrade

Upgrade should position Pro around outcome quality:

- stronger ranking
- smarter filters
- menu scan recommendations
- more useful alternatives
- better repeat avoidance in future phases

## Recommendation Model

The existing scoring engine should be extended, not replaced.

Each recommendation should be scored using:

- saved cuisine preferences
- dietary restrictions
- current location or manually selected area
- distance and convenience
- time of day
- selected mood/state filter
- restaurant rating
- review count confidence
- dish-level fit metadata from the app's structured dataset
- novelty / repeat suppression

The model should still produce user-facing reasons. That is one of the product's strongest existing improvements and should remain central to the experience.

## Data Sources

### App-Owned Dish Metadata

The app continues to maintain its own normalized dish metadata for:

- cuisine mapping
- likely ingredients
- dietary conflict hints
- recommendation tags
- health-style tags
- moment-fit tags

This metadata powers the recommendation explanation layer.

### Google Places

Google Places should provide nearby restaurant trust signals, including where supported:

- restaurant identity
- coordinates and address
- rating
- review count
- review snippets
- open/closed state
- meal-serving metadata when available

Google data should be used for restaurant-level trust and proximity, not as a promise of dish-level rating accuracy.

### Menu Scan AI Extraction

External AI vision should convert menu photos and screenshots into structured menu candidates, including:

- item name
- optional description
- optional price
- inferred ingredients or risk hints
- optional category grouping when inferable

The app then applies its own preference and dietary logic to those candidates.

## Location Strategy

The app should support both:

- live current location
- manual area/address entry

Default behavior:

1. Request foreground location permission.
2. If granted, use current location.
3. If denied, unavailable, or imprecise, immediately fall back to manual area entry.

The app should allow saved contexts such as:

- Home
- Work

The UI must never hard-block the user on location permission.

## Menu Scan Feature Definition

### Inputs

- camera photo
- uploaded screenshot

### Processing

1. capture or import image
2. send image to AI extraction service
3. normalize extracted menu items
4. apply dietary filtering
5. score items against user taste profile
6. present ranked picks

### Outputs

The menu scan result view should contain:

- Best for you
- Safe picks
- Avoid or caution
- short explanations

This view should feel like an extension of the main recommendation engine, not a separate product.

## Visual Design Direction

### Design Language

The app should feel like a premium North America iOS consumer app influenced by Apple and Google design principles:

- clean hierarchy
- strong readability
- generous spacing
- restrained surfaces
- realistic food imagery
- minimal visual noise

It should not feel like:

- an AI assistant
- a crypto/gradient startup app
- a noisy food marketplace
- a social media feed

### Emotional Tone

The app should feel:

- warm
- useful
- calm
- tasteful
- premium casual

### Color System

The palette should keep food warmth without becoming loud.

Recommended direction:

- light neutral backgrounds
- warm off-white surfaces
- dark charcoal text
- a restrained warm brand accent in the burnt orange / tomato / muted saffron family
- subtle success, warning, and dietary states

Color should create appetite and warmth, but UI structure should still feel disciplined.

### Typography

Use a system-native feel. Premium quality should come from hierarchy and spacing, not decorative font choices.

Typography goals:

- readable at a glance
- strong title hierarchy
- compact supporting metadata
- no overly playful letterforms

### Motion

Motion should stay subtle:

- deck movement should feel confident, not flashy
- transitions should reinforce focus
- avoid ornamental motion that makes the app feel synthetic

## Content and Copy Direction

All user-facing copy should be rewritten for English-speaking North America users.

Tone should be:

- calm
- direct
- lightly premium
- not overexcited
- not "AI-powered" sounding

Examples of desired tone:

- "A strong pick for tonight."
- "Fits your usual taste and avoids dairy."
- "Closer and easier than your recent dinner picks."

Avoid:

- hype
- emoji-led UI copy
- chatbot-like phrases
- exaggerated personalization claims

## Subscription Strategy

Free should still provide real value.

Pro should clearly unlock:

- stronger recommendation depth
- menu scan and menu-aware dish ranking
- more detailed fit explanations
- broader filtering controls

This phase should not reintroduce an early paywall into onboarding.

## Required Code Changes

The implementation should stay within the current app shape and mostly extend existing files.

### Primary modified files

- `src/screens/Home.tsx`
- `src/screens/Detail.tsx`
- `src/screens/Explore.tsx`
- `src/screens/Upgrade.tsx`
- `src/screens/Profile.tsx`
- `src/screens/OnboardingCuisines.tsx`
- `src/screens/OnboardingRestrictions.tsx`
- `src/navigation/AppNavigator.tsx`
- `src/data/mockData.ts`
- `src/utils/recommendations.ts`

### New files expected

- `src/services/places.ts`
- `src/services/menuScan.ts`
- `src/utils/location.ts`
- one lightweight menu scan UI surface such as `src/screens/MenuScan.tsx` or a focused modal/sheet component

### Supporting checks

Existing smoke/release checks should be expanded to guard:

- English-first product copy in key flows
- location fallback support
- Google Places integration boundaries
- menu scan entry points
- restaurant-plus-dish deck structure

## Error Handling

### Location

- permission denied -> show manual area entry immediately
- location unavailable -> use last known location if possible, otherwise manual entry

### Google Places

- no results -> show calm fallback recommendations from app-owned dataset
- API failure -> do not break the deck; degrade gracefully
- incomplete place data -> render only available trust signals

### Menu Scan

- extraction failure -> offer retry and manual browse fallback
- low-confidence extraction -> present as "possible matches," not certainty
- dietary uncertainty -> show caution state instead of pretending confidence

### Subscription

Existing iOS IAP and account deletion compliance changes remain in force and must not regress.

## Testing Strategy

Testing should cover:

- recommendation ranking with location and dietary inputs
- manual area fallback when location is unavailable
- restaurant-plus-dish card rendering
- menu scan parsing and filtering logic
- English copy presence in critical screens
- no regression to early forced paywall
- existing iOS subscription and account flows

The test scope should expand existing smoke checks rather than invent a separate testing philosophy.

## Launch Readiness Standard

This phase should be treated as a commercial iOS launch step, not an experiment.

Success means:

- the app feels English-native and North America-ready
- the swipe deck remains the star
- recommendations feel meaningfully closer to the user's real situation
- the app supports nearby context without making location permission a blocker
- the menu scan feature feels useful and productized
- the design feels premium and food-centric without looking synthetic or AI-branded

## Recommended Implementation Order

1. English rebrand and core copy conversion
2. location and manual area foundation
3. Google Places nearby restaurant service
4. restaurant-plus-dish deck model
5. detail and explore integration
6. menu scan service and UI
7. upgrade/profile polish
8. smoke and release gate expansion

