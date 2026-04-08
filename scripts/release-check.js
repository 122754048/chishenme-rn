const fs = require('fs');
const path = require('path');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const root = path.resolve(__dirname, '..');
const backendConfig = fs.readFileSync(path.join(root, 'backend', 'app', 'config.py'), 'utf8');
const backendApi = fs.readFileSync(path.join(root, 'src', 'api', 'backend.ts'), 'utf8');
const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

assert(backendConfig.includes('def assert_runtime_safe(self) -> None:'), 'backend config should enforce production runtime safety checks');
assert(backendConfig.includes("if self.env.lower() not in {'prod', 'production'}:"), 'backend config should gate strict validation by production env');
assert(!backendApi.includes("const PASSWORD = 'secret123'"), 'frontend should not hardcode backend bootstrap password');
assert(backendApi.includes('EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD'), 'frontend backend bootstrap password should come from env');
assert(packageJson.scripts.lint.includes('release-check.js'), 'lint should include release-check gate');

console.log('Release check passed.');
