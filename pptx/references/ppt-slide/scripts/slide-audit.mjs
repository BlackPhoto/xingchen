#!/usr/bin/env node
/* ============================================================================
 * slide-audit · slide-audit.mjs
 * 零依赖 Node 运行器：驱动本机 Chrome/Edge 的 CDP 协议做无头几何审计。
 *
 * 用法：
 *   node slide-audit.mjs <文件或目录或glob> [选项]
 *   node slide-audit.mjs slide_*.html --open
 *   node slide-audit.mjs . --out report.html --open --json report.json
 *
 * 主要选项：
 *   --out <file>        输出可视化 HTML 报告（默认 audit-report.html）
 *   --json <file>       输出 JSON（默认 audit-report.json）
 *   --md  <file>        输出 Markdown
 *   --open              跑完自动打开 HTML 报告
 *   --shots <dir>       同时导出每页标注后的 PNG
 *   --fail-on <level>   error|warning|none，命中则 exit code = 1（默认 none）
 *   --baseline <json>   与上次结果对比，只报告新增/变化的问题
 *   --min-font <n>      最小字号阈值（默认 18）
 *   --min-contrast <n>  最小对比度阈值（默认 3.0）
 *   --tol <n>           几何容差 px（默认 1.5）
 *   --no-contrast       关闭对比度检查
 *   --no-occlusion      关闭遮挡检查（最耗时的一项）
 *   --chrome <path>     指定浏览器可执行文件
 *   --quiet             只输出汇总
 * ========================================================================== */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

/* ------------------------------ WebSocket 兼容层 ------------------------------ */
/* Node 22+ 有全局 WebSocket；Node 20 没有，需 --experimental-websocket flag。
 * 这里检测到缺失时自动带 flag 重启自身，对调用方完全透明。*/
if (typeof globalThis.WebSocket === 'undefined') {
  const args = ['--experimental-websocket', ...process.argv.slice(1)];
  const child = spawn(process.execPath, args, { stdio: 'inherit' });
  child.on('exit', (code) => process.exit(code || 0));
  // 防止后续代码在此进程继续执行
  await new Promise(() => {});
}

/* ------------------------------ 参数解析 ------------------------------ */

const argv = process.argv.slice(2);
const FLAG_BOOL = new Set(['--open', '--quiet', '--no-contrast', '--no-occlusion', '--no-shots', '--no-out']);
const opts = {
  inputs: [], out: 'audit-report.html', json: 'audit-report.json', md: null,
  open: false, shots: null, failOn: 'none', baseline: null, chrome: null, quiet: false,
  rules: {}, engine: {}
};

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (!a.startsWith('-')) { opts.inputs.push(a); continue; }
  const [name, inlineVal] = a.includes('=') ? a.split('=') : [a, null];
  const take = () => inlineVal !== null ? inlineVal : argv[++i];
  switch (name) {
    case '--out': opts.out = take(); break;
    case '--json': opts.json = take(); break;
    case '--md': opts.md = take(); break;
    case '--shots': opts.shots = take(); break;
    case '--fail-on': opts.failOn = take(); break;
    case '--baseline': opts.baseline = take(); break;
    case '--chrome': opts.chrome = take(); break;
    case '--min-font': opts.engine.minFontSize = Number(take()); break;
    case '--min-contrast': opts.engine.minContrast = Number(take()); break;
    case '--tol': opts.engine.overflowTol = Number(take()); opts.engine.tol = Number(opts.engine.overflowTol); break;
    case '--no-contrast': opts.rules.LOW_CONTRAST = false; break;
    case '--no-occlusion': opts.rules.OCCLUDED = false; break;
    case '--quiet': opts.quiet = true; break;
    case '--open': opts.open = true; break;
    case '--no-out': opts.out = null; break;
    case '--help': printHelp(); process.exit(0);
    case '--include-shell': opts.engine.includeShell = true; break;
    default:
      if (!FLAG_BOOL.has(a)) console.warn(`[warn] 未知参数：${a}`);
  }
}

function printHelp() {
  console.log(`
slide-audit —— HTML 幻灯片排版体检（无需视觉模型）

用法:
  node slide-audit.mjs <文件|目录|glob> [选项]

示例:
  node slide-audit.mjs slide_*.html --open          检查并打开可视化报告
  node slide-audit.mjs . --fail-on error            仅当有「错误」时退出码为 1
  node slide-audit.mjs deck.html --baseline last.json --out new.html
                                                    改完后只看新增问题

选项:
  --out <file>        HTML 可视化报告（默认 audit-report.html）
  --json <file>       JSON 结果（默认 audit-report.json）
  --md <file>         Markdown 报告
  --open              跑完自动打开 HTML 报告
  --shots <dir>       导出每页带标注框的 PNG
  --fail-on <lvl>     error|warning|none；命中则退出码 1（默认 none）
  --baseline <json>   与上次 JSON 对比，只列出新增/变化的问题
  --min-font <n>      最小字号阈值，默认 18
  --min-contrast <n>  最小对比度阈值，默认 3.0
  --tol <n>           几何容差 px，默认 1.5
  --no-contrast       关闭对比度检查
  --no-occlusion      关闭遮挡检查（最耗时的一项）
  --no-out            不生成 HTML 可视化报告和截图（步骤3.6 逐页体检时使用，省时间；步骤6.5 全量体检仍用 --out）
  --chrome <path>     指定浏览器可执行文件
  --quiet             只打印汇总行
`);
}
if (opts.inputs.length === 0) {
  console.error('请指定要检查的 HTML 文件或目录，例如：node slide-audit.mjs slide_*.html');
  process.exit(2);
}

/* ------------------------------ 文件发现 ------------------------------ */

function globToRegExp(p) {
  const esc = p.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  return new RegExp('^' + esc.replace(/\*\*/g, '\u0000').replace(/\*/g, '[^/\\\\]*').replace(/\u0000/g, '.*').replace(/\?/g, '.') + '$', 'i');
}

// 避免自引用：跳过本工具生成的报告文件
const SELF_RE = /(^|[\\/])(audit-report.*|_audit.*)\.html?$/i;
const generatedPaths = new Set();
for (const k of ['out', 'json', 'md']) {
  if (opts[k]) { try { generatedPaths.add(fs.realpathSync(path.resolve(opts[k]))); } catch { generatedPaths.add(path.resolve(opts[k])); } }
}
// 兜底：内容里带本工具水印的也跳过
function isSelfGenerated(file) {
  if (SELF_RE.test(file)) return true;
  try {
    if (generatedPaths.has(fs.realpathSync(file))) return true;
  } catch { }
  if (generatedPaths.has(path.resolve(file))) return true;
  try {
    const head = fs.readFileSync(file, 'utf8').slice(0, 4096);
    if (/Slide Audit|__slide_audit_overlay__/.test(head)) return true;
  } catch { }
  return false;
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith('.') || e.name === 'node_modules') continue;
    const f = path.join(dir, e.name);
    if (e.isDirectory()) walk(f, out);
    else if (/\.html?$/i.test(e.name) && !isSelfGenerated(f)) out.push(f);
  }
  return out;
}

function resolveInputs(inputs) {
  const files = new Set();
  for (const raw of inputs) {
    const p = path.resolve(raw);
    if (fs.existsSync(p) && fs.statSync(p).isDirectory()) {
      walk(p).forEach(f => files.add(f));
    } else if (/[*?]/.test(raw)) {
      const re = globToRegExp(path.resolve(raw).replace(/\\/g, '/'));
      const base = path.dirname(raw.split(/[*?]/)[0]) || '.';
      walk(path.resolve(base)).forEach(f => { if (re.test(f.replace(/\\/g, '/'))) files.add(f); });
    } else if (fs.existsSync(p)) {
      if (isSelfGenerated(p)) console.log(`[skip] ${path.basename(p)}：本工具生成的报告，跳过`);
      else files.add(p);
    } else {
      console.warn(`[warn] 找不到：${raw}`);
    }
  }
  return [...files];
}

/* --------------------- 模板型单文件拆分（script[type=text/html]） --------------------- */

const TPL_RE = /<script\b[^>]*type\s*=\s*["']text\/html["'][^>]*>([\s\S]*?)<\/script>/gi;

function extractTemplates(file, tmpDir) {
  const src = fs.readFileSync(file, 'utf8');
  const out = [];
  let m, i = 0;
  while ((m = TPL_RE.exec(src)) !== null) {
    const body = m[1];
    if (!/class=["'][^"']*slide|<div/i.test(body)) continue;
    const pre = src.slice(Math.max(0, m.index - 200), m.index);
    const idm = /id\s*=\s*["']([^"']+)["']/.exec(m[0]);
    const name = (idm ? idm[1] : 'slide') + '-' + (++i);
    const offsetLines = src.slice(0, m.index).split('\n').length;
    const f = path.join(tmpDir, safeName(path.basename(file, '.html')) + '__' + safeName(name) + '.html');
    fs.writeFileSync(f, body, 'utf8');
    out.push({ file: f, origin: file, name, lineOffset: offsetLines });
  }
  return out;
}
function safeName(s) { return String(s).replace(/[^\w.-]+/g, '_').slice(0, 60); }

/* ------------------------------ 浏览器定位 ------------------------------ */

function findChrome() {
  if (opts.chrome && fs.existsSync(opts.chrome)) return opts.chrome;
  const cands = [
    process.env.CHROME_PATH,
    // Windows
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    process.env.LOCALAPPDATA && process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
    // macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    // Linux
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser'
  ].filter(Boolean);
  for (const c of cands) if (fs.existsSync(c)) return c;
  throw new Error('未找到 Chrome/Edge，请用 --chrome 指定路径');
}

/* ------------------------------ 极简 CDP 客户端 ------------------------------ */

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.listeners = new Map();
    ws.addEventListener('message', (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(`${msg.error.message} (code ${msg.error.code})`)) : resolve(msg.result);
      } else if (msg.method) {
        (this.listeners.get(msg.method) || []).forEach(fn => fn(msg.params));
      }
    });
  }
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', rej, { once: true });
    });
    return new CDP(ws);
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`CDP 超时: ${method}`)); }
      }, 60000);
    });
  }
  on(method, fn) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(fn);
  }
  off(method, fn) {
    const arr = this.listeners.get(method);
    if (arr) {
      const idx = arr.indexOf(fn);
      if (idx >= 0) arr.splice(idx, 1);
      if (arr.length === 0) this.listeners.delete(method);
    }
  }
  close() { try { this.ws.close(); } catch { } }
}

async function httpJson(url, tries = 60, delay = 150) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch { /* 还没起来 */ }
    await new Promise(r => setTimeout(r, delay));
  }
  throw new Error('浏览器调试端口未就绪');
}

/* ------------------------------ 主流程 ------------------------------ */

const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'slide-audit-'));
const profileDir = path.join(tmpRoot, 'profile');
fs.mkdirSync(profileDir, { recursive: true });
let chromeProc = null;
let cdp = null;

// 统一清理：关闭 CDP 连接 + 杀掉 Chrome 子进程 + 删除临时目录
// 防止 Ctrl+C 或异常退出时 Chrome 变僵尸进程占用端口或残留临时文件
function killChrome() {
  try { cdp?.close(); } catch { }
  try { chromeProc?.kill('SIGKILL'); } catch { }
  // 清理临时目录（Chrome profile 数据），避免长期使用积累垃圾文件
  try { fs.rmSync(tmpRoot, { recursive: true, force: true }); } catch { }
}
process.on('SIGINT', () => { killChrome(); process.exit(130); });
process.on('SIGTERM', () => { killChrome(); process.exit(143); });
process.on('exit', () => { try { chromeProc?.kill('SIGKILL'); } catch { } try { fs.rmSync(tmpRoot, { recursive: true, force: true }); } catch { } });

async function launch() {
  const exe = findChrome();
  const port = 9200 + Math.floor(Math.random() * 600);
  chromeProc = spawn(exe, [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--disable-background-networking', '--disable-component-update',
    '--disable-gpu', '--hide-scrollbars', '--mute-audio',
    '--allow-file-access-from-files', '--force-device-scale-factor=1',
    '--font-render-hinting=none', '--disable-lcd-text',
    '--window-size=1280,768',
    'about:blank'
  ], { stdio: 'ignore', detached: false });

  const ver = await httpJson(`http://127.0.0.1:${port}/json/version`);
  let list = await httpJson(`http://127.0.0.1:${port}/json/list`);
  let page = list.find(t => t.type === 'page') || (await httpJson(`http://127.0.0.1:${port}/json/new?about:blank`));
  cdp = await CDP.connect(page.webSocketDebuggerUrl);
  return ver;
}

async function evaluate(expr, awaitPromise = true, timeout) {
  const args = {
    expression: `(async function(){ ${expr} })()`,
    returnByValue: true, awaitPromise, userGesture: true
  };
  // 可选：给 awaitPromise 的执行加 CDP 侧超时（防止页面 Promise 永不 resolve 时卡死审计）
  if (timeout) args.timeout = timeout;
  const r = await cdp.send('Runtime.evaluate', args);
  if (r.exceptionDetails) {
    const ex = r.exceptionDetails;
    throw new Error(ex.exception?.description || ex.text || 'evaluate 异常');
  }
  return r.result.value;
}

const ENGINE_SRC = fs.readFileSync(new URL('./engine.js', import.meta.url), 'utf8');

async function auditFile(file, meta) {
  const url = pathToFileURL(file).href;
  const consoleErrors = [];
  const onEntry = (e) => {
    if (e.entry && (e.entry.level === 'error' || e.entry.level === 'warning')) {
      if (/favicon|Failed to load resource/i.test(e.entry.text || '')) return;
      consoleErrors.push(`${e.entry.level}: ${e.entry.text}`);
    }
  };
  cdp.on('Runtime.consoleAPICalled', onEntry);

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable').catch(() => { });

  const loaded = new Promise(res => {
    let done = false;
    const h = () => { if (done) return; done = true; res(); };
    cdp.on('Page.loadEventFired', h);
    setTimeout(h, 8000);
  });
  await cdp.send('Page.navigate', { url });
  await loaded;

  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1280, height: 768, deviceScaleFactor: 1, mobile: false
  }).catch(() => { });
  // 等待字体就绪；fonts.ready 在某些字体加载失败场景可能永不 resolve，用 2s 超时兜底
  await evaluate(
    `document.fonts && document.fonts.ready ? await Promise.race([document.fonts.ready, new Promise(function (r) { setTimeout(r, 2000); })]) : 0;`,
    true, 4000
  );

  // 若文档内含多张 slide，抬高视口让全部进入视口（elementFromPoint 需要）
  const dim = await evaluate(`
    const ds=document.documentElement;
    return JSON.stringify({w:Math.max(ds.scrollWidth,1280),h:Math.max(ds.scrollHeight,768)});
  `);
  const d = JSON.parse(dim || '{}');
  const vh = Math.min(Math.max(d.h || 768, 768), 20000);
  if (vh > 768 + 32) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: Math.max(d.w || 1280, 1280), height: vh, deviceScaleFactor: 1, mobile: false
    }).catch(() => { });
    await evaluate(`await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));`);
  }

  const engineOpts = Object.assign({}, opts.engine, { rules: opts.rules });
  const raw = await evaluate(`
    ${ENGINE_SRC}
    return JSON.stringify(window.__SLIDE_AUDIT__(${JSON.stringify(engineOpts)}));
  `);
  const result = JSON.parse(raw);

  // 标注 + 截图
  const shots = [];
  const wantShots = opts.shots || opts.out;
  if (wantShots) {
    const n = await evaluate(`${ENGINE_SRC}; return window.__SLIDE_AUDIT_ANNOTATE__ ? 1 : 0;`);
    if (n === 1) {
      await evaluate(`window.__SLIDE_AUDIT_ANNOTATE__(${JSON.stringify(result)});`);
    }
    const shotDir = opts.shots ? path.resolve(opts.shots) : path.join(tmpRoot, 'shots');
    fs.mkdirSync(shotDir, { recursive: true });
    for (const s of result.slides) {
      const clip = { x: s.rect.x, y: s.rect.y, width: s.rect.w, height: s.rect.h, scale: 1 };
      const png = await cdp.send('Page.captureScreenshot', {
        format: 'png', clip, captureBeyondViewport: true, optimizeForSpeed: true
      }).catch(async () => await cdp.send('Page.captureScreenshot', { format: 'png' }));
      const b64 = png.data;
      const f = path.join(shotDir, `${safeName(path.basename(file, '.html'))}__s${String(s.index).padStart(2, '0')}.png`);
      fs.writeFileSync(f, Buffer.from(b64, 'base64'));
      shots.push({ file: f, b64, slide: s.index });
    }
    await evaluate(`const o=document.getElementById('__slide_audit_overlay__'); if(o) o.remove();`);
  }

  // 源码行号映射
  const originFile = meta?.origin || file;
  let srcText = null;
  try { srcText = fs.readFileSync(originFile, 'utf8'); } catch { }
  for (const it of result.issues) {
    it.file = originFile;
    it.fileName = path.basename(originFile);
    // 模板型文件拆分后仍在「原始文件」里按样式/文案定位行号，无需额外偏移
    it.line = srcText ? locateLine(srcText, it) : null;
  }
  if (consoleErrors.length) {
    result.issues.push({
      rule: 'CONSOLE', ruleTitle: '页面脚本报错', severity: 'warning', slide: 1,
      path: '-', tag: '', text: consoleErrors.slice(0, 3).join(' | '), style: '',
      rect: null, message: '页面存在 ' + consoleErrors.length + ' 条控制台错误', data: {}
    });
    result.stats.warning = (result.stats.warning || 0) + 1;
  }
  result.file = originFile;
  result.shots = shots;
  // 清理本文件注册的 CDP 监听器，避免多文件审计时监听器累积导致重复计数
  cdp.off('Runtime.consoleAPICalled', onEntry);
  return result;
}

// 用 inline style / 文案在源文件里定位行号
// 多个兄弟共用同一段 inline style 时（卡片列表很常见），按 path 末尾的 :N 取第 N 次出现
function nthIndexOf(src, needle, n) {
  let idx = -1;
  for (let i = 0; i < Math.max(1, n); i++) {
    idx = src.indexOf(needle, idx + 1);
    if (idx < 0) return -1;
  }
  return idx;
}

function occurrenceInPath(p) {
  const m = /:(\d+)$/.exec(String(p || ''));
  return m ? parseInt(m[1], 10) : 1;
}

function locateLine(src, it) {
  const occ = occurrenceInPath(it.path);
  const cands = [];
  if (it.style) {
    cands.push(it.style);
    const seg = it.style.split(';').filter(s => s.trim()).slice(0, 4).join(';');
    if (seg) cands.push(seg);
    const first = it.style.split(';')[0];
    if (first && first.length > 8) cands.push(first);
  }
  if (it.text) cands.push(it.text.slice(0, 30), it.text.slice(0, 14));
  for (const c of cands) {
    if (!c || c.length < 6) continue;
    let idx = nthIndexOf(src, c, occ);
    if (idx < 0) idx = src.indexOf(c);          // 兜底：取第一次出现
    if (idx >= 0) return src.slice(0, idx).split('\n').length;
  }
  return null;
}

/* ------------------------------ 报告 ------------------------------ */

const SEV = { error: { cn: '错误', sym: '✗', order: 0 }, warning: { cn: '警告', sym: '!', order: 1 }, info: { cn: '提示', sym: '·', order: 2 } };
const RULE_CN = {
  TEXT_OVERFLOW: '文字溢出容器',
  CHILD_OUT_OF_PARENT: '子元素越出父容器',
  TEXT_CLIPPED: '文字被裁切',
  OUT_OF_CANVAS: '超出画布',
  OVERLAP: '元素重叠',
  OCCLUDED: '文字被遮挡',
  TEXT_TRUNCATED: '文本被截断',
  FONT_TOO_SMALL: '字号过小',
  LOW_CONTRAST: '对比度过低',
  CONSOLE: '脚本报错',
  ENGINE_ERROR: '引擎异常'
};

function fingerprint(it) {
  return [it.fileName, it.slide, it.rule, it.path, it.rect ? `${Math.round(it.rect.rx / 6)},${Math.round(it.rect.ry / 6)}` : ''].join('|');
}

function renderText(results, filtered) {
  const L = [];
  const bar = '='.repeat(78);
  L.push(bar);
  L.push('  Slide Audit · HTML 幻灯片排版体检报告');
  L.push('  ' + new Date().toLocaleString('zh-CN'));
  L.push(bar);

  let te = 0, tw = 0, ti = 0;
  for (const r of results) {
    const fileIssues = filtered.get(r.file) || [];
    te += fileIssues.filter(i => i.severity === 'error').length;
    tw += fileIssues.filter(i => i.severity === 'warning').length;
    ti += fileIssues.filter(i => i.severity === 'info').length;

    L.push('');
    L.push(`■ ${path.basename(r.file)}   [${path.dirname(r.file)}]`);
    L.push(`  画布 ${r.slides.map(s => `${s.width}×${s.height}`).join(' / ')} · ${r.slides.length} 页`);
    if (!fileIssues.length) { L.push('  ✓ 未发现问题'); continue; }

    const bySlide = new Map();
    fileIssues.forEach(i => {
      if (!bySlide.has(i.slide)) bySlide.set(i.slide, []);
      bySlide.get(i.slide).push(i);
    });
    for (const [sn, list] of [...bySlide].sort((a, b) => a[0] - b[0])) {
      L.push(`  ── 第 ${sn} 页 ─────────────────────────────────────────`);
      list.sort((a, b) => SEV[a.severity].order - SEV[b.severity].order);
      list.forEach((it, k) => {
        const s = SEV[it.severity];
        L.push(`  [${s.sym}] ${String(k + 1).padStart(2)}. ${RULE_CN[it.rule] || it.rule}  (${it.severity})`);
        L.push(`      位置 : ${it.path}${it.line ? `   ← 源码第 ${it.line} 行` : ''}`);
        if (it.rect) L.push(`      区域 : x=${it.rect.rx} y=${it.rect.ry} ${it.rect.w}×${it.rect.h}`);
        if (it.text) L.push(`      文案 : “${it.text.slice(0, 56)}”`);
        L.push(`      问题 : ${it.message}`);
        if (it.style) L.push(`      样式 : ${it.style.slice(0, 150)}`);
        const sg = it.data && it.data.suggestions;
        if (sg && sg.length) {
          L.push(`      修复建议:`);
          sg.forEach(x => L.push(`        · ${x.from ? x.from + '  →  ' + x.to : '新增 ' + x.to}${x.note ? '   [' + x.note + ']' : ''}`));
        }
        L.push('');
      });
    }
  }
  L.push(bar);
  L.push(`  合计：${te} 错误 / ${tw} 警告 / ${ti} 提示`);
  L.push(bar);
  return L.join('\n');
}

function renderMarkdown(results, filtered) {
  const L = ['# Slide Audit 报告', '', `生成时间：${new Date().toLocaleString('zh-CN')}`, ''];
  let te = 0, tw = 0, ti = 0;
  for (const r of results) {
    const list = filtered.get(r.file) || [];
    te += list.filter(i => i.severity === 'error').length;
    tw += list.filter(i => i.severity === 'warning').length;
    ti += list.filter(i => i.severity === 'info').length;
    L.push(`## ${path.basename(r.file)}`, '');
    L.push(`- 文件：\`${r.file}\``);
    L.push(`- 画布：${r.slides.map(s => `${s.width}×${s.height}`).join(' / ')}（${r.slides.length} 页）`);
    L.push('');
    if (!list.length) { L.push('✅ 未发现问题', ''); continue; }
    L.push('| # | 级别 | 页 | 规则 | 位置 | 说明 | 建议 |');
    L.push('|---|------|----|------|------|------|------|');
    list.sort((a, b) => SEV[a.severity].order - SEV[b.severity].order);
    list.forEach((it, k) => {
      const sg = (it.data && it.data.suggestions || []).map(x => x.from ? `${x.from} → ${x.to}` : `新增 ${x.to}`).join('；');
      L.push(`| ${k + 1} | ${SEV[it.severity].cn} | ${it.slide} | ${RULE_CN[it.rule] || it.rule} | ` +
        `\`${it.path.replace(/\|/g, '\\|')}\`${it.line ? ` (L${it.line})` : ''} | ` +
        `${it.message.replace(/\|/g, '\\|')} | ${sg || '-'} |`);
    });
    L.push('');
  }
  L.push('---', '', `**合计：${te} 错误 / ${tw} 警告 / ${ti} 提示**`);
  return L.join('\n');
}

function renderHtml(results, filtered, reportPath) {
  const shotDir = path.join(path.dirname(path.resolve(reportPath)), 'audit-shots');
  fs.mkdirSync(shotDir, { recursive: true });
  const shotMap = new Map();
  for (const r of results) {
    for (const s of r.shots || []) {
      const dst = path.join(shotDir, path.basename(s.file));
      try { fs.copyFileSync(s.file, dst); } catch { }
      shotMap.set(`${path.basename(r.file)}#${s.slide}`, path.relative(path.dirname(path.resolve(reportPath)), dst).replace(/\\/g, '/'));
    }
  }

  const cards = results.map(r => {
    const list = filtered.get(r.file) || [];
    const slides = r.slides.map(s => {
      const key = `${path.basename(r.file)}#${s.index}`;
      const img = shotMap.get(key);
      const items = list.filter(i => i.slide === s.index);
      const W = 720, scale = W / (s.width || 1280);
      const boxes = items.map((it, k) => {
        if (!it.rect) return '';
        const c = it.severity === 'error' ? '#e5342c' : it.severity === 'warning' ? '#f5a623' : '#2b7de9';
        return `<div class="abox" data-sev="${it.severity}" style="left:${(it.rect.rx * scale).toFixed(1)}px;top:${(it.rect.ry * scale).toFixed(1)}px;width:${(it.rect.w * scale).toFixed(1)}px;height:${(it.rect.h * scale).toFixed(1)}px;border-color:${c}" title="${esc(it.message)}"><span style="background:${c}">${k + 1}</span></div>`;
      }).join('');
      const rows = items.sort((a, b) => SEV[a.severity].order - SEV[b.severity].order).map((it, k) => {
        const sg = (it.data && it.data.suggestions || []).map(x =>
          `<div class="sug"><code>${x.from ? esc(x.from) + '</code> → <code>' + esc(x.to) : '新增 <code>' + esc(x.to)}</code>${x.note ? `<em>${esc(x.note)}</em>` : ''}</div>`).join('');
        return `<tr class="row-${it.severity}">
          <td class="num">${k + 1}</td>
          <td><span class="sev sev-${it.severity}">${SEV[it.severity].cn}</span></td>
          <td><b>${RULE_CN[it.rule] || it.rule}</b></td>
          <td><code class="path">${esc(it.path)}</code>${it.line ? `<div class="ln">源码 L${it.line}</div>` : ''}</td>
          <td>${it.text ? `<div class="txt">“${esc(it.text.slice(0, 60))}”</div>` : ''}<div class="msg">${esc(it.message)}</div>${sg ? `<div class="sugs">${sg}</div>` : ''}</td>
        </tr>`;
      }).join('');
      return `<div class="slide-card">
        <div class="shot-wrap" style="width:${W}px">
          ${img ? `<img src="${img}" width="${W}" loading="lazy">` : '<div class="noshot">无截图</div>'}
          <div class="anno">${boxes}</div>
        </div>
        <div class="side">
          <div class="side-h">第 ${s.index} 页 · ${s.width}×${s.height}
            <span class="cnt e">${s.counts.error} 错</span><span class="cnt w">${s.counts.warning} 警</span><span class="cnt i">${s.counts.info} 提</span>
          </div>
          ${items.length ? `<table class="issues"><tbody>${rows}</tbody></table>` : '<div class="ok">✓ 无问题</div>'}
        </div>
      </div>`;
    }).join('');
    return `<details class="file-card" open><summary><b>${esc(path.basename(r.file))}</b>
      <span class="fp">${esc(r.file)}</span>
      <span class="cnt e">${list.filter(i => i.severity === 'error').length} 错</span>
      <span class="cnt w">${list.filter(i => i.severity === 'warning').length} 警</span>
      <span class="cnt i">${list.filter(i => i.severity === 'info').length} 提</span></summary>
      ${slides}</details>`;
  }).join('');

  let te = 0, tw = 0, ti = 0;
  for (const [, list] of filtered) {
    te += list.filter(i => i.severity === 'error').length;
    tw += list.filter(i => i.severity === 'warning').length;
    ti += list.filter(i => i.severity === 'info').length;
  }

  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Slide Audit 报告</title><style>
*{box-sizing:border-box}body{margin:0;background:#0f1420;color:#dbe3f0;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:18px 24px;background:#161d2e;border-bottom:1px solid #26304a;position:sticky;top:0;z-index:9}
header h1{margin:0;font-size:18px}.sub{color:#7f8ba6;font-size:12px;margin-top:4px}
.tot{margin-left:auto;display:flex;gap:14px;align-items:center}
.sev{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:700;white-space:nowrap}
.sev-error{background:#3a1416;color:#ff7b74;border:1px solid #6d2320}
.sev-warning{background:#3a2c10;color:#ffc14d;border:1px solid #6d5320}
.sev-info{background:#12233a;color:#6cb0ff;border:1px solid #1e3f6b}
main{padding:18px 24px 60px}
.file-card{margin-bottom:22px;background:#141b2b;border:1px solid #26304a;border-radius:10px;overflow:hidden}
.file-card>summary{padding:12px 16px;cursor:pointer;display:flex;align-items:center;gap:10px;list-style:none}
.file-card>summary::-webkit-details-marker{display:none}
.file-card>summary::before{content:"▸";color:#6cb0ff;margin-right:2px}
.file-card[open]>summary::before{content:"▾"}
.fp{color:#6b7690;font-size:11px;font-weight:400}
.cnt{margin-left:6px;font-size:11px;padding:1px 7px;border-radius:9px}
.cnt.e{background:#3a1416;color:#ff7b74}.cnt.w{background:#3a2c10;color:#ffc14d}.cnt.i{background:#12233a;color:#6cb0ff}
.slide-card{display:flex;gap:16px;padding:14px 16px;border-top:1px solid #1e2739;align-items:flex-start;flex-wrap:wrap}
.shot-wrap{position:relative;flex:0 0 auto;background:#000;border-radius:6px;overflow:hidden;line-height:0}
.shot-wrap img{display:block;border-radius:6px}
.anno{position:absolute;inset:0}
.abox{position:absolute;border:2px dashed;background:rgba(229,52,44,.10);pointer-events:auto}
.abox span{position:absolute;left:0;top:-15px;color:#fff;font:700 10px/13px monospace;padding:0 4px;border-radius:2px}
.side{flex:1 1 460px;min-width:400px}
.side-h{font-size:12px;color:#93a0bb;margin-bottom:8px;display:flex;align-items:center;gap:6px}
table.issues{width:100%;border-collapse:collapse;font-size:12.5px}
table.issues td{padding:7px 8px;border-bottom:1px solid #1e2739;vertical-align:top}
table.issues td.num{color:#5d6880;width:22px}
tr.row-error td{background:rgba(229,52,44,.06)}
tr.row-warning td{background:rgba(245,166,35,.05)}
code.path{color:#8fd0ff;font-size:11.5px;word-break:break-all}
.ln{color:#6b7690;font-size:11px;margin-top:2px}
.txt{color:#c8d3e6;margin-bottom:3px}
.msg{color:#9aa7c0}
.sugs{margin-top:5px}
.sug{background:#0d1a2b;border:1px solid #1e3554;border-radius:5px;padding:3px 7px;margin-top:3px;font-size:11.5px;color:#8fd0ff}
.sug code{background:#123;color:#ffd479;padding:0 3px;border-radius:3px}
.sug em{color:#6b7690;font-style:normal;margin-left:6px}
.ok{color:#4ad07f;padding:10px}
.noshot{width:720px;height:200px;display:flex;align-items:center;justify-content:center;color:#5d6880;background:#0a0e17}
.toolbar{display:flex;gap:10px;align-items:center;font-size:12px;color:#93a0bb;margin-bottom:14px}
.toolbar label{cursor:pointer;user-select:none}
.empty{padding:40px;text-align:center;color:#4ad07f;font-size:16px}
</style></head><body>
<header><div style="display:flex;align-items:center;gap:16px">
  <div><h1>Slide Audit · HTML 幻灯片排版体检</h1><div class="sub">${new Date().toLocaleString('zh-CN')} · ${results.length} 个文件 · ${results.reduce((s, r) => s + r.slides.length, 0)} 页</div></div>
  <div class="tot"><span class="sev sev-error">${te} 错误</span><span class="sev sev-warning">${tw} 警告</span><span class="sev sev-info">${ti} 提示</span></div>
</div></header>
<main>
<div class="toolbar">
  <label><input type="checkbox" id="tgErr" checked> 错误</label>
  <label><input type="checkbox" id="tgWarn" checked> 警告</label>
  <label><input type="checkbox" id="tgInfo" checked> 提示</label>
  <label><input type="checkbox" id="tgBox" checked> 显示标注框</label>
</div>
${te + tw + ti === 0 ? '<div class="empty">✓ 未发现任何排版问题</div>' : cards}
</main>
<script>
const map={error:'tgErr',warning:'tgWarn',info:'tgInfo'};
function apply(){
  for(const k in map){const on=document.getElementById(map[k]).checked;
    document.querySelectorAll('.abox[data-sev="'+k+'"]').forEach(e=>e.style.display=on?'':'none');
    document.querySelectorAll('tr.row-'+k).forEach(e=>e.style.display=on?'':'none');}
  document.querySelectorAll('.anno').forEach(e=>e.style.display=document.getElementById('tgBox').checked?'':'none');
}
['tgErr','tgWarn','tgInfo','tgBox'].forEach(id=>document.getElementById(id).addEventListener('change',apply));
apply();
</script></body></html>`;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ------------------------------ run ------------------------------ */

(async function main() {
  let files = resolveInputs(opts.inputs);
  if (!files.length) { console.error('没有匹配到任何 HTML 文件'); process.exit(2); }

  const jobs = [];
  const tmpTpl = path.join(tmpRoot, 'tpl');
  fs.mkdirSync(tmpTpl, { recursive: true });
  for (const f of files) {
    const src = fs.readFileSync(f, 'utf8');
    const tpls = extractTemplates(f, tmpTpl);
    if (tpls.length) {
      // 模板型：拆开检查，但结果归属原文件
      tpls.forEach(t => jobs.push({ file: t.file, origin: f, name: t.name, group: f, lineOffset: t.lineOffset }));
    } else {
      jobs.push({ file: f, origin: f, group: f, lineOffset: 0 });
    }
  }

  const t0 = Date.now();
  await launch();
  const rawResults = [];
  for (const j of jobs) {
    try {
      const r = await auditFile(j.file, j);
      if (r.skipped) { console.log(`[skip] ${path.basename(j.group)}：${r.meta.reason || '非幻灯片页面'}`); continue; }
      r.file = j.group;                 // 模板型统一归属原文件
      r.slides.forEach((s, i) => { s.index = i + 1; });
      rawResults.push(r);
    } catch (e) {
      console.warn(`[warn] 检查失败 ${j.file}: ${e.message}`);
    }
  }

  // 合并同组（模板型）结果
  const grouped = new Map();
  for (const r of rawResults) {
    if (!grouped.has(r.file)) grouped.set(r.file, { file: r.file, slides: [], issues: [], stats: { error: 0, warning: 0, info: 0 }, shots: [] });
    const g = grouped.get(r.file);
    const base = g.slides.length;
    r.issues.forEach(i => { i.slide = (i.slide || 1) + base; });
    r.slides.forEach((s, i) => { s.index = base + i + 1; g.slides.push(s); });
    g.issues = g.issues.concat(r.issues);
    g.shots = g.shots.concat(r.shots.map(s => ({ ...s, slide: s.slide + base })));
    for (const k in r.stats) g.stats[k] = (g.stats[k] || 0) + r.stats[k];
  }
  const results = [...grouped.values()];
  results.sort((a, b) => a.file.localeCompare(b.file));

  // baseline 对比
  const filtered = new Map();
  let baselineSet = null;
  if (opts.baseline && fs.existsSync(opts.baseline)) {
    try {
      const b = JSON.parse(fs.readFileSync(opts.baseline, 'utf8'));
      baselineSet = new Set((b.issues || []).map(fingerprint));
    } catch { }
  }
  for (const r of results) {
    let list = r.issues;
    if (baselineSet) {
      list = list.filter(i => !baselineSet.has(fingerprint(i)));
      r.deltaMode = true;
    }
    filtered.set(r.file, list);
  }

  const text = renderText(results, filtered);
  if (!opts.quiet) console.log(text); else {
    let te = 0, tw = 0, ti = 0;
    for (const [, l] of filtered) { te += l.filter(i => i.severity === 'error').length; tw += l.filter(i => i.severity === 'warning').length; ti += l.filter(i => i.severity === 'info').length; }
    console.log(`Slide Audit: ${te} 错误 / ${tw} 警告 / ${ti} 提示  (${results.length} 文件, ${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  }

  // 输出
  const allIssues = [];
  for (const r of results) (filtered.get(r.file) || []).forEach(i => allIssues.push(i));
  const jsonObj = {
    generatedAt: new Date().toISOString(),
    options: { engine: opts.engine, rules: opts.rules },
    files: results.map(r => ({
      file: r.file, slides: r.slides.map(s => ({ index: s.index, width: s.width, height: s.height, counts: s.counts }))
    })),
    stats: {
      error: allIssues.filter(i => i.severity === 'error').length,
      warning: allIssues.filter(i => i.severity === 'warning').length,
      info: allIssues.filter(i => i.severity === 'info').length
    },
    issues: allIssues
  };
  if (opts.json) { fs.writeFileSync(path.resolve(opts.json), JSON.stringify(jsonObj, null, 2), 'utf8'); console.log(`\nJSON  → ${path.resolve(opts.json)}`); }
  if (opts.md) { fs.writeFileSync(path.resolve(opts.md), renderMarkdown(results, filtered), 'utf8'); console.log(`MD    → ${path.resolve(opts.md)}`); }
  if (opts.out) {
    const p = path.resolve(opts.out);
    fs.writeFileSync(p, renderHtml(results, filtered, p), 'utf8');
    console.log(`HTML  → ${p}`);
    if (opts.open) {
      const { execSync } = await import('node:child_process');
      try {
        if (process.platform === 'win32') {
          execSync(`start "" "${p}"`, { shell: 'cmd.exe' });
        } else if (process.platform === 'darwin') {
          execSync(`open "${p}"`);
        } else {
          execSync(`xdg-open "${p}"`);
        }
      } catch { }
    }
  }
  if (opts.shots) console.log(`PNG   → ${path.resolve(opts.shots)}`);

  // 退出码
  if (opts.failOn !== 'none') {
    const lv = opts.failOn === 'error' ? ['error'] : ['error', 'warning'];
    if (allIssues.some(i => lv.includes(i.severity))) process.exitCode = 1;
  }

  killChrome();
  setTimeout(() => process.exit(process.exitCode || 0), 120);
})().catch(e => {
  console.error('[fatal]', e);
  killChrome();
  process.exit(1);
});
