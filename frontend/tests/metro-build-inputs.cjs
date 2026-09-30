const assert = require('node:assert/strict');
const path = require('node:path');
const config = require('../metro.config');
const root = path.resolve(__dirname, '..');
assert.equal(new Set(config.resolver.blockList.map((pattern) => pattern.flags)).size, 1,
  'Metro requires every blockList pattern to use the same flags');
const blocked = (relative, separator = path.sep) => {
  const file = path.join(root, relative).replace(/[\\/]/g, separator);
  return config.resolver.blockList.some((pattern) => pattern.test(file));
};
for (const separator of ['/', '\\']) {
  for (const file of ['android/app/build/generated/assets/index.android.bundle', 'dist/_expo/static/js/web/old.js', '.savoya-web-a0123456789/index.html']) {
    assert.equal(blocked(file, separator), true, `Generated file crawled: ${file}`);
  }
  for (const file of ['src/screens/NewsScreen.tsx', 'assets/app-icon.png', 'node_modules/expo-notifications/build/index.js', 'src/android/example.ts', 'src/dist/component.tsx']) {
    assert.equal(blocked(file, separator), false, `Required input blocked: ${file}`);
  }
}
console.log('PASS 17 Metro input cases: compatible pattern flags; skip generated output; preserve source, assets and dependencies');
