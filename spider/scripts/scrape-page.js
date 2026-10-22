#!/usr/bin/env node

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

/**
 * spider-agent-skills 网页爬取脚本 (TeleAgent 适配版)
 * 
 * 用法: node scrape-page.js [--config <path>] <url>
 * 
 * --config  可选，配置文件路径，默认按以下顺序查找:
 *           1. 当前工作目录/settings.json
 *           2. <脚本所在目录>/../assets/settings.example.json
 */

async function getConfig(configPath) {
  const defaults = {
    browser: 'chrome',
    headless: false,
    keepOpen: false,
    cdpPort: 9222,
    outputDir: path.join(process.cwd(), 'output'),
    tempDir: path.join(process.cwd(), 'temp'),
    sites: {}
  };

  if (!configPath) {
    const cwdSettings = path.join(process.cwd(), 'settings.json');
    if (fs.existsSync(cwdSettings)) {
      configPath = cwdSettings;
    }
  }

  if (configPath && fs.existsSync(configPath)) {
    try {
      const raw = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      const resolved = resolveConfig(raw);
      return { ...defaults, ...resolved };
    } catch (err) {
      console.warn(`Warning: Failed to read config: ${err.message}`);
    }
  }
  return defaults;
}

function resolveConfig(obj) {
  if (typeof obj !== 'object' || obj === null) return obj;
  if (Array.isArray(obj)) return obj.map(resolveConfig);
  const result = {};
  for (const [key, value] of Object.entries(obj)) {
    if (key.startsWith('_')) continue;
    if (typeof value === 'string') {
      result[key] = value.replace(/\$\{([^}]+)\}/g, (m, v) => process.env[v] || m);
    } else if (typeof value === 'object') {
      result[key] = resolveConfig(value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

function getAuthForUrl(url, sites) {
  try {
    const hostname = new URL(url).hostname;
    for (const [domain, siteConfig] of Object.entries(sites)) {
      if (hostname === domain || hostname.endsWith('.' + domain)) {
        return siteConfig.auth;
      }
    }
  } catch (err) {
    console.warn(`Warning: URL parse failed: ${url}`);
  }
  return null;
}

function htmlToMarkdown(html) {
  const TurndownService = (function() {
    try {
      return require('turndown');
    } catch (e) {
      return null;
    }
  })();

  if (TurndownService) {
    const turndown = new TurndownService({
      headingStyle: 'atx',
      codeBlockStyle: 'fenced'
    });
    return turndown.turndown(html);
  }

  // Fallback: simple tag stripping
  let text = html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<\/h[1-6]>/gi, '\n\n')
    .replace(/<\/li>/gi, '\n')
    .replace(/<\/tr>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");

  text = text.split('\n').map(line => line.trim()).join('\n');
  text = text.replace(/\n{3,}/g, '\n\n');

  return text.trim();
}

async function handleBasicAuth(page, auth) {
  const credentials = Buffer.from(`${auth.username}:${auth.password}`).toString('base64');
  await page.setExtraHTTPHeaders({
    'Authorization': `Basic ${credentials}`
  });
  console.log(`  [OK] Basic Auth credentials injected (user: ${auth.username})`);
}

async function handleFormLogin(page, auth) {
  console.log(`  Logging in: ${auth.loginUrl}`);

  await page.goto(auth.loginUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForSelector(auth.selectors.username, { timeout: 10000 });
  await page.fill(auth.selectors.username, auth.username);

  await page.waitForSelector(auth.selectors.password, { timeout: 5000 });
  await page.fill(auth.selectors.password, auth.password);

  await page.waitForSelector(auth.selectors.submit, { timeout: 5000 });
  await page.click(auth.selectors.submit);

  const waitTime = auth.waitAfterLogin || 3000;
  await page.waitForTimeout(waitTime);

  console.log('  [OK] Form login completed');
}

async function tryCdpConnect(port, targetUrl, config) {
  try {
    const browser = await chromium.connectOverCDP(`http://localhost:${port}`);
    console.log(`[OK] CDP connected (port: ${port})`);

    const context = browser.contexts()[0] || await browser.newContext();
    const page = await context.newPage();

    return { browser, page, mode: 'cdp' };
  } catch (err) {
    return null;
  }
}

async function launchBrowser(config) {
  const channel = config.browser || 'chrome';
  const headless = config.headless || false;

  console.log(`Launching browser (channel: ${channel}, headless: ${headless})...`);

  const browser = await chromium.launch({
    headless,
    channel,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext();
  const page = await context.newPage();

  return { browser, page, mode: 'launch' };
}

async function main() {
  // Parse arguments: [--config <path>] <url>
  const args = process.argv.slice(2);
  let configPath = null;
  let url = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--config' && i + 1 < args.length) {
      configPath = args[++i];
    } else if (!url) {
      url = args[i];
    }
  }

  if (!url) {
    console.error('Usage: node scrape-page.js [--config <path>] <url>');
    process.exit(1);
  }

  const config = await getConfig(configPath);
  const tempDir = config.tempDir;
  fs.mkdirSync(tempDir, { recursive: true });

  let browser = null;
  let page = null;
  let mode = '';

  try {
    console.log(`Scraping: ${url}`);
    console.log('');

    // Try CDP connection first
    const cdpResult = await tryCdpConnect(config.cdpPort, url, config);
    if (cdpResult) {
      browser = cdpResult.browser;
      page = cdpResult.page;
      mode = cdpResult.mode;
    } else {
      const launchResult = await launchBrowser(config);
      browser = launchResult.browser;
      page = launchResult.page;
      mode = launchResult.mode;
    }

    // Auth handling
    const auth = getAuthForUrl(url, config.sites);
    if (auth) {
      if (auth.type === 'basic') {
        await handleBasicAuth(page, auth);
      } else if (auth.type === 'form') {
        await handleFormLogin(page, auth);
      }
    }

    // Load target page
    console.log(`  Loading page...`);
    await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });

    // Wait for extra rendering
    await page.waitForTimeout(2000);

    // Extract content
    console.log('  Extracting content...');
    const html = await page.content();
    const title = await page.title();

    const markdown = htmlToMarkdown(html);
    const fullContent = `# ${title}\n\n> Source: ${url}\n> Scraped at: ${new Date().toISOString()}\n> Browser mode: ${mode}\n\n---\n\n${markdown}`;

    // Write raw.md
    const rawPath = path.join(tempDir, 'raw.md');
    fs.writeFileSync(rawPath, fullContent, 'utf-8');
    console.log(`  [OK] Raw content saved: ${rawPath}`);
    console.log(`  [OK] Content length: ${fullContent.length} chars`);

    // Output result summary for the agent
    console.log('');
    console.log(JSON.stringify({
      status: 'success',
      mode,
      url,
      title,
      rawPath,
      contentLength: fullContent.length
    }));

  } catch (err) {
    console.error(`[FAIL] Scraping failed: ${err.message}`);

    // Screenshot fallback
    if (page) {
      try {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const screenshotPath = path.join(tempDir, `error-${timestamp}.png`);
        await page.screenshot({ path: screenshotPath, fullPage: true });
        console.error(`  Screenshot saved: ${screenshotPath}`);
      } catch (screenshotErr) {
        console.error(`  Screenshot failed: ${screenshotErr.message}`);
      }
    }

    console.log('');
    console.log(JSON.stringify({
      status: 'error',
      url,
      error: err.message,
      screenshot: page ? `Saved to ${tempDir}/` : 'Unavailable'
    }));

  } finally {
    if (browser) {
      if (config.keepOpen && mode === 'launch') {
        console.log('  Browser window kept open.');
      } else {
        await browser.close();
        console.log('  Browser closed.');
      }
    }
  }
}

main().catch(err => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
