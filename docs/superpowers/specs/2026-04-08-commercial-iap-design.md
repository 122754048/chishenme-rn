# Commercial IAP Launch Design

## Goal

Move ChiShenMe from a technically validated demo/MVP into an iOS-commercialization-ready app by replacing iOS digital membership payments with Apple In-App Purchase subscriptions, adding entitlement sync, account deletion, privacy/compliance surfacing, and release gates that prevent accidental regression to non-compliant iOS payment flows.

## Scope

This design targets iOS App Store commercialization first. Android and Web are not part of this implementation pass. Alipay remains available only for non-iOS use cases or future Android distribution; it must not be presented as the purchase method for iOS digital Pro/Family membership.

## Commercial Model

The app sells two auto-renewable subscription tiers:

- `pro`: unlocks unlimited recommendations and premium AI food analysis for one user.
- `family`: unlocks Pro benefits plus family-oriented sharing copy and future family features.

Product identifiers are environment-driven so App Store Connect values can be supplied without code edits:

- `EXPO_PUBLIC_RC_IOS_API_KEY`
- `EXPO_PUBLIC_RC_ENTITLEMENT_ID`, default `premium`
- `EXPO_PUBLIC_RC_PRO_PRODUCT_ID`, default `chishenme.pro.monthly`
- `EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID`, default `chishenme.family.monthly`

## Architecture

The implementation uses RevenueCat's React Native SDK (`react-native-purchases`) as the client wrapper over StoreKit and RevenueCat entitlements. Expo's IAP documentation lists `react-native-purchases` as an Expo-compatible IAP option, but real native purchases require a development build rather than Expo Go.

Client subscription flow:

1. App startup configures RevenueCat on iOS when `EXPO_PUBLIC_RC_IOS_API_KEY` is present.
2. Upgrade loads offerings or customer info from RevenueCat.
3. Checkout uses RevenueCat packages/products to purchase Pro or Family.
4. Restore purchase calls RevenueCat restore and maps active entitlement to `pro` or `family`.
5. App stores the active membership plan locally for immediate UX, then syncs with backend when backend is configured.

Backend subscription flow:

1. Backend exposes membership plan and account deletion endpoints.
2. Backend supports a `subscription_source` concept, initially `local`, `alipay`, and `apple_iap`.
3. RevenueCat webhook support is added as the server-side source of truth for iOS subscription events. Webhook validation uses `REVENUECAT_WEBHOOK_SECRET`.
4. Active RevenueCat entitlement maps to `pro` or `family`; cancelled/expired/transfer events fall back to `free`.
5. `/membership/me` returns the current plan plus source metadata when available.

## Frontend Changes

Create a small subscription service layer under `src/services/subscriptions.ts` with these responsibilities:

- Detect iOS vs non-iOS behavior.
- Configure RevenueCat once per app launch.
- Fetch available packages for Pro and Family.
- Purchase the selected package.
- Restore purchases.
- Convert RevenueCat customer info to the local `free | pro | family` membership plan.
- Return user-facing error messages for unavailable store config, user cancellation, network failure, and no active restored subscription.

Update screens:

- `Upgrade.tsx`: show subscription copy that meets Apple expectations: price period, auto-renewal, cancel in Apple ID settings, restore purchase action.
- `Checkout.tsx`: on iOS, use IAP purchase/restore instead of Alipay order creation. On non-iOS or when IAP is unavailable, fail closed with a clear message unless explicit development mock mode is enabled.
- `Profile.tsx`: add "恢复购买" and "删除账号" user actions. Account deletion must be easy to find in account settings and must initiate deletion of automatically generated guest accounts.
- `AppContext.tsx`: sync subscription plan from RevenueCat on startup/app resume before using local cached membership, then persist the resolved plan.

## Backend Changes

Add account deletion:

- `DELETE /account/me` deletes the authenticated user, subscription row, quotas, orders, and idempotency records where legally safe for this project.
- Deletion returns a simple confirmation payload and invalidates app-local auth state on the client.

Add RevenueCat webhook:

- `POST /billing/revenuecat/webhook`
- Requires `Authorization: Bearer <REVENUECAT_WEBHOOK_SECRET>` or an equivalent shared secret header.
- Parses RevenueCat app user id, entitlement id, product id, and event type.
- Maps configured RevenueCat product ids to `pro` / `family`.
- Stores the resulting subscription source as `apple_iap`.
- Ignores unknown products safely and returns a 2xx response for non-actionable events after logging enough context for QA.

## Compliance Gates

Update release checks so production iOS builds cannot accidentally ship an external digital-membership payment path:

- Fail if Checkout exposes Alipay as the primary iOS purchase path.
- Fail if `react-native-purchases` is missing.
- Fail if subscription config references are missing from the IAP service.
- Fail if the Profile account deletion entry is missing.
- Keep the existing payment mock gate: production must not set `EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS=true`.

Update `RELEASE_READINESS_REPORT_2026-04-08.md` with:

- IAP implementation status.
- Required App Store Connect setup.
- Required RevenueCat setup.
- Required privacy policy and support URL values.
- TestFlight and StoreKit sandbox checks that still require a real Apple developer account.

## Testing

Automated tests:

- `npm run lint`
- `npm test`
- Backend unittest discovery from `backend`
- `npx expo-doctor`
- `npm audit --omit=dev`
- `git diff --check`

New frontend smoke assertions:

- IAP service exists and imports RevenueCat SDK.
- Upgrade/Checkout include restore purchase flow.
- iOS Checkout does not use Alipay as the purchase path.
- Profile includes account deletion entry.

New backend tests:

- RevenueCat webhook activates Pro plan.
- RevenueCat webhook activates Family plan.
- RevenueCat expiration/cancellation returns user to Free.
- Webhook rejects missing/invalid secret.
- Account deletion removes authenticated user data and subsequent membership lookup fails.

Manual release checks that cannot be fully automated here:

- Create App Store Connect auto-renewable subscriptions for Pro and Family.
- Configure RevenueCat project, entitlement, products, App Store Connect API key, and webhook URL.
- Build a development/TestFlight iOS binary; Expo Go is not sufficient for real native purchases.
- Run StoreKit sandbox purchase, restore, cancel/expire simulation, and app resume entitlement sync.
- Verify App Store privacy nutrition labels and privacy policy URL match actual data collection.

## Risks

- RevenueCat account/configuration is external and cannot be completed solely in code.
- Real StoreKit purchases require a development build or TestFlight build, not Expo Go.
- Until App Store Connect product IDs and RevenueCat entitlement IDs are created, the app can only be code-ready, not commercially live.
- The current backend remains single-instance SQLite. This is acceptable for low-volume launch validation, but a commercial scale-up should migrate to PostgreSQL and centralized audit logs.

## Acceptance Criteria

- iOS digital membership purchases use Apple IAP through RevenueCat.
- Restore purchase exists and updates membership state.
- Account deletion can be initiated from Profile and deletes generated account data.
- Production release checks fail if iOS membership purchase falls back to Alipay or mock payments.
- All automated checks pass.
- The report clearly separates code-ready status from external App Store Connect/RevenueCat/TestFlight tasks.
