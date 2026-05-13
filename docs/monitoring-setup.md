# Monitoring & Analytics — Setup Guide

This document covers everything needed to **activate** the Sentry + PostHog monitoring stack that ships with Teller. Without these secrets the SDKs are no-ops (safe default), so production builds with no DSN configured will silently drop telemetry.

## TL;DR

```bash
# 1. Provision projects on the providers
#    - Sentry:  https://sentry.io  -> create project (React Native)
#    - PostHog: https://app.posthog.com (or eu.posthog.com for EU)

# 2. Set EAS secrets (one-time)
eas secret:create --scope project --name EXPO_PUBLIC_SENTRY_DSN     --value "https://<...>@<...>.ingest.sentry.io/<id>"
eas secret:create --scope project --name EXPO_PUBLIC_POSTHOG_KEY    --value "phc_<...>"
eas secret:create --scope project --name EXPO_PUBLIC_POSTHOG_HOST   --value "https://eu.i.posthog.com"
eas secret:create --scope project --name EXPO_PUBLIC_APP_ENV        --value "prod"

# 3. Verify
eas secret:list --scope project

# 4. Build & deploy as usual
eas build --profile preview
```

After the first build with secrets, `app_opened` and `screen_viewed` events should land in PostHog within ~30 seconds. Sentry will start receiving crash reports immediately.

---

## What gets tracked, by default

After this PR, **without any further code changes**, every screen transition in the app fires:

1. `screen_viewed` (PostHog) with `screen_name`, `previous_screen`
2. `$screen` (PostHog's built-in screen event, used in funnel views)
3. A Sentry breadcrumb (`navigation: <prev> -> <next>`) attached to any subsequent crash

This means you can build retention/funnel views without instrumenting individual screens.

The following events are **already wired** by other PRs:

| Event | Where | Properties |
|---|---|---|
| `app_opened` | App.tsx bootstrap | — |
| `onboarding_step_completed` | OnboardingCuisines | `step`, `selected_count`, `skipped` |
| `onboarding_completed` | OnboardingRestrictions | `restriction_count`, `has_area`, `skipped` |
| `screen_viewed` | NavigationContainer | `screen_name`, `previous_screen` |

The full enum lives in [`src/monitoring/analytics.ts`](../src/monitoring/analytics.ts) — never inline-string an event name at the call site.

---

## Three environments, three DSNs

We recommend **separate Sentry projects per environment** so dev crashes don't pollute production dashboards. PostHog is fine with a single project (use the `$app_environment` property to filter).

```
Sentry projects:
  teller-mobile-dev      <- dev simulator runs (optional)
  teller-mobile-preview  <- TestFlight / EAS preview channel
  teller-mobile-prod     <- App Store / Play Store

PostHog projects:
  teller-mobile          <- single project; filter by $app_environment
```

Set per-profile DSNs in `eas.json` if you split:

```jsonc
// eas.json
{
  "build": {
    "preview": {
      "env": {
        "EXPO_PUBLIC_APP_ENV": "preview",
        "EXPO_PUBLIC_SENTRY_DSN": "${EAS_SECRET_SENTRY_DSN_PREVIEW}"
      }
    },
    "production": {
      "env": {
        "EXPO_PUBLIC_APP_ENV": "prod",
        "EXPO_PUBLIC_SENTRY_DSN": "${EAS_SECRET_SENTRY_DSN_PROD}"
      }
    }
  }
}
```

(Or the simpler alternative: single DSN for both, filter by `environment` tag — Sentry is smart enough.)

---

## EU vs US PostHog

PostHog has two clouds. Pick one **before** going live and stick with it (data does not migrate).

- **EU cloud** (`https://eu.i.posthog.com`) — recommended if you target EU users (GDPR posture is cleaner)
- **US cloud** (`https://us.i.posthog.com`) — recommended for US-only or global apps

Default in code is **EU** — override via `EXPO_PUBLIC_POSTHOG_HOST` if needed.

---

## Sentry knobs you might want

The `initSentry()` wrapper in [`src/monitoring/sentry.ts`](../src/monitoring/sentry.ts) is intentionally conservative:

| Setting | Default | Why |
|---|---|---|
| `tracesSampleRate` | 0.1 (prod), 1.0 (dev) | Cost control. Bump to 0.3 for a launch-week burst, then ratchet down. |
| `sendDefaultPii` | `false` | We attach our own anonymised user id via `setSentryUser()`. |
| `enableAutoPerformanceTracing` | `false` | Adds non-trivial JS bundle weight; turn on once you want screen timing. |
| `enableAutoSessionTracking` | `true` | Required for "crash-free users" metric. |

To opt a user out (privacy preference toggle):

```ts
import { setSentryUser, resetAnalytics } from './monitoring';
setSentryUser(null);
resetAnalytics();
```

---

## What's still missing / planned

- **`identify(userId)` on login** — currently no real auth flow uses analytics identify. Wire after Sign in with Apple (next PR).
- **Session replay** — Sentry RN now supports it; we'll opt in once we have a privacy-review process for masked recordings.
- **Funnel events for paywall + checkout** — instrumented at the call site once those screens are migrated to i18n (the touch-up is cheaper to bundle).
- **Remote config kill-switch** — `enabled` flag should come from a remote config service so we can turn off telemetry without a release. Out of scope for this PR.

---

## Privacy / compliance checklist

For App Store review and GDPR/CCPA posture:

- [ ] Add Sentry + PostHog to your **privacy policy** under "third-party analytics"
- [ ] Add to **App Store Privacy Manifest** (handled in a separate PR — see `ios/PrivacyInfo.xcprivacy`)
- [ ] Document data retention period in user-facing docs (Sentry default: 30/90 days; PostHog: 1 year on free tier)
- [ ] Provide opt-out toggle in Profile screen (TODO)

---

## Verifying after deploy

1. **Sentry test event**: in dev, throw `new Error('test sentry')` from anywhere — should appear in your Sentry project within ~30s.
2. **PostHog screen events**: navigate Home -> Explore -> Profile in TestFlight build; PostHog Live Events tab should show three `$screen` events.
3. **Crash-free rate**: should report >99.5% before public launch. Anything lower means there's an open production crash to chase.
