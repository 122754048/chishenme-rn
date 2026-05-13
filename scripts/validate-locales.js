const fs = require('fs');
function keys(obj, prefix = '') {
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? prefix + '.' + k : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(...keys(v, next));
    else out.push(next);
  }
  return out.sort();
}
const en = JSON.parse(fs.readFileSync('src/i18n/locales/en.json', 'utf8'));
const enKeys = keys(en);
console.log('EN keys: ' + enKeys.length);
let ok = true;
for (const lang of ['zh', 'es', 'ja']) {
  const data = JSON.parse(fs.readFileSync('src/i18n/locales/' + lang + '.json', 'utf8'));
  const k = keys(data);
  if (k.length === enKeys.length && k.every((key, i) => key === enKeys[i])) {
    console.log(lang + ': SHAPE OK (' + k.length + ' keys)');
  } else {
    ok = false;
    console.log(lang + ': MISMATCH');
    const missing = enKeys.filter(x => !k.includes(x));
    const extra = k.filter(x => !enKeys.includes(x));
    if (missing.length) console.log('  missing in ' + lang + ': ' + missing.join(', '));
    if (extra.length) console.log('  extra in ' + lang + ': ' + extra.join(', '));
  }
}
process.exit(ok ? 0 : 1);
