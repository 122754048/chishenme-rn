# i18n migration tracker

This file is the source of truth for which screens have been migrated to react-i18next.

## Status

| Screen / surface | Status | Notes |
|---|---|---|
| OnboardingCuisines | ✅ migrated | hero eyebrow uses title key as fallback until brand voice is locked |
| OnboardingRestrictions | ✅ migrated | full migration |
| Profile | ✅ migrated | full migration; restore/delete/billing alerts use t() |
| Upgrade (paywall) | ✅ migrated | full migration; emits paywall_viewed, paywall_plan_selected, checkout_started events |
| Checkout | ✅ migrated | full migration; emits checkout_started/completed/failed funnel events with billingCycle dimension |
| Home | ⏳ pending | ~118 strings; biggest, do last after locale catalogue is stable |
| Explore | ⏳ pending | ~65 strings |
| Favorites | ⏳ pending | already calls `<EmptyState language="en" />` — promote to active locale |
| History | ⏳ pending | same as Favorites |
| Detail | ⏳ pending | |
| MenuScan | ⏳ pending | |
| DeveloperMode | ❌ skipped | dev-only, not user-visible in production |
| Components (EmptyState, Toast, etc.) | partial | EmptyState ships own `language` prop; consumer should pass `i18n.language` |

## Locale catalogue scope

Currently shipped keys (per locale, identical schema):

- `common.*` — buttons & generic chrome
- `tabs.*` — bottom-tab labels
- `onboarding.cuisines.*`, `onboarding.restrictions.*` — both onboarding screens
- `home.*` — feed shell + quota messaging (not yet wired)
- `explore.*`, `favorites.*`, `history.*`, `profile.*` — surface-level keys (unwired)
- `upgrade.*`, `checkout.*` — paywall + checkout keys (unwired)
- `errors.*` — generic error states

## Conventions

1. **Keys are dot-paths** scoped by surface: `screen.feature.role` (e.g. `home.quotaUpgradeCta`).
2. **Plural keys end in `_one` / `_other`**; never hand-write `${count} pick(s)`.
3. **Never inline raw strings** in JSX. Even one-word labels must come from `t()`.
4. **Accessibility labels are user-facing** — also localised, not hardcoded.
5. **Keep keys flat per surface** (max 2 levels of nesting). Deep trees hurt translator UX.
6. **Add the key to all 4 locales (`en`, `zh`, `es`, `ja`) in the same commit.** A missing key in one locale silently falls back to English, which masks real translation gaps.
7. **No string concat with translated parts** — use interpolation: `t('foo.bar', { name })`.

## How to migrate a screen

```tsx
// 1. Add hook
import { useTranslation } from 'react-i18next';
const { t } = useTranslation();

// 2. Replace hardcoded text
- <Text>Continue</Text>
+ <Text>{t('common.continue')}</Text>

// 3. Replace plural strings (count is the magic param name)
- <Text>{count} picks left today</Text>
+ <Text>{t('home.quotaRemaining', { count })}</Text>

// 4. Localise accessibility labels too
- accessibilityLabel="Skip for now"
+ accessibilityLabel={t('onboarding.cuisines.skip')}
```

## Adding a new locale

1. Copy `src/i18n/locales/en.json` → `src/i18n/locales/<code>.json`
2. Add `<code>` to `SUPPORTED_LANGUAGES` in `src/i18n/index.ts`
3. Add `<code>: { translation: <code> }` to the `resources` map
4. Test by overriding device language in iOS simulator settings

## Pending work / debt

- Hero strings in OnboardingCuisines (`heroEyebrow`/`heroSummary`) currently reuse `title`/`subtitle` keys — extract dedicated keys once brand voice is decided.
- The selected count "X picked so far" is gone in EN copy — restore as a separate key with proper plural support before the next PR.
- Profile screen has a `Language` row that needs to wire `setLanguage()` from `src/i18n` once migrated.
- Locale-aware date/number formatting (`Intl.DateTimeFormat`, `Intl.NumberFormat`) not yet wired into History timestamps.
