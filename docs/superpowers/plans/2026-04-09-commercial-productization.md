# Commercial Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current food-swipe demo into a commercial-feeling iOS product by making recommendations preference-aware, delaying monetization until after first value, and converting detail/upgrade flows into decision and subscription tools.

**Architecture:** Keep the current Expo + React Native app structure, but enrich local food data, centralize recommendation logic in shared utilities, and rework screen composition around a recommendation-led journey. Avoid backend expansion unless needed for existing membership and subscription continuity.

**Tech Stack:** Expo 54, React Native, TypeScript, React Navigation, AsyncStorage, existing Apple IAP / RevenueCat integration, Node-based smoke gates.

---

### Task 1: Build Product Data And Recommendation Utilities

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\data\mockData.ts`
- Create: `C:\Users\zhaocx04\Documents\New project\src\utils\recommendations.ts`
- Test: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`

- [ ] **Step 1: Add richer food metadata**

Add fields for decision-oriented recommendation logic: `mealType`, `budgetBand`, `decisionTags`, `restrictionConflicts`, `healthTags`, `fitMoments`, `groupFit`, `speedScore`, `comfortScore`, `premiumScore`.

- [ ] **Step 2: Create shared recommendation helpers**

Implement utilities that:
- normalize onboarding preferences into product-facing signals
- score dishes using cuisines, restrictions, price, moments, and health tags
- generate 2-3 user-facing recommendation reasons
- produce related alternatives for detail and explore surfaces

- [ ] **Step 3: Add smoke assertions**

Update smoke checks so they require:
- recommendation explanation logic
- richer mock data fields
- home to use recommendation utilities instead of static raw ordering

- [ ] **Step 4: Run tests**

Run:
- `npm test`

- [ ] **Step 5: Commit**

Commit message:
- `feat: add product recommendation scoring`

### Task 2: Remove Forced Monetization From Onboarding

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\OnboardingRestrictions.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\components\OnboardingGuide.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`

- [ ] **Step 1: Route onboarding into Home**

After restrictions, complete onboarding and send users into `MainTabs` instead of pushing upgrade.

- [ ] **Step 2: Align first-use guidance with real interactions**

Update the onboarding guide so it only teaches supported gestures and actions.

- [ ] **Step 3: Add regression assertions**

Require smoke tests to confirm onboarding does not hard-route to upgrade and guide text matches actual capabilities.

- [ ] **Step 4: Run tests**

Run:
- `npm test`

- [ ] **Step 5: Commit**

Commit message:
- `feat: move paywall after first recommendation value`

### Task 3: Rebuild Home Into A Decision Surface

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Home.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\context\AppContext.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\navigation\AppNavigator.tsx`
- Test: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`

- [ ] **Step 1: Feed Home from recommendation scoring**

Replace static index-based browsing with scored recommendation ordering that reacts to cuisines and restrictions.

- [ ] **Step 2: Add “why recommended” and context framing**

Expose clear recommendation reasons and lightweight context chips on the home card.

- [ ] **Step 3: Reframe CTA meanings**

Keep quick actions, but rename and present them around decision outcomes such as skip, save, choose.

- [ ] **Step 4: Improve low-quota monetization copy**

Upgrade prompts should sell better decision support, not only unlimited count.

- [ ] **Step 5: Update loading / brand presentation**

Reduce emoji dependence in structural product UI where feasible without rebranding the whole app.

- [ ] **Step 6: Run tests**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 7: Commit**

Commit message:
- `feat: make home a recommendation decision surface`

### Task 4: Turn Detail Into A Decision Assistant

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Detail.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\utils\recommendations.ts`
- Test: `C:\Users\zhaocx04\Documents\New project\scripts\smoke-test.js`

- [ ] **Step 1: Replace faux-transaction framing**

Remove unsupported real-world purchase cues such as “estimated total price” when the app is not actually transacting meals.

- [ ] **Step 2: Add recommendation summary sections**

Show:
- why this fits you
- restriction compatibility
- time / budget / nutrition snapshot
- similar alternatives

- [ ] **Step 3: Add a real decision CTA**

Use a primary CTA like “今天吃这个” or equivalent save/decide action tied to current app capabilities.

- [ ] **Step 4: Update smoke coverage**

Require that detail no longer implies unsupported commerce and includes recommendation-decision framing.

- [ ] **Step 5: Run tests**

Run:
- `npm run lint`
- `npm test`

- [ ] **Step 6: Commit**

Commit message:
- `feat: turn detail into a decision assistant`

### Task 5: Improve Explore And Upgrade For Commercial Positioning

**Files:**
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Explore.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Upgrade.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\src\screens\Profile.tsx`
- Modify: `C:\Users\zhaocx04\Documents\New project\scripts\release-check.js`
- Modify: `C:\Users\zhaocx04\Documents\New project\RELEASE_READINESS_REPORT_2026-04-08.md`

- [ ] **Step 1: Make explore more intent-driven**

Use scenario-driven grouping and stronger relevance around meal type, diet fit, and budget.

- [ ] **Step 2: Rewrite upgrade around premium outcomes**

Reframe plans as:
- free = basic meal help
- pro = sharper decisions and deeper insight
- family = multi-person meal coordination

- [ ] **Step 3: Align profile language**

Make profile plan language, saved content, and family positioning consistent with the new commercial product story.

- [ ] **Step 4: Update release gates and readiness report**

Reflect the new productization gates in smoke / release checks and the release report.

- [ ] **Step 5: Run full validation**

Run:
- `npm run lint`
- `npm test`
- `cd backend && python -m unittest discover -s tests -v`

- [ ] **Step 6: Commit**

Commit message:
- `feat: commercialize recommendation and upgrade journeys`
