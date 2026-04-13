const fs = require('fs');
const path = require('path');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const root = path.resolve(__dirname, '..');
const paths = {
  mockData: path.join(root, 'src', 'data', 'mockData.ts'),
  recommendations: path.join(root, 'src', 'utils', 'recommendations.ts'),
  appContext: path.join(root, 'src', 'context', 'AppContext.tsx'),
  navigator: path.join(root, 'src', 'navigation', 'AppNavigator.tsx'),
  home: path.join(root, 'src', 'screens', 'Home.tsx'),
  detail: path.join(root, 'src', 'screens', 'Detail.tsx'),
  explore: path.join(root, 'src', 'screens', 'Explore.tsx'),
  onboardingCuisines: path.join(root, 'src', 'screens', 'OnboardingCuisines.tsx'),
  onboardingRestrictions: path.join(root, 'src', 'screens', 'OnboardingRestrictions.tsx'),
  profile: path.join(root, 'src', 'screens', 'Profile.tsx'),
  upgrade: path.join(root, 'src', 'screens', 'Upgrade.tsx'),
  checkout: path.join(root, 'src', 'screens', 'Checkout.tsx'),
  menuScan: path.join(root, 'src', 'screens', 'MenuScan.tsx'),
  searchOverlay: path.join(root, 'src', 'components', 'SearchOverlay.tsx'),
  onboardingGuide: path.join(root, 'src', 'components', 'OnboardingGuide.tsx'),
  storage: path.join(root, 'src', 'storage', 'index.ts'),
  places: path.join(root, 'src', 'services', 'places.ts'),
  menuScanService: path.join(root, 'src', 'services', 'menuScan.ts'),
};

const mockData = fs.readFileSync(paths.mockData, 'utf8');
const recommendationsCode = fs.readFileSync(paths.recommendations, 'utf8');
const appContextCode = fs.readFileSync(paths.appContext, 'utf8');
const navigatorCode = fs.readFileSync(paths.navigator, 'utf8');
const homeCode = fs.readFileSync(paths.home, 'utf8');
const detailCode = fs.readFileSync(paths.detail, 'utf8');
const exploreCode = fs.readFileSync(paths.explore, 'utf8');
const onboardingCuisinesCode = fs.readFileSync(paths.onboardingCuisines, 'utf8');
const onboardingRestrictionsCode = fs.readFileSync(paths.onboardingRestrictions, 'utf8');
const profileCode = fs.readFileSync(paths.profile, 'utf8');
const upgradeCode = fs.readFileSync(paths.upgrade, 'utf8');
const checkoutCode = fs.readFileSync(paths.checkout, 'utf8');
const menuScanCode = fs.readFileSync(paths.menuScan, 'utf8');
const searchOverlayCode = fs.readFileSync(paths.searchOverlay, 'utf8');
const onboardingGuideCode = fs.readFileSync(paths.onboardingGuide, 'utf8');
const storageCode = fs.readFileSync(paths.storage, 'utf8');
const placesCode = fs.readFileSync(paths.places, 'utf8');
const menuScanServiceCode = fs.readFileSync(paths.menuScanService, 'utf8');

assert(mockData.includes('restaurantName'), 'mock data should support restaurant-plus-dish cards');
assert(mockData.includes('restaurantReviewCount'), 'mock data should include restaurant trust signals');
assert(mockData.includes('recommendationBlurb'), 'mock data should still provide recommendation summary copy');
assert(recommendationsCode.includes('getRecommendedDishes'), 'recommendation utility should export ranked recommendations');
assert(recommendationsCode.includes('nearbyRestaurants'), 'recommendation utility should account for nearby restaurant context');
assert(recommendationsCode.includes('activeFilter'), 'recommendation utility should support home deck filters');
assert(recommendationsCode.includes('keepItFresh'), 'recommendation utility should support repeat-avoidance logic');
assert(recommendationsCode.includes('forTwo'), 'recommendation utility should support duo decision mode');
assert(recommendationsCode.includes('getTodaysTopPicks'), 'recommendation utility should expose the curated top picks strip');
assert(recommendationsCode.includes('getDecisivePick'), 'recommendation utility should expose the decisive-pick helper');
assert(appContextCode.includes('locationContext'), 'app context should expose location context');
assert(appContextCode.includes('saveAreaPreset'), 'app context should support saved areas');
assert(appContextCode.includes('backendToken'), 'app context should expose backend token for nearby and menu scan features');
assert(appContextCode.includes('decisionSettings'), 'app context should persist C-stage decision settings');
assert(storageCode.includes('LOCATION_CONTEXT'), 'storage should persist location context');
assert(storageCode.includes('SAVED_AREAS'), 'storage should persist saved areas');
assert(storageCode.includes('DECISION_SETTINGS'), 'storage should persist C-stage decision settings');
assert(placesCode.includes('searchNearbyRestaurants'), 'places service should call the backend discovery endpoint');
assert(menuScanServiceCode.includes('launchCameraAsync'), 'menu scan service should support camera input');
assert(menuScanServiceCode.includes('launchImageLibraryAsync'), 'menu scan service should support screenshot/library input');
assert(navigatorCode.includes("tabBarLabel: 'Home'"), 'navigator should use English North America tab labels');
assert(navigatorCode.includes("name=\"MenuScan\""), 'navigator should wire the menu scan route');
assert(!navigatorCode.includes('ChiShenMe'), 'navigator shell should use the new North America brand');
assert(onboardingGuideCode.includes('Swipe left to pass'), 'onboarding guide should teach the current swipe model in English');
assert(searchOverlayCode.includes('dish, place, area'), 'search overlay should support area and restaurant search');
assert(onboardingCuisinesCode.includes('Pick your favorites'), 'cuisine onboarding should be English-first');
assert(onboardingRestrictionsCode.includes('Saved areas'), 'restriction onboarding should capture home/work area context');
assert(
  homeCode.includes("triggerDecision('left')") && homeCode.includes("triggerDecision('right')"),
  'home should stay focused on the swipe deck'
);
assert(homeCode.includes("navigation.navigate('MainTabs', { screen: 'Explore' })"), 'home should hand secondary discovery to Explore');
assert(homeCode.includes("navigation.navigate('Upgrade')"), 'home should route quota exhaustion to upgrade');
assert(homeCode.includes("navigation.navigate('MenuScan'"), 'home should expose menu scan from the main deck');
assert(detailCode.includes('Snapshot') || detailCode.includes('buildDecisionSnapshot'), 'detail should include decision framing, not just presentation');
assert(exploreCode.includes('Top 3'), 'explore should own the curated daily picks');
assert(exploreCode.includes('buildManualAreaContext') || exploreCode.includes('Save Home'), 'explore should support using a manual area for the home deck');
assert(exploreCode.includes('Nearby'), 'explore should show nearby restaurant trust signals');
assert(exploreCode.includes('Fresh'), 'explore should expose repeat-avoidance mode');
assert(exploreCode.includes('For two'), 'explore should expose duo mode');
assert(fs.readFileSync(path.join(root, 'src', 'screens', 'History.tsx'), 'utf8').includes('Worth revisiting'), 'history should help users revisit strong prior picks');
assert(profileCode.includes('Delete account'), 'profile should expose account deletion');
assert(profileCode.includes('saveAreaPreset') || profileCode.includes('Areas'), 'profile should reflect saved location context');
assert(upgradeCode.includes('Smart rank') || upgradeCode.includes('Upgrade'), 'upgrade should still sell decision quality');
assert(checkoutCode.includes('Confirm subscription'), 'checkout should be English and productized');
assert(checkoutCode.includes('Restore purchases'), 'checkout should expose restore purchase');
assert(menuScanCode.includes('Scan a menu'), 'menu scan screen should exist');
assert(menuScanCode.includes('Best for you'), 'menu scan results should group recommendations');

console.log('Smoke test passed.');
