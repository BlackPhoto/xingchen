#!/usr/bin/env node

const { execSync } = require('child_process');

console.log('=== Playwright Environment Check ===');
console.log('');

try {
  const version = execSync('npx playwright --version', { stdio: 'pipe', timeout: 10000 }).toString().trim();
  console.log(`[OK] Playwright version: ${version}`);
} catch (err) {
  console.log('[FAIL] Playwright not installed');
  console.log('  Run: npm install playwright');
  process.exit(1);
}

try {
  execSync('npx playwright install --dry-run chromium', { stdio: 'pipe', timeout: 15000 });
  console.log('[OK] Chromium browser kernel installed');
} catch {
  console.log('[FAIL] Chromium browser kernel not installed');
  console.log('  Run: npx playwright install chromium');
  process.exit(1);
}

console.log('');
console.log('[OK] Environment ready');
