# Commercial IAP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the iOS app code-ready for App Store compliant subscription monetization through Apple IAP via RevenueCat.

**Architecture:** Add a focused client subscription service around `react-native-purchases`, route iOS checkout through that service, and keep Alipay out of iOS digital membership purchases. Add backend account deletion and RevenueCat webhook endpoints so subscription entitlements and deletion requests have server-side lifecycle coverage.

**Tech Stack:** Expo SDK 54, React Native 0.81, RevenueCat `react-native-purchases`, FastAPI, SQLite, Node smoke/release checks.

---

### Task 1: Add RevenueCat Client Dependency

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`

- [ ] **Step 1: Install SDK**

Run: `npm install react-native-purchases`

Expected: `react-native-purchases` appears under `dependencies`; lockfile updates.

- [ ] **Step 2: Verify Expo health**

Run: `npx expo-doctor`

Expected: `17/17 checks passed`.

### Task 2: Add Subscription Service

**Files:**
- Create: `src/services/subscriptions.ts`
- Modify: `scripts/smoke-test.js`

- [ ] **Step 1: Implement service**

Create a service exporting:

```ts
export type MembershipPlan = 'free' | 'pro' | 'family';
export type PurchaseResult = { plan: MembershipPlan; message: string };

export const subscriptionService = {
  configure(appUserId?: string): Promise<void>,
  syncCustomerPlan(appUserId?: string): Promise<MembershipPlan | null>,
  purchase(plan: 'pro' | 'family', appUserId?: string): Promise<PurchaseResult>,
  restore(appUserId?: string): Promise<PurchaseResult>,
  isIapAvailable(): boolean,
};
```

The service must import `react-native-purchases`, use iOS only for real purchases, read `EXPO_PUBLIC_RC_IOS_API_KEY`, `EXPO_PUBLIC_RC_ENTITLEMENT_ID`, `EXPO_PUBLIC_RC_PRO_PRODUCT_ID`, and `EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID`, and return clear user-facing errors when IAP is not configured.

- [ ] **Step 2: Add smoke assertions**

Extend `scripts/smoke-test.js` to assert that the service imports `react-native-purchases`, exposes `restore`, and uses `EXPO_PUBLIC_RC_IOS_API_KEY`.

- [ ] **Step 3: Verify**

Run: `npm run lint` and `npm test`.

Expected: both pass.

### Task 3: Route Checkout Through IAP

**Files:**
- Modify: `src/screens/Checkout.tsx`
- Modify: `src/screens/Upgrade.tsx`
- Modify: `scripts/release-check.js`
- Modify: `scripts/smoke-test.js`

- [ ] **Step 1: Update UI copy**

`Upgrade.tsx` must show Apple subscription copy: auto-renewal, Apple ID settings cancellation, and restore purchase.

- [ ] **Step 2: Implement purchase and restore**

`Checkout.tsx` must call `subscriptionService.purchase(plan)` for iOS IAP and `subscriptionService.restore()` for restore purchase. Alipay create-order stays only in the non-iOS explicit fallback path; production iOS digital purchase must not call `backendApi.createOrder`.

- [ ] **Step 3: Strengthen gates**

`scripts/release-check.js` must fail if `Checkout.tsx` lacks `subscriptionService.purchase` or if `react-native-purchases` is missing from `package.json`.

- [ ] **Step 4: Verify**

Run: `npm run lint` and `npm test`.

Expected: both pass.

### Task 4: Sync Entitlement and Account Deletion

**Files:**
- Modify: `src/context/AppContext.tsx`
- Modify: `src/api/backend.ts`
- Modify: `src/storage/index.ts`
- Modify: `src/screens/Profile.tsx`

- [ ] **Step 1: Sync IAP plan**

On app load and active resume, sync RevenueCat customer plan first when available, persist the resulting plan, then continue existing backend/local quota logic.

- [ ] **Step 2: Add backend account deletion client**

`backendApi.deleteAccount(token)` calls `DELETE /account/me`.

- [ ] **Step 3: Add profile actions**

Profile shows "恢复购买" and "删除账号". Restore calls the subscription service. Delete confirms with `Alert.alert`, calls backend deletion if backend token exists, clears local storage, and resets onboarding.

- [ ] **Step 4: Verify**

Run: `npm run lint` and `npm test`.

Expected: both pass.

### Task 5: Add Backend RevenueCat and Account Endpoints

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Extend settings**

Add `revenuecat_webhook_secret`, `revenuecat_entitlement_id`, `revenuecat_pro_product_id`, and `revenuecat_family_product_id`. Production runtime checks require webhook secret and product IDs when iOS IAP is enabled.

- [ ] **Step 2: Extend subscription storage**

Add `source`, `product_id`, and `expires_at` columns to `subscriptions` with `ALTER TABLE` guards for existing SQLite files.

- [ ] **Step 3: Add account deletion endpoint**

`DELETE /account/me` deletes quotas, idempotency rows, orders, subscriptions, and users for the authenticated user.

- [ ] **Step 4: Add RevenueCat webhook endpoint**

`POST /billing/revenuecat/webhook` validates bearer secret, parses `event.app_user_id`, `event.type`, `event.product_id`, and `event.entitlement_ids`, maps product to plan, and updates subscription to `apple_iap` or `free` for expiration/cancellation.

- [ ] **Step 5: Add tests**

Tests cover pro activation, family activation, expiration fallback to free, invalid secret rejection, and account deletion.

- [ ] **Step 6: Verify**

Run: `cd backend && python -m unittest discover -s tests -v`.

Expected: all tests pass.

### Task 6: Update Report and Final Gates

**Files:**
- Modify: `RELEASE_READINESS_REPORT_2026-04-08.md`

- [ ] **Step 1: Update report**

Report the code-ready IAP status, required App Store Connect product setup, required RevenueCat API key/webhook setup, privacy policy/support URL needs, and TestFlight sandbox checks.

- [ ] **Step 2: Final verification**

Run:

```text
npm run lint
npm test
npx expo-doctor
npm audit --omit=dev
cd backend && python -m unittest discover -s tests -v
git diff --check
```

Expected: all pass; `git diff --check` may print CRLF conversion warnings on Windows but no whitespace errors.
