---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'e0ec68b9-de1e-4210-bcd5-716733aaa9fe'
  PropagateID: 'e0ec68b9-de1e-4210-bcd5-716733aaa9fe'
  ReservedCode1: '7d4ee422-53cc-479b-bdda-1f4bd15c2800'
  ReservedCode2: '7d4ee422-53cc-479b-bdda-1f4bd15c2800'
---

| 维度      | 规范                                         |
| ------- | ------------------------------------------ |
| **主色调** | 由 `color-themes.json` 选定主题决定（默认科技蓝） |
| **背景**  | 由主题 `background` 字段定义                    |
| **文字**  | 由主题 `text` 字段定义                          |
| **卡片**  | 圆角 12-16px，轻微阴影，渐变填充                       |
| **字号**  | 最小 18px（页脚），正文 24px，数据展示 56-72px           |
| **页面**  | 1280×768px 固定尺寸                            |



/* ============================================
   PPT页面CSS设计系统 - 配色由 color-themes.json 选定主题注入
   结构变量(圆角/字号/间距等)所有主题共享，颜色变量从主题注入
   ============================================ */

/* ---- 基础变量定义 ---- */

/* === 结构变量（所有主题共享，不随主题变化）=== */
:root {
  /* 圆角 */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
  --radius-full: 9999px;
  
  /* 字体 */
  --font-primary: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "SF Mono", "Fira Code", Consolas, monospace;
  
  /* 字号规范 (最小18px) */
  --text-xs: 18px;    /* 注释、页脚 */
  --text-sm: 22px;    /* 辅助文字 */
  --text-base: 24px;  /* 正文 */
  --text-lg: 28px;    /* 小标题 */
  --text-xl: 32px;    /* 模块标题 */
  --text-2xl: 40px;   /* 大标题 */
  --text-3xl: 56px;   /* 数据展示 */
  --text-4xl: 72px;   /* 核心数据 */
  
  /* 间距 */
  --space-xs: 12px;
  --space-sm: 20px;
  --space-md: 32px;
  --space-lg: 48px;
  --space-xl: 64px;
  
  /* 页面尺寸 */
  --slide-width: 1280px;
  --slide-height: 768px;
  --header-height: 80px;
  --footer-height: 60px;
}

/* === 颜色变量（以下值为 tech-blue 默认值，生成HTML时从 color-themes.json 选定主题注入）=== */
:root {
  /* 主色调 - 从主题 primary 字段注入 */
  --primary-blue: #1e5bb5;   /* ← primary.main */
  --primary-dark: #0d3a7a;   /* ← primary.dark */
  --primary-light: #4a90e2;  /* ← primary.light */
  --accent-blue: #2b7de9;    /* ← primary.accent */
  
  /* 渐变色 - 从主题 gradients 字段注入 */
  --gradient-blue: linear-gradient(135deg, #1e5bb5 0%, #2b7de9 100%);
  --gradient-light: linear-gradient(135deg, #e8f0fe 0%, #d4e4fc 100%);
  --gradient-card: linear-gradient(135deg, #f0f5ff 0%, #e6efff 100%);
  
  /* 中性色 - 从主题 background/text/border 字段注入 */
  --white: #ffffff;          /* ← background.main */
  --bg-gray: #f5f7fa;       /* ← background.secondary */
  --text-primary: #1a1a2e;  /* ← text.primary */
  --text-secondary: #4a5568;/* ← text.secondary */
  --text-muted: #718096;    /* ← text.muted */
  --border-light: #e2e8f0;  /* ← border.light */
  --border-card-tint: rgba(30, 91, 181, 0.1); /* ← border.card_tint */
  
  /* 渐变底/深色底上的文字色 - 从主题 text_on_primary 字段注入 */
  --text-on-primary: #ffffff;
  
  /* 渐变底上的标签底色 - 从主题 tag_bg_on_primary 字段注入 */
  --tag-bg-on-primary: rgba(255, 255, 255, 0.95);
  
  /* 阴影系统 - 从主题 shadows 字段注入 */
  --shadow-sm: 0 2px 4px rgba(30, 91, 181, 0.08);
  --shadow-md: 0 4px 12px rgba(30, 91, 181, 0.12);
  --shadow-lg: 0 8px 24px rgba(30, 91, 181, 0.15);
  --shadow-xl: 0 12px 32px rgba(30, 91, 181, 0.2);
}

/* ---- 重置与基础 ---- */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-primary);
  background: var(--bg-gray);
  color: var(--text-primary);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

/* ---- 页面容器 ---- */
.slide-container {
  width: var(--slide-width);
  height: var(--slide-height);
  background: var(--white);
  position: relative;
  overflow: hidden;
  margin: 0 auto;
  box-shadow: var(--shadow-lg);
}

/* ---- 顶部导航栏 ---- */
.slide-header {
  height: var(--header-height);
  padding: 0 var(--space-lg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-light);
  background: var(--white);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.logo {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--primary-dark);
  letter-spacing: 2px;
}

.company-name {
  font-size: var(--text-sm);
  color: var(--text-muted);
  border-left: 2px solid var(--border-light);
  padding-left: var(--space-sm);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.header-icon {
  width: 24px;
  height: 24px;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.3s;
}

.header-icon:hover {
  opacity: 1;
}

/* ---- 主内容区 ---- */
.slide-content {
  height: calc(var(--slide-height) - var(--header-height) - var(--footer-height));
  padding: var(--space-lg);
  display: flex;
  gap: var(--space-lg);
  overflow: hidden;
}

/* ---- 左侧标题区 ---- */
.content-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.section-title {
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--primary-dark);
  line-height: 1.3;
  position: relative;
  padding-left: var(--space-sm);
}

.section-title::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 80%;
  background: var(--gradient-blue);
  border-radius: var(--radius-full);
}

/* ---- 右侧内容区 ---- */
.content-right {
  flex: 1.2;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

/* ---- 数据展示模块 ---- */
.data-highlight {
  display: flex;
  align-items: baseline;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.data-number {
  font-size: var(--text-4xl);
  font-weight: 800;
  color: var(--primary-blue);
  line-height: 1;
  letter-spacing: -2px;
}

.data-unit {
  font-size: var(--text-2xl);
  color: var(--primary-blue);
  font-weight: 600;
}

.data-arrow {
  width: 48px;
  height: 48px;
  margin-left: var(--space-xs);
}

.data-label {
  font-size: var(--text-base);
  color: var(--text-secondary);
  text-align: right;
}

.data-date {
  font-size: var(--text-sm);
  color: var(--text-muted);
  text-align: right;
}

/* ---- 卡片组件 ---- */
.card {
  background: var(--white);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--shadow-md);
  border: 1px solid var(--border-light);
  transition: transform 0.3s, box-shadow 0.3s;
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.card-blue {
  background: var(--gradient-blue);
  color: var(--text-on-primary);
  border: none;
}

.card-light {
  background: var(--gradient-card);
  border: 1px solid var(--border-card-tint);
}

.card-tag {
  display: inline-block;
  background: var(--white);
  color: var(--primary-blue);
  padding: var(--space-xs) var(--space-md);
  border-radius: var(--radius-full);
  font-size: var(--text-base);
  font-weight: 600;
  margin-bottom: var(--space-md);
  box-shadow: var(--shadow-sm);
}

.card-blue .card-tag {
  background: var(--tag-bg-on-primary);
}

/* ---- 数据网格 ---- */
.data-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-md);
  margin-top: var(--space-sm);
}

.data-item {
  text-align: center;
}

.data-item-label {
  font-size: var(--text-sm);
  color: var(--text-on-primary);
  margin-bottom: var(--space-xs);
}

.card-blue .data-item-label {
  color: var(--text-on-primary);
}

.data-item-value {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-on-primary);
}

/* ---- 增长曲线模块 ---- */
.growth-section {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  margin-top: var(--space-sm);
}

.growth-chart {
  flex: 1;
  height: 120px;
  position: relative;
}

/* ---- 特性列表 ---- */
.feature-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.feature-item {
  display: flex;
  gap: var(--space-md);
  align-items: flex-start;
}

.feature-number {
  width: 48px;
  height: 48px;
  background: var(--gradient-blue);
  color: var(--text-on-primary);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-lg);
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: var(--shadow-md);
}

.feature-content {
  flex: 1;
  background: var(--white);
  padding: var(--space-md);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  border-left: 3px solid var(--primary-light);
}

.feature-title {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--primary-dark);
  margin-bottom: var(--space-xs);
}

.feature-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
}

/* ---- 中央图标组 ---- */
.icon-cluster {
  position: relative;
  width: 280px;
  height: 280px;
  margin: 0 auto;
}

.icon-circle {
  position: absolute;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: var(--gradient-blue);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-lg);
  transition: transform 0.3s;
}

.icon-circle:hover {
  transform: scale(1.05);
}

.icon-circle:nth-child(1) { top: 0; left: 80px; }
.icon-circle:nth-child(2) { top: 80px; left: 0; }
.icon-circle:nth-child(3) { top: 80px; right: 0; }
.icon-circle:nth-child(4) { bottom: 0; left: 80px; }

.icon-circle svg {
  width: 48px;
  height: 48px;
  fill: none;
  stroke: var(--text-on-primary);
  stroke-width: 2;
}

/* ---- 底部栏 ---- */
.slide-footer {
  height: var(--footer-height);
  background: var(--gradient-blue);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-lg);
  color: var(--text-on-primary);
}

.footer-left {
  font-size: var(--text-base);
  font-weight: 600;
  letter-spacing: 2px;
}

.footer-right {
  font-size: var(--text-xs);
  opacity: 0.9;
  letter-spacing: 4px;
}

/* ---- 文字排版工具类 ---- */
.text-center { text-align: center; }
.text-right { text-align: right; }
.text-left { text-align: left; }

.font-bold { font-weight: 700; }
.font-semibold { font-weight: 600; }

.text-primary { color: var(--primary-blue); }
.text-dark { color: var(--primary-dark); }
.text-secondary { color: var(--text-secondary); }
.text-muted { color: var(--text-muted); }
.text-white { color: var(--text-on-primary); }

/* ---- 布局工具类 ---- */
.flex { display: flex; }
.flex-col { flex-direction: column; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.gap-sm { gap: var(--space-sm); }
.gap-md { gap: var(--space-md); }
.gap-lg { gap: var(--space-lg); }

/* ---- 装饰元素 ---- */
.divider {
  width: 100%;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-light), transparent);
  margin: var(--space-md) 0;
}

.accent-line {
  width: 40px;
  height: 4px;
  background: var(--gradient-blue);
  border-radius: var(--radius-full);
  margin-bottom: var(--space-sm);
}

/* ---- 响应式适配 ---- */
@media (max-width: 1320px) {
  .slide-container {
    transform: scale(0.9);
    transform-origin: top center;
  }
}

@media (max-width: 768px) {
  :root {
    --slide-width: 100vw;
    --slide-height: auto;
    --text-4xl: 48px;
    --text-3xl: 36px;
  }
  
  .slide-content {
    flex-direction: column;
    height: auto;
  }
  
  .data-grid {
    grid-template-columns: 1fr;
  }
  
  .icon-cluster {
    transform: scale(0.8);
  }
}

/* ---- 打印优化 ---- */
@media print {
  .slide-container {
    box-shadow: none;
    page-break-after: always;
  }
  
  body {
    background: white;
  }
}

> AI生成