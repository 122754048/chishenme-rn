const fs = require('fs');
const path = require('path');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const root = path.resolve(__dirname, '..');
const backendConfig = fs.readFileSync(path.join(root, 'backend', 'app', 'config.py'), 'utf8');
const backendMain = fs.readFileSync(path.join(root, 'backend', 'app', 'main.py'), 'utf8');
const backendApi = fs.readFileSync(path.join(root, 'src', 'api', 'backend.ts'), 'utf8');
const checkoutCode = fs.readFileSync(path.join(root, 'src', 'screens', 'Checkout.tsx'), 'utf8');
const subscriptionCode = fs.readFileSync(path.join(root, 'src', 'services', 'subscriptions.ts'), 'utf8');
const profileCode = fs.readFileSync(path.join(root, 'src', 'screens', 'Profile.tsx'), 'utf8');
const storageCode = fs.readFileSync(path.join(root, 'src', 'storage', 'index.ts'), 'utf8');
const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const appJson = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'));

assert(backendConfig.includes('def assert_runtime_safe(self) -> None:'), 'backend config should enforce production runtime safety checks');
assert(backendConfig.includes("if self.env.lower() not in {'prod', 'production'}:"), 'backend config should gate strict validation by production env');
assert(!backendConfig.includes('ALIPAY_NOTIFY_TOKEN'), 'backend should not use token-based Alipay notification auth');
assert(backendMain.includes('verify_alipay_rsa2_signature'), 'backend should verify Alipay notifications with RSA2 signatures');
assert(!backendApi.includes("const PASSWORD = 'secret123'"), 'frontend should not hardcode backend bootstrap password');
assert(backendApi.includes('EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD'), 'frontend backend bootstrap password should come from env');
assert(checkoutCode.includes('EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS'), 'mock payment fallback must be gated by an explicit env flag');
assert(checkoutCode.includes("throw new Error('payment backend is not configured')"), 'checkout should fail closed when backend and mock payments are disabled');
assert(packageJson.dependencies['react-native-purchases'], 'iOS commercialization requires react-native-purchases for Apple IAP');
assert(subscriptionCode.includes("from 'react-native-purchases'"), 'subscription service should import RevenueCat SDK');
assert(subscriptionCode.includes('EXPO_PUBLIC_RC_IOS_API_KEY'), 'subscription service should read RevenueCat iOS API key from env');
assert(storageCode.includes('ensureBackendUserId'), 'storage should expose a stable app user id for RevenueCat entitlement sync');
assert(checkoutCode.includes('storage.ensureBackendUserId()'), 'checkout should use a stable RevenueCat app user id before iOS IAP purchase');
assert(checkoutCode.includes("Platform.OS === 'ios'"), 'checkout should branch iOS digital membership purchases to Apple IAP');
assert(checkoutCode.includes('subscriptionService.purchase'), 'checkout should use subscriptionService.purchase for iOS IAP');
assert(checkoutCode.indexOf("Platform.OS === 'ios'") < checkoutCode.indexOf('backendApi.createOrder'), 'checkout should evaluate the iOS IAP path before Alipay/backend order creation');
assert(profileCode.includes('删除账号'), 'profile should expose account deletion for App Store compliance');
assert(profileCode.includes('恢复购买'), 'profile should expose restore purchase for App Store subscription compliance');
assert(backendMain.includes('/billing/revenuecat/webhook'), 'backend should expose RevenueCat webhook for Apple IAP entitlement sync');
assert(backendMain.includes('/account/me'), 'backend should expose account deletion endpoint');
assert(!appJson.expo.ios.bundleIdentifier.includes('anonymous'), 'iOS bundle identifier should be production-ready, not anonymous');
assert(packageJson.scripts.lint.includes('release-check.js'), 'lint should include release-check gate');

console.log('Release check passed.');
