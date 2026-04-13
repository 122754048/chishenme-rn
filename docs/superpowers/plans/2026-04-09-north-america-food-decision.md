# North America Food Decision Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing swipe-based iOS app into a North America-ready commercial food decision product with English copy, nearby restaurant context, Google restaurant trust signals, and menu scan dish recommendations while keeping the current app structure intact.

**Architecture:** Extend the existing Expo + React Native app in place. Preserve the current onboarding, tab structure, swipe home screen, detail flow, upgrade flow, and storage model, but add location-aware restaurant context, a Places integration layer, menu scan services, and English-first product copy. Keep recommendation ranking centralized in shared utilities and avoid rewriting the backend except where new config or API boundaries are required.

**Tech Stack:** Expo 54, React Native, TypeScript, React Navigation, AsyncStorage, existing RevenueCat/Apple IAP integration, Google Places Web Service, Expo Location, Expo ImagePicker, Node-based smoke/release gates.

---

### Task 1: Lay The Foundation For North America Launch

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\package.json`
- Modify: `C:\Users\zhaocx04\Documents\New project\app.json`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\navigation\types.ts`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\navigation\AppNavigator.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\storage\index.ts`
- Create: `C:\Users\zhaocx04\Documents\New project\src\config\brand.ts`
- Create: `C:\Users\zhaocx04\Documents\New project\src\utils\location.ts`
- Test: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`
- Test: `C:\Users\zhaocx04\Documents\New project\scripts\release-check.js`

- [ ] **Step 1: Add native dependencies for location and image import**

Update `package.json` to include `expo-location` and `expo-image-picker`. Update `app.json` with English product name, iOS location permissions copy, and photo library / camera usage descriptions appropriate for a North America consumer app.

- [ ] **Step 2: Add centralized brand configuration**

Create `src/config/brand.ts` to hold:
- the new working brand name
- key English UI strings for the shell
- premium warm accent palette values that can be reused without hardcoding scattered copy and colors

- [ ] **Step 3: Extend navigation types for the new flows**

Update `src/navigation/types.ts` so the app can route to:
- a restaurant-aware detail state
- a location/area search helper route if needed
- a menu scan route or modal surface input

- [ ] **Step 4: Add location persistence helpers**

Extend `src/storage/index.ts` and `src/utils/location.ts` to support:
- current location payloads
- manually entered area/address
- saved contexts like `home` and `work`
- graceful fallback when location is missing

- [ ] **Step 5: Update shell branding**

Update the app shell in `src/navigation/AppNavigator.tsx` to use the new English brand and remove any remaining Chinese-first or placeholder presentation in loading/title shell UI.

- [ ] **Step 6: Add foundation smoke gates**

Update smoke/release checks so they require:
- English product shell text
- location usage descriptions in config
- new dependencies for location/image import
- no Chinese tab labels in the primary app shell

- [ ] **Step 7: Run validation**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 8: Commit**

Commit message:
- `feat: add north america app foundation`

### Task 2: Add Nearby Restaurant Data And Recommendation Inputs

**Files:**
- Create: `C:\Users\zhaocx04\Documents\New project\src\services\places.ts`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\data\mockData.ts`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\utils\recommendations.ts`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\context\AppContext.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\release-check.js`

- [ ] **Step 1: Define restaurant-aware card models**

Refactor `src/data/mockData.ts` so the recommendation layer can work with:
- restaurant identity
- nearby distance
- signature dish
- Google-style rating/review metadata
- dietary fit markers
- restaurant image + dish image fallbacks

Keep mock fallback data available so the app still runs when Places is unavailable.

- [ ] **Step 2: Create the Google Places service boundary**

Implement `src/services/places.ts` with:
- typed request/response transforms
- nearby restaurant fetch by coordinates
- area/address search fallback
- normalized rating/review fields
- clear handling for no results and partial restaurant fields

This file should isolate external API details from screens.

- [ ] **Step 3: Extend recommendation scoring**

Update `src/utils/recommendations.ts` so scores account for:
- cuisine preferences
- dietary restrictions
- meal time
- mood/state filters
- distance and area relevance
- rating confidence
- repeat avoidance

Recommendation results should continue to return short human-readable reasons.

- [ ] **Step 4: Add location + area state to app context**

Update `src/context/AppContext.tsx` so the app can load/store:
- current location
- manual area selection
- saved area presets
- current mood filter state if the deck needs it globally

Keep subscriptions, quota, and account behaviors intact.

- [ ] **Step 5: Expand test gates for Places and ranking**

Require smoke/release checks to confirm:
- Places service exists
- recommendation utilities reference location-aware ranking
- fallback mock content remains available
- no regression to static dish-only recommendation assumptions

- [ ] **Step 6: Run validation**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 7: Commit**

Commit message:
- `feat: add nearby restaurant recommendation services`

### Task 3: Upgrade Home Into Restaurant Plus Signature Dish Swipe Cards

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Home.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\components\OnboardingGuide.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\theme\index.ts` (or related theme entry if needed)
- Test: `C:\Users\\zhaocx04\\Documents\\New project\\scripts\\smoke-test.js`

- [ ] **Step 1: Preserve the swipe deck structure**

Keep the current swipe interaction and action layout, but change card content to:
- restaurant name
- recommended signature dish
- why it fits now
- distance / quick travel cue
- Google rating and review count
- dietary fit or caution badge

- [ ] **Step 2: Add lightweight decision filters**

Add a compact horizontal filter bar for:
- Quick
- Comfort
- Healthy
- Budget
- Treat

This should influence ranking, not replace the core deck.

- [ ] **Step 3: Add location context without clutter**

Expose:
- current area label
- easy area switch
- graceful fallback if location is unavailable

This must feel native and quiet, not like a map app.

- [ ] **Step 4: Rewrite Home copy in English**

Replace all Chinese and demo-style text with North America-ready English copy using the approved calm, premium, human tone.

- [ ] **Step 5: Tune visual polish**

Adjust spacing, hierarchy, chips, and CTA styling so the screen feels like a premium food app:
- warm but restrained accents
- realistic food-first cards
- no AI-style decorative chrome

- [ ] **Step 6: Update first-use guidance**

Update `src/components/OnboardingGuide.tsx` so the overlay explains the new restaurant-plus-dish card model in English and matches the supported interactions.

- [ ] **Step 7: Run validation**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 8: Commit**

Commit message:
- `feat: upgrade home to nearby restaurant decision cards`

### Task 4: Make Detail And Explore Support Real Nearby Decisions

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Detail.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Explore.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\OnboardingCuisines.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\OnboardingRestrictions.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Profile.tsx`
- Test: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`

- [ ] **Step 1: Add area and lifestyle relevance to onboarding**

Keep onboarding short, but adapt it to North America by:
- converting copy to English
- capturing optional Home/Work area context
- preserving cuisine and dietary onboarding as the main identity inputs

- [ ] **Step 2: Upgrade the detail page**

Detail should now explain:
- why this restaurant and dish fit now
- restaurant trust signals
- dietary compatibility
- best alternatives from the same restaurant
- menu scan entry point

Do not convert the screen into a marketplace or ordering page.

- [ ] **Step 3: Reposition Explore as a fallback and browse tool**

Use Explore for:
- manual neighborhood/address search
- broader restaurant browse when location is denied
- searching around current preferences

It should support the home deck, not compete with it.

- [ ] **Step 4: Align profile with saved context**

Update Profile so users can:
- review or edit taste profile
- manage area context
- understand Pro value in English
- keep restore purchase and deletion flows

- [ ] **Step 5: Expand smoke coverage**

Require checks for:
- English onboarding copy
- area/location support
- menu scan entry visibility
- restaurant-first detail framing

- [ ] **Step 6: Run validation**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 7: Commit**

Commit message:
- `feat: align onboarding detail and explore with nearby dining`

### Task 5: Add Menu Scan For Photo And Screenshot Flows

**Files:**
- Create: `C:\Users\zhaocx04\Documents\New project\src\services\menuScan.ts`
- Create: `C:\Users\zhaocx04\Documents\New project\src\screens\MenuScan.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\navigation\types.ts`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Detail.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Home.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\release-check.js`

- [ ] **Step 1: Create the menu scan service boundary**

Implement `src/services/menuScan.ts` with:
- image input abstraction
- AI extraction request/response transform
- normalized menu item structure
- dietary conflict inference hooks
- recommendation ranking hooks

The service should support both:
- camera photo input
- screenshot/library input

- [ ] **Step 2: Create a lightweight menu scan UI**

Build `src/screens/MenuScan.tsx` or an equivalent focused surface that:
- presents the two input choices
- shows loading and extraction states
- renders Best for you / Safe picks / Avoid
- keeps the visual language premium and simple

- [ ] **Step 3: Hook menu scan into the existing app**

Add entry points from:
- restaurant detail
- optionally the home deck secondary actions

Do not make menu scan the main navigation identity.

- [ ] **Step 4: Add environment and release gates**

Ensure release checks cover:
- menu scan service presence
- image import dependency
- route wiring
- user-facing fallback behavior when extraction is unavailable

- [ ] **Step 5: Run validation**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 6: Commit**

Commit message:
- `feat: add menu scan recommendations`

### Task 6: Reframe Monetization And Finish Launch Gates

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Upgrade.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Checkout.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\RELEASE_READINESS_REPORT_2026-04-08.md`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\release-check.js`

- [ ] **Step 1: Reframe premium value**

Update Upgrade and Checkout to sell:
- stronger nearby ranking
- menu scan dish recommendations
- better dietary filtering
- better confidence in daily decisions

Do not fall back to quota-only messaging.

- [ ] **Step 2: Improve trust and subscription clarity**

Ensure Checkout clearly explains:
- what the user is buying
- restore purchase
- subscription management expectations
- graceful fallback when services are unavailable

- [ ] **Step 3: Update release documentation**

Revise the release readiness report to include:
- North America localization
- Google Places dependency
- location permissions behavior
- menu scan dependency and limitations
- launch blockers still outside the repo

- [ ] **Step 4: Run full validation**

Run:
- `npm run lint`
- `npm test`
- `cd backend && python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

Commit message:
- `feat: finalize monetization and launch gates for north america app`

