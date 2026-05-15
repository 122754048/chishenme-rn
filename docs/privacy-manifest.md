# Privacy Manifest (iOS)

App Store **mandates** a privacy manifest for all apps as of May 1, 2024 (and SDK-level manifests since Spring 2024). This file explains every declaration in `app.json` → `ios.privacyManifests`.

## How it ships

We are an **Expo managed workflow** project. The `privacyManifests` block in `app.json` is consumed by Expo prebuild / EAS Build and rendered into `ios/PrivacyInfo.xcprivacy` automatically.

To verify locally:

```bash
npx expo prebuild --platform ios --clean
cat ios/Teller/PrivacyInfo.xcprivacy
```

Do **not** hand-edit `ios/PrivacyInfo.xcprivacy` — it is regenerated each prebuild.

## NSPrivacyAccessedAPITypes (Required-Reason APIs)

| API category | Reason code | Why we use it |
|---|---|---|
| `UserDefaults` | `CA92.1` | AsyncStorage (`@react-native-async-storage/async-storage`) backs onboarding state, favorites, history, and i18n preference. CA92.1 = "access info from same app, per documentation". |
| `FileTimestamp` | `C617.1` | `expo-file-system` reads `modificationTime` for the photos picked from the user's library when scanning a menu. C617.1 = "display file timestamps to the person using the device". |
| `DiskSpace` | `E174.1` | `expo-file-system.getFreeDiskStorageAsync()` is called before menu-scan upload to fail fast on full disks. E174.1 = "write or delete file on device". |
| `SystemBootTime` | `35F9.1` | Reanimated / Sentry use `mach_absolute_time`-derived timestamps internally. 35F9.1 = "measure elapsed time within the app". |

> Apple ref: <https://developer.apple.com/documentation/bundleresources/privacy_manifest_files/describing_use_of_required_reason_api>

## NSPrivacyCollectedDataTypes

Each entry must be: type + linked-to-identity? + used-for-tracking? + purposes.

| Data type | Linked | Tracking | Purposes | Notes |
|---|---|---|---|---|
| `PreciseLocation` | NO | NO | AppFunctionality | `expo-location` `Accuracy.High` — used to compute distance to restaurants on-device. Not sent to backend. |
| `CoarseLocation` | NO | NO | AppFunctionality | Fallback when precise is denied. Same scope. |
| `CrashData` | NO | NO | AppFunctionality, Analytics | Sentry crash reports. We **do not** call `Sentry.setUser(email)`, so it stays unlinked. |
| `PerformanceData` | NO | NO | Analytics | Sentry tracing + PostHog `$performance` events. |
| `ProductInteraction` | NO | NO | Analytics, AppFunctionality | PostHog screen views, paywall events, checkout funnel events. We use anonymous device IDs, no PII. |
| `EmailAddress` | YES | NO | AppFunctionality | Stored on backend `users.email` for account-based login + RevenueCat user mapping. |
| `UserID` | YES | NO | AppFunctionality, Analytics | Backend user UUID + RevenueCat / PostHog distinct ID linked after sign-in. |
| `PurchaseHistory` | YES | NO | AppFunctionality | Subscription plan + checkout history (Pro / Family). RevenueCat-managed. |

**Tracking flag global:** `NSPrivacyTracking: false` — we do not track users across other apps/websites for ad targeting.

## What's NOT collected

- **Health & Fitness, Financial Info, Sensitive Info, Browsing History, Audio, Video, Photo content, Customer Support, Other Diagnostic Data, Other Usage Data, Other Data Types** — none collected.
- **Contact list, Search history, Messages** — not accessed.

## When to update this file

You **must** update both `app.json` and this doc when:

1. Adding any third-party SDK that collects new data types
2. Calling `Sentry.setUser()` with PII → flip `CrashData.linked = true`
3. Adding email/password sign-in for marketing emails → add purpose `Analytics` for email
4. Adding "Sign in with Apple" → no manifest change (Apple-provided identifier replaces email when user opts to hide email)
5. Adding `react-native-track-player` or any audio / contacts / health module → re-audit with the SDK's own manifest

## SDK Privacy Manifests

Each third-party SDK on Apple's "commonly-used SDKs" list **must** ship its own manifest. Verify at build time:

```bash
# After `npx expo prebuild`:
find ios/Pods -name "PrivacyInfo.xcprivacy" -exec dirname {} \; | sort -u
```

Required SDKs we ship that need manifests (Apple's list as of 2024):

- `RevenueCat` — bundled
- `Sentry` — bundled
- `PostHog` — bundled (since 2.x)
- `react-native-async-storage` — bundled
- `expo-file-system` — bundled
- `expo-location` — bundled

If `npx expo prebuild` warns about missing SDK manifests, **block the release** until upstream fixes.

## App Store Connect: Privacy Questionnaire

The manifest **does not** replace the App Store Connect privacy questionnaire — both must agree. Set the following in App Store Connect → App Privacy:

- **Data Collected:** Location (Precise + Coarse), Crash Data, Performance Data, Product Interaction, Email, User ID, Purchase History
- **Data Used to Track You:** None (NSPrivacyTracking = false)
- **Data Linked to You:** Email, User ID, Purchase History
- **Data Not Linked:** Location (both), Crash Data, Performance Data, Product Interaction
