const fs = require('fs');
const path = require('path');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const root = path.resolve(__dirname, '..');
const mockDataPath = path.join(root, 'src', 'data', 'mockData.ts');
const checkoutPath = path.join(root, 'src', 'screens', 'Checkout.tsx');
const appContextPath = path.join(root, 'src', 'context', 'AppContext.tsx');
const searchOverlayPath = path.join(root, 'src', 'components', 'SearchOverlay.tsx');
const storagePath = path.join(root, 'src', 'storage', 'index.ts');
const homePath = path.join(root, 'src', 'screens', 'Home.tsx');
const explorePath = path.join(root, 'src', 'screens', 'Explore.tsx');
const appApiPath = path.join(root, 'src', 'api', 'backend.ts');
const data = fs.readFileSync(mockDataPath, 'utf8');
const checkoutCode = fs.readFileSync(checkoutPath, 'utf8');
const appContextCode = fs.readFileSync(appContextPath, 'utf8');
const searchOverlayCode = fs.readFileSync(searchOverlayPath, 'utf8');
const storageCode = fs.readFileSync(storagePath, 'utf8');
const homeCode = fs.readFileSync(homePath, 'utf8');
const exploreCode = fs.readFileSync(explorePath, 'utf8');
const appApiCode = fs.readFileSync(appApiPath, 'utf8');

assert(data.includes("category: '推荐'"), 'EXPLORE_CARDS must include 推荐 category item');
assert(data.includes("category: '中餐'"), 'EXPLORE_CARDS must include 中餐 category item');
assert(data.includes("category: '日料'"), 'EXPLORE_CARDS must include 日料 category item');
assert(data.includes('cuisine:'), 'EXPLORE_CARDS items should include cuisine metadata');
assert(data.includes('mealType:'), 'EXPLORE_CARDS items should include mealType metadata');
assert(data.includes('priceBand:'), 'EXPLORE_CARDS items should include priceBand metadata');
assert(data.includes('dietTag:'), 'EXPLORE_CARDS items should include dietTag metadata');
assert(!checkoutCode.includes('Math.random'), 'Checkout should avoid random payment outcomes');
assert(checkoutCode.includes('appendPaymentEvent'), 'Checkout should persist payment lifecycle events');
assert(checkoutCode.includes('backendApi.createOrder'), 'Checkout should call backend create-order in pay flow');
assert(checkoutCode.includes('backendApi.getOrder'), 'Checkout should poll backend order status in pay flow');
assert(!checkoutCode.includes('markOrderPaidForTesting'), 'Checkout should not use backend mock mark-paid in production pay flow');
assert(checkoutCode.includes('refreshOrderStatus'), 'Checkout should provide a manual order status refresh action when payment is pending');
assert(appContextCode.includes("AppState.addEventListener('change'"), 'AppContext should resync quota when app becomes active');
assert(appContextCode.includes("from '../utils/quota'"), 'AppContext should use shared quota utility logic');
assert(appContextCode.includes("const syncDailyQuota = useCallback(async (plan: 'free' | 'pro' | 'family')"), 'Quota sync should be explicit to a membership plan');
assert(appContextCode.includes('getResetQuotaForFree'), 'Reset flow should preserve same-day free quota to prevent local reset abuse');
assert(checkoutCode.includes("recordEvent('trial', 'failed'"), 'Trial flow should record failure events when exceptions happen');
assert(checkoutCode.includes('eventSeq'), 'Checkout event IDs should include a local sequence to avoid same-ms collisions');
assert(storageCode.includes('async setRecentSearches'), 'Storage should provide recent search persistence APIs');
assert(searchOverlayCode.includes('storage.getRecentSearches'), 'Search overlay should load recent searches from storage API');
assert(searchOverlayCode.includes('onClose();'), 'Submitting search should close overlay for faster interaction flow');
assert(searchOverlayCode.includes('userInteractedRef'), 'Search overlay hydration should guard against overwriting in-flight user input');
assert(searchOverlayCode.includes('recentSearches.length > 0 ? recentSearches : DEFAULT_RECENT_SEARCHES'), 'Recent-search section should fall back to defaults when persisted list is empty');
assert(!appContextCode.includes('refreshRecommendations'), 'AppContext should not expose refresh action that bypasses free daily limits');
assert(homeCode.includes("navigation.navigate('Upgrade')"), 'Quota-exhausted state should route free users to upgrade instead of resetting quota');
assert(homeCode.includes('.enabled(enabled)'), 'Swipe gesture should be disabled when quota is locked');
assert(homeCode.includes('disabled={quotaLocked}'), 'Action buttons should be disabled when free quota is exhausted');
assert(homeCode.includes("params: { initialQuery: query }"), 'Home search should pass query into Explore tab route');
assert(exploreCode.includes('route.params?.initialQuery'), 'Explore should hydrate search query from route params');
assert(exploreCode.includes('tabNavigation.setParams({ initialQuery: undefined })'), 'Explore should consume and clear initialQuery params to avoid sticky stale searches');
assert(!exploreCode.includes('route.params?.initialQuery, searchQuery'), 'Explore param-sync effect should not depend on searchQuery to avoid wiping manual user input');
assert(appContextCode.includes('backendApi.isEnabled()'), 'AppContext should support backend-enabled quota synchronization');
assert(appContextCode.includes('backendApi.getMembership(backendToken)'), 'AppContext should refresh backend membership when app returns active');
assert(appApiCode.includes('/auth/register') && appApiCode.includes('/auth/login'), 'Backend API client should bootstrap auth session');
assert(!appApiCode.includes("const PASSWORD = 'secret123'"), 'Backend API client should not hardcode bootstrap password');
assert(appApiCode.includes('EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD'), 'Backend bootstrap password should come from env');

console.log('Smoke test passed.');
