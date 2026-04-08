const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ts = require('typescript');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const root = path.resolve(__dirname, '..');
const quotaPath = path.join(root, 'src', 'utils', 'quota.ts');
const source = fs.readFileSync(quotaPath, 'utf8');

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2019,
  },
}).outputText;

const moduleObj = { exports: {} };
const sandbox = { exports: moduleObj.exports, module: moduleObj, require };
vm.runInNewContext(compiled, sandbox, { filename: quotaPath });
const quota = moduleObj.exports;

assert(quota.getQuotaByPlan('free') === 3, 'free plan should be 3/day');
assert(quota.getQuotaByPlan('pro') === -1, 'pro plan should be unlimited');
assert(quota.getQuotaByPlan('family') === -1, 'family plan should be unlimited');

const today = '2026-04-08';
const rollover = quota.getQuotaForToday('free', today, { date: '2026-04-07', left: 1 });
assert(rollover.left === 3, 'free quota should reset at day rollover');

const clamped = quota.getQuotaForToday('free', today, { date: today, left: -20 });
assert(clamped.left === 0, 'quota should clamp to zero for malformed negative values');

const unlimited = quota.getQuotaForToday('pro', today, { date: today, left: 2 });
assert(unlimited.left === -1, 'paid plan should remain unlimited regardless of saved finite value');

assert(quota.consumeQuota(-1) === -1, 'consume should keep unlimited sentinel');
assert(quota.consumeQuota(0) === 0, 'consume should not go below 0');
assert(quota.consumeQuota(2) === 1, 'consume should decrement finite quota');

const resetFresh = quota.getResetQuotaForFree(today, null);
assert(resetFresh.left === 3, 'reset should restore free daily quota for new day/no prior quota');

const resetSameDay = quota.getResetQuotaForFree(today, { date: today, left: 0 });
assert(resetSameDay.left === 0, 'reset should preserve same-day consumed free quota');

const resetFromUnlimited = quota.getResetQuotaForFree(today, { date: today, left: -1 });
assert(resetFromUnlimited.left === 3, 'reset from unlimited state should normalize back to free daily quota');

console.log('Quota test passed.');
