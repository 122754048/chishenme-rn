# Release Readiness Report - 2026-04-08

## Verdict

The repository is now code-ready for the next iOS commercial launch gate from the automated-check perspective.

The previous blocker, Alipay notification authentication by shared token, has been replaced with RSA2 public-key verification over the original JSON/form notification parameters before membership activation.

The QA regression pass also found and fixed frontend release risks in the Expo dependency graph and checkout flow.

The latest user-experience pass is scoped to iOS/mobile release readiness. Expo Web remains outside the current launch scope; `npm run web` currently requires adding `react-dom` and `react-native-web` if Web/H5 delivery becomes required.

The commercial monetization path now uses Apple IAP through RevenueCat on iOS. The app is still not commercially live until App Store Connect subscription products, RevenueCat project configuration, webhook URL, TestFlight/StoreKit sandbox verification, privacy policy URL, and support URL are completed outside this repository.

## Completed Remediation

- Replaced token-based Alipay notify authentication with RSA2 signature verification.
- Preserved raw notification parameter strings during verification, including form submissions such as `total_amount=9.90`.
- Added app ID and RSA2 sign type validation before marking orders as paid.
- Switched password storage from unsalted SHA-256 to salted PBKDF2-SHA256, while retaining legacy SHA-256 verification for migration safety.
- Fixed backend DB path handling so tests and runtime do not depend on the current working directory.
- Added production runtime checks for placeholder `JWT_SECRET`, `ALIPAY_APP_ID`, and `ALIPAY_PUBLIC_KEY`.
- Cleared the npm production audit finding by updating `@xmldom/xmldom` in `package-lock.json`.
- Expanded release-check gates so lint fails if the backend regresses to `ALIPAY_NOTIFY_TOKEN` or loses RSA2 verification.
- Fixed Expo SDK 54 dependency mismatches by installing `react-native-worklets`, aligning `expo-font`, `react-native-svg`, and `babel-preset-expo`, and adding the Expo font config plugin.
- Locked local mock payment/trial membership activation behind `EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS=true`; checkout now fails closed when neither backend payments nor explicit mock payments are configured.
- Added payment regression coverage for wrong Alipay app ID, amount mismatch, unpaid trade statuses, and cross-user order access.
- Localized bottom-tab labels and loading copy for the Chinese mobile product experience.
- Bounded the Home swipe-card height by active device dimensions so small iPhone screens keep the action row usable.
- Replaced the Home shortcut icon that looked like a filter with a discovery icon, matching its route to the Explore screen.
- Added accessibility labels, selected/disabled states, and larger hit areas across onboarding, search, Home actions, upgrade, checkout, and profile entry points.
- Added bottom safe-area coverage and extra scroll padding for onboarding, upgrade, and checkout fixed-footers.
- Improved checkout failure and pending-payment copy so users see whether payment service configuration, order failure, or pending Alipay completion is the issue.
- Turned Profile preference, payment method, and help rows into explicit actions/feedback instead of dead tap targets.
- Added smoke-test assertions for the iOS UX polish gates above.
- Added RevenueCat `react-native-purchases` and a focused subscription service for iOS Apple IAP purchase, restore, and entitlement sync.
- Added a stable local app user ID for RevenueCat purchases, restore purchase, and backend webhook entitlement mapping.
- Tightened iOS checkout so a configured backend must prepare the account token before purchase, avoiding successful purchases that cannot map back to a backend account.
- Changed iOS checkout so digital membership purchase routes through Apple IAP before any backend/Alipay order path.
- Added restore purchase entry points in Checkout, Upgrade, and Profile.
- Added Profile account deletion flow and backend `DELETE /account/me`, including a user-facing reminder that deleting the app account does not automatically cancel Apple ID subscriptions.
- Added backend RevenueCat webhook endpoint for Apple IAP entitlement sync, with secret validation and Pro/Family/Free plan mapping.
- Preserved already-synced RevenueCat entitlements if a webhook reaches the backend before the user registration request completes.
- Added subscription `source`, `product_id`, and `expires_at` storage metadata.
- Updated backend membership responses to include subscription source metadata.
- Added release gates that require `react-native-purchases`, RevenueCat env references, iOS IAP routing, restore purchase, account deletion, and a non-anonymous iOS bundle identifier.
- Updated iOS bundle identifier to `com.chishenme.app`.
- Updated backend README production notes and test command.

## Verification

- PASS: `npm run lint`
- PASS: `npm test`
- PASS: `npm audit --omit=dev`
- PASS: `npx expo-doctor`
- PASS: `cd backend && python -m unittest discover -s tests -v`
- PASS: `git diff --check` (only CRLF conversion warnings from Git on Windows)
- PASS: isolated backend virtualenv install, `unittest discover`, and `pip check` using a temporary `.qa-venv` that was removed after QA.

## Production Configuration Required

Set real environment values before deployment:

- `APP_ENV=production`
- `JWT_SECRET` with a high-entropy secret
- `ALIPAY_APP_ID` from the Alipay application
- `ALIPAY_PUBLIC_KEY` from Alipay, PEM formatted or compact public-key body
- `REVENUECAT_WEBHOOK_SECRET` for RevenueCat webhook validation
- `REVENUECAT_ENTITLEMENT_ID` matching the RevenueCat entitlement, default expected: `premium`
- `REVENUECAT_PRO_PRODUCT_ID` matching App Store Connect and RevenueCat Pro monthly subscription
- `REVENUECAT_FAMILY_PRODUCT_ID` matching App Store Connect and RevenueCat Family monthly subscription
- `DB_PATH` pointing to the deployment database path if not using the default single-instance SQLite file
- `EXPO_PUBLIC_API_BASE_URL` pointing at the production backend
- `EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD` until the temporary bootstrap auth flow is replaced
- `EXPO_PUBLIC_RC_IOS_API_KEY` from RevenueCat
- `EXPO_PUBLIC_RC_ENTITLEMENT_ID` matching the RevenueCat entitlement
- `EXPO_PUBLIC_RC_PRO_PRODUCT_ID` matching the Pro App Store product
- `EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID` matching the Family App Store product
- Do not set `EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS=true` in production builds.

## External Commercial Launch Tasks

- Create App Store Connect auto-renewable subscriptions for Pro and Family under the production bundle identifier `com.chishenme.app`.
- Configure RevenueCat project, iOS API key, entitlement, products, App Store Connect API key, and backend webhook URL.
- Add production Privacy Policy URL and Support URL in App Store Connect.
- Fill App Store privacy nutrition labels to match actual data collection: backend user id, purchase/subscription status, favorites/history/preferences stored by the app, and any analytics added later.
- Build an iOS development/TestFlight binary; Expo Go is not sufficient for native IAP testing.
- Run StoreKit/TestFlight sandbox purchase, restore purchase, cancel/expiration, app resume entitlement sync, and RevenueCat webhook entitlement sync.
- Confirm mock payments are disabled in production.

## Operational Follow-Up

The current backend remains scoped to a single-instance deployment profile. Before running multiple backend instances or handling higher payment volume, move SQLite/idempotency storage to PostgreSQL plus a distributed lock/idempotency store, add reconciliation jobs, and add centralized audit logging and secret rotation.
