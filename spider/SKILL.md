---
name: spider
description: "Web scraping skill that uses browser automation (Playwright + CDP) and LLM cleaning to extract any webpage into clean Markdown. Use when the user asks to scrape, crawl, extract, or fetch webpage content, convert web pages to Markdown, or needs to access web content that requires browser rendering or authentication. Triggers: scrape website, extract webpage content, web to markdown, crawl page, 爬取网页, 抓取网页, 提取网页内容, 网页转Markdown."
name_cn: 网页爬取
description_cn: "浏览器自动化 + LLM 清洗，将任意网页内容提取为干净的 Markdown 文件"
create_source: super-agent-skill-creator
---

# Spider - Web Scraping Skill

Extract any webpage into clean Markdown via browser automation + LLM cleaning.

## Prerequisites

Before first use, ensure environment is ready:

```bash
# Check Playwright environment
node <SKILL_DIR>/scripts/install-check.js

# If not installed, install dependencies:
npm install playwright turndown
npx playwright install chromium
```

- **Node.js** >= 16 required
- **Chrome browser** installed on the system
- `playwright` and `turndown` (optional, for better HTML-to-MD conversion) npm packages

## Workflow

```
User provides URL
       |
       v
  [1. Pre-check] <-- Validate URL, check config, create dirs
       |
       v
  [2. Browser Scrape] <-- Run scrape-page.js → temp/raw.md
       |
   +---+---+
   |       |
  OK     FAIL → Report error + screenshot → END
   |
   v
  [3. LLM Clean] <-- Read raw.md, remove noise → output/<domain>-<date>.md
       |
       v
  [4. Summary] <-- Report results to user
```

## Step 1: Pre-check

1. Extract and validate URL from user input (must start with `http://` or `https://`)
2. Check if `settings.json` exists in current working directory; if not, inform user:
   - Copy `<SKILL_DIR>/assets/settings.example.json` to working directory as `settings.json`
   - Fill in site credentials if authentication is needed
   - If no auth needed, proceed with defaults
3. Ensure `temp/` and `output/` directories exist (create if missing)

## Step 2: Browser Scrape

Run the scrape script via terminal:

```bash
node "<SKILL_DIR>/scripts/scrape-page.js" [--config <settings_path>] <url>
```

- `<SKILL_DIR>`: the directory where this SKILL.md resides
- `--config`: optional, path to settings.json (defaults to `./settings.json` in cwd)
- `<url>`: the target URL to scrape

The script:
1. Attempts CDP connection to `localhost:9222` (reuse existing Chrome session with login state)
2. Falls back to launching new Chrome window if CDP fails
3. Handles authentication (Basic Auth / form login) per settings.json
4. Loads page, waits for render, extracts HTML → Markdown
5. Writes raw content to `temp/raw.md`
6. Outputs JSON status to stdout

**Parse the JSON output**:
- `status: "success"` → record `title`, `rawPath`, `contentLength`, `mode`; proceed to Step 3
- `status: "error"` → report error to user, mention screenshot if saved, do NOT proceed to Step 3

### CDP Mode (Reuse Browser Login State)

To share an already-logged-in Chrome session:

1. Close all Chrome windows
2. Relaunch Chrome with debug port:
   ```powershell
   # Windows
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
   ```
3. Log into target website in Chrome
4. Run spider - it will auto-detect CDP and share cookies/login state

## Step 3: LLM Clean

Read `temp/raw.md` and perform content cleaning:

**Remove noise**:
- Navigation bars, menus, breadcrumbs
- Sidebars, related article recommendations
- Ads, promotional content
- Footers, copyright info
- Comment sections (unless it's a documentation-style page)
- Excessive blank lines and line breaks

**Preserve structure**:
- Heading hierarchy (H1-H6)
- Body paragraphs
- Code blocks with syntax highlighting markers
- Tables
- Ordered/unordered lists
- Image alt text and src (keep references)
- Link text and href (keep references)

**Optimize**:
- Fix broken paragraphs
- Merge truncated sentences
- Normalize heading numbering
- Remove zero-width characters and garbled text

**If raw content is very short (< 500 chars)**: keep as-is, skip cleaning.

**Output file**: `output/<domain>-<date>.md`
- `<domain>`: hostname from URL (e.g. `docs.example.com`)
- `<date>`: `YYYYMMDD` format

Add header metadata to the output file:

```markdown
# <Page Title>

> Source: <original URL>
> Scraped at: <ISO timestamp>
> Cleaned at: <current time>

---

<cleaned content>
```

## Step 4: Summary

Report to user:

```
Scraping complete!

  Page title: <title>
  Source URL: <url>
  Browser mode: <cdp|launch>
  Raw content: <N> chars
  Cleaned: <M> chars
  Output: output/<filename>.md
  Removed: <brief list of noise removed>
```

## Safety & Compliance Rules

- **Do not scrape sensitive content**: personal info, passwords, keys, tokens. If detected, stop and inform user.
- **Respect robots.txt**: check before scraping. If path is disallowed, inform user and ask to confirm.
- **Rate limiting**: one page per invocation. Do not fire multiple requests to the same domain in short succession.
- **Credential security**: passwords/tokens from settings.json must NEVER appear in output, logs, or error messages.
- **Environment variables**: `${ENV_VAR}` values are masked as `***` in any output.
- **No silent failures**: all errors and warnings must be reported to user.
- **Output fidelity**: cleaning stage only removes noise and formats content — do NOT add, modify, or translate original content. Preserve original language.
- **Timeout**: page load timeout is 60 seconds. If exceeded, capture already-loaded content and inform user it may be incomplete.

## Error Recovery

| Error | Action |
|-------|--------|
| Playwright not installed | Tell user: `npm install playwright && npx playwright install chromium` |
| Chrome not installed | Playwright requires system Chrome. Tell user to install Chrome. |
| CDP connection failed | Auto-fallback to launch mode. Inform user about CDP mode for login reuse. |
| Auth failed | Check settings.json credentials and environment variables. |
| Page load timeout | Capture partial content, save screenshot, inform user. |
| settings.json not found | Continue with defaults. Inform user about settings.example.json for auth config. |

## Config Reference

See [assets/settings.example.json](assets/settings.example.json) for the full config template.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `browser` | string | `"chrome"` | Browser: chrome, chromium, firefox, edge |
| `headless` | boolean | `false` | Headless mode |
| `keepOpen` | boolean | `false` | Keep browser open after scrape |
| `cdpPort` | number | `9222` | CDP debug port |
| `outputDir` | string | `"output"` | Final MD output directory |
| `tempDir` | string | `"temp"` | Temp files directory |
| `sites` | object | `{}` | Per-domain auth config |
