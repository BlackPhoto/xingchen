# 交互增强包（L1 级，跨模式可选叠加）

本文件定义 5 种轻量交互组件，**任何模式**生成的 HTML 均可按需叠加。每个组件自包含 CSS + JS 片段，不依赖骨架文件中已有样式。

**使用原则**：
- 仅当用户明确要求"可交互/可筛选/Tab 切换/可折叠"等交互功能时，从本包选取对应组件内联到生成的 HTML 中
- 不主动添加，除非用户要求
- 交互组件属于 L1 级（轻量 JS），转 Word/PDF/Markdown 时按降级表处理，影响分析会列出
- 内联 JS 总量控制在 ~2KB 以内，保持离线自包含

**display 切换一致性规则（强制）**：

元素的显隐控制**不可混用** CSS class 切换与内联 `style.display`，否则内联样式（优先级 1000）会覆盖 class 选择器（优先级 20），导致后续 class 切换失效。每个元素的显隐只允许使用以下两种模式之一：

- **模式 A — 纯 class 切换**（推荐）：CSS 中定义 `.xxx { display:none }` / `.xxx.visible { display:flex }`，JS 中只通过 `classList.add/remove/toggle('visible')` 控制
- **模式 B — 纯内联切换**：JS 中直接 `el.style.display='none'/'flex'`，不依赖 CSS class 做显隐判断

> **典型错误**：在 `retry()` 中先 `el.style.display='none'` 再 `classList.remove('visible')`，之后 `seekAnswer()` 中只 `classList.add('visible')`——内联 `display:none` 覆盖了 class 的 `display:flex`，导致元素永远不可见。修正：要么删掉内联 display 设置（统一用模式 A），要么在添加 class 前清除内联值 `el.style.display=''`。

---

## 降级总表

| 交互组件 | HTML 效果 | 转 Word | 转 PDF | 转 Markdown |
|---|---|---|---|---|
| Tab 切换 | 点击切换面板 | 全部面板展开（内容不丢） | 全部面板展开 | 全部内容保留 |
| 表格搜索 | 实时过滤行 | 保留完整表格（无搜索） | 保留完整表格（无搜索） | 保留完整表格 |
| 折叠展开 | 点击展开/收起 | 全部展开为段落 | 全部展开为段落 | 全部内容保留 |
| 代码复制 | 一键复制按钮 | 按钮丢失，代码保留 | 按钮丢失，代码保留 | 按钮丢失，代码保留 |
| 返回顶部 | 浮动按钮平滑滚动 | 按钮丢失（无影响） | 按钮丢失（无影响） | 按钮丢失（无影响） |

> **降级原则**：交互丢失不等于内容丢失。所有面板/折叠/表格的**内容**在转换后完整保留，只是丢失了交互行为本身。

---

## 1. Tab 切换

**适用场景**：多章节内容切换、多维度数据展示、A/B 方案对比展开

**适用模式**：全部

### CSS（内联到 `<style>` 块尾部）

```css
/* ========== 交互增强：Tab 切换 ========== */
.tab-nav { display: flex; gap: 0; border-bottom: 2px solid {border}; margin: 0 0 16px 0; flex-wrap: wrap; }
.tab-btn {
  padding: 10px 20px; border: none; background: transparent;
  font-size: 14px; color: {text_secondary}; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -2px;
  transition: color 0.2s, border-color 0.2s; font-family: inherit;
}
.tab-btn:hover { color: {primary}; }
.tab-btn.active { color: {primary}; border-bottom-color: {accent}; font-weight: 600; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
```

### HTML 结构

```html
<div class="tab-nav" role="tablist">
  <button class="tab-btn active" data-tab="0" role="tab">{标签1}</button>
  <button class="tab-btn" data-tab="1" role="tab">{标签2}</button>
  <button class="tab-btn" data-tab="2" role="tab">{标签3}</button>
</div>
<div class="tab-panel active" data-panel="0" role="tabpanel">{面板1内容}</div>
<div class="tab-panel" data-panel="1" role="tabpanel">{面板2内容}</div>
<div class="tab-panel" data-panel="2" role="tabpanel">{面板3内容}</div>
```

### JS（内联到 `</body>` 前）

```html
<script>
(function(){
  var navs=document.querySelectorAll('.tab-nav');
  navs.forEach(function(nav){
    var btns=nav.querySelectorAll('.tab-btn');
    btns.forEach(function(btn){
      btn.addEventListener('click',function(){
        var idx=btn.getAttribute('data-tab');
        btns.forEach(function(b){b.classList.remove('active');});
        btn.classList.add('active');
        var panels=nav.parentElement.querySelectorAll('.tab-panel');
        panels.forEach(function(p){
          p.classList.toggle('active',p.getAttribute('data-panel')===idx);
        });
      });
    });
  });
})();
</script>
```

### 使用示例

```html
<div>
  <div class="tab-nav" role="tablist">
    <button class="tab-btn active" data-tab="0" role="tab">桌面端</button>
    <button class="tab-btn" data-tab="1" role="tab">移动端</button>
    <button class="tab-btn" data-tab="2" role="tab">API</button>
  </div>
  <div class="tab-panel active" data-panel="0" role="tabpanel">
    <p class="paragraph">桌面端操作流程...</p>
  </div>
  <div class="tab-panel" data-panel="1" role="tabpanel">
    <p class="paragraph">移动端操作流程...</p>
  </div>
  <div class="tab-panel" data-panel="2" role="tabpanel">
    <p class="paragraph">API 接口说明...</p>
  </div>
</div>
```

---

## 2. 表格搜索

**适用场景**：数据表格行数较多时，实时过滤匹配行

**适用模式**：全部含 `.table` 的模式

### CSS（内联到 `<style>` 块尾部）

```css
/* ========== 交互增强：表格搜索 ========== */
.table-search-wrap { margin: 0 0 12px 0; }
.table-search-input {
  width: 100%; max-width: 320px; padding: 8px 14px;
  border: 1px solid {border}; border-radius: 8px;
  font-size: 14px; color: {text}; font-family: inherit;
  background: {card}; outline: none;
  transition: border-color 0.2s;
}
.table-search-input:focus { border-color: {accent}; }
.table-search-input::placeholder { color: {text_secondary}; }
.table-row-hidden { display: none; }
.table-no-result { display: none; padding: 12px; color: {text_secondary}; font-size: 14px; text-align: center; }
```

### HTML 结构

```html
<div class="table-search-wrap">
  <input type="text" class="table-search-input" placeholder="搜索表格内容..." data-target="{table-id}">
</div>
<table class="table" id="{table-id}" data-caption="{表格标题}">
  <!-- 表格内容 -->
</table>
<div class="table-no-result" data-nomatch="{table-id}">未找到匹配项</div>
```

### JS（内联到 `</body>` 前）

```html
<script>
(function(){
  var inputs=document.querySelectorAll('.table-search-input');
  inputs.forEach(function(input){
    input.addEventListener('input',function(){
      var kw=input.value.trim().toLowerCase();
      var tid=input.getAttribute('data-target');
      var table=document.getElementById(tid);
      if(!table) return;
      var rows=table.querySelectorAll('tbody tr');
      var visible=0;
      rows.forEach(function(row){
        var text=row.textContent.toLowerCase();
        var match=!kw||text.indexOf(kw)>=0;
        row.classList.toggle('table-row-hidden',!match);
        if(match) visible++;
      });
      var nomatch=document.querySelector('[data-nomatch="'+tid+'"]');
      if(nomatch) nomatch.style.display=visible===0?'block':'none';
    });
  });
})();
</script>
```

---

## 3. 折叠展开

**适用场景**：FAQ 问答、多层详情、长报告章节折叠

**适用模式**：全部

### CSS（内联到 `<style>` 块尾部）

```css
/* ========== 交互增强：折叠展开 ========== */
.collapse-item { border-bottom: 1px solid {border}; }
.collapse-item:last-child { border-bottom: none; }
.collapse-trigger {
  width: 100%; padding: 14px 0; border: none; background: transparent;
  font-size: 15px; color: {primary}; cursor: pointer; text-align: left;
  display: flex; justify-content: space-between; align-items: center;
  font-family: inherit; font-weight: 600;
}
.collapse-trigger:hover { color: {accent}; }
.collapse-arrow { font-size: 12px; color: {text_secondary}; transition: transform 0.2s; }
.collapse-trigger.expanded .collapse-arrow { transform: rotate(90deg); }
.collapse-body { max-height: 0; overflow: hidden; transition: max-height 0.3s ease; }
.collapse-body.expanded { max-height: 2000px; }
.collapse-body-inner { padding: 0 0 14px 0; }
```

### HTML 结构

```html
<div class="collapse-item">
  <button class="collapse-trigger" data-collapse="0">
    <span>{标题}</span>
    <span class="collapse-arrow">▶</span>
  </button>
  <div class="collapse-body" data-body="0">
    <div class="collapse-body-inner">{折叠内容}</div>
  </div>
</div>
```

### JS（内联到 `</body>` 前）

```html
<script>
(function(){
  var triggers=document.querySelectorAll('.collapse-trigger');
  triggers.forEach(function(trigger){
    trigger.addEventListener('click',function(){
      var idx=trigger.getAttribute('data-collapse');
      var body=document.querySelector('[data-body="'+idx+'"]');
      if(!body) return;
      var expanded=trigger.classList.toggle('expanded');
      body.classList.toggle('expanded',expanded);
    });
  });
})();
</script>
```

### 使用示例

```html
<div class="card" style="padding:8px 24px;">
  <div class="collapse-item">
    <button class="collapse-trigger" data-collapse="0">
      <span>常见问题：如何注册账号？</span>
      <span class="collapse-arrow">▶</span>
    </button>
    <div class="collapse-body" data-body="0">
      <div class="collapse-body-inner">
        <p class="paragraph">点击首页"注册"按钮，填写邮箱和密码即可完成注册。</p>
      </div>
    </div>
  </div>
  <div class="collapse-item">
    <button class="collapse-trigger" data-collapse="1">
      <span>常见问题：如何修改密码？</span>
      <span class="collapse-arrow">▶</span>
    </button>
    <div class="collapse-body" data-body="1">
      <div class="collapse-body-inner">
        <p class="paragraph">登录后进入"账号设置"→"修改密码"。</p>
      </div>
    </div>
  </div>
</div>
```

---

## 4. 代码复制

**适用场景**：代码块一键复制到剪贴板

**适用模式**：含 `.code` 语义 class 的模式（mode-doc、mode-explainer 等）

### CSS（内联到 `<style>` 块尾部）

```css
/* ========== 交互增强：代码复制 ========== */
.code-wrap { position: relative; }
.code-copy-btn {
  position: absolute; top: 8px; right: 8px;
  padding: 4px 12px; border: 1px solid rgba(255,255,255,0.2);
  background: rgba(255,255,255,0.1); color: #e2e8f0;
  font-size: 12px; border-radius: 6px; cursor: pointer;
  font-family: inherit; transition: background 0.2s; opacity: 0;
}
.code-wrap:hover .code-copy-btn { opacity: 1; }
.code-copy-btn:hover { background: rgba(255,255,255,0.2); }
.code-copy-btn.copied { background: rgba(34,197,94,0.3); border-color: rgba(34,197,94,0.5); }
```

### HTML 结构

```html
<div class="code-wrap">
  <button class="code-copy-btn">复制</button>
  <pre class="code" data-lang="{语言}"><code>{代码内容}</code></pre>
</div>
```

### JS（内联到 `</body>` 前）

```html
<script>
(function(){
  var btns=document.querySelectorAll('.code-copy-btn');
  btns.forEach(function(btn){
    btn.addEventListener('click',function(){
      var wrap=btn.closest('.code-wrap');
      var code=wrap.querySelector('code');
      if(!code) return;
      var text=code.textContent;
      if(navigator.clipboard){
        navigator.clipboard.writeText(text).then(function(){
          btn.textContent='已复制'; btn.classList.add('copied');
          setTimeout(function(){btn.textContent='复制';btn.classList.remove('copied');},2000);
        });
      }else{
        var ta=document.createElement('textarea');ta.value=text;
        document.body.appendChild(ta);ta.select();
        try{document.execCommand('copy');
          btn.textContent='已复制';btn.classList.add('copied');
          setTimeout(function(){btn.textContent='复制';btn.classList.remove('copied');},2000);
        }catch(e){}
        document.body.removeChild(ta);
      }
    });
  });
})();
</script>
```

---

## 5. 返回顶部

**适用场景**：长文档滚动浏览时快速回到顶部

**适用模式**：全部（mode-doc 长报告、mode-dashboard 多指标简报等）

### CSS（内联到 `<style>` 块尾部）

```css
/* ========== 交互增强：返回顶部 ========== */
.back-to-top {
  position: fixed; bottom: 32px; right: 32px;
  width: 44px; height: 44px; border-radius: 50%;
  border: none; background: {primary}; color: #fff;
  font-size: 20px; cursor: pointer; opacity: 0;
  visibility: hidden; transition: opacity 0.3s, visibility 0.3s, background 0.2s;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15); z-index: 9999;
}
.back-to-top:hover { background: {primary_dark}; }
.back-to-top.visible { opacity: 1; visibility: visible; }
```

### HTML 结构

```html
<button class="back-to-top" aria-label="返回顶部">↑</button>
```

### JS（内联到 `</body>` 前）

```html
<script>
(function(){
  var btn=document.querySelector('.back-to-top');
  if(!btn) return;
  window.addEventListener('scroll',function(){
    btn.classList.toggle('visible',window.scrollY>400);
  });
  btn.addEventListener('click',function(){
    window.scrollTo({top:0,behavior:'smooth'});
  });
})();
</script>
```

---

## 组合使用

多个交互组件可同时使用，JS 片段合并到同一个 `<script>` 标签内：

```html
<script>
(function(){
  // Tab 切换
  ...
  // 表格搜索
  ...
  // 返回顶部
  ...
})();
</script>
```

**注意**：多个 IIFE 可合并为一个，减少 `<script>` 标签数量。总 JS 量控制在 ~2KB 以内。

---

## 转换影响分析

当 HTML 中包含 `<script>` 标签时，`impact_analyzer.py` 应检测到并输出以下降级项：

| 检测特征 | 降级项描述 |
|---|---|
| `.tab-nav` + `.tab-panel` | Tab 切换交互 → Word/PDF 全部面板展开（内容不丢） |
| `.table-search-input` | 表格搜索 → Word/PDF 保留完整表格（无搜索功能） |
| `.collapse-trigger` + `.collapse-body` | 折叠展开 → Word/PDF 全部展开为段落（内容不丢） |
| `.code-copy-btn` | 代码复制按钮 → Word/PDF/Markdown 按钮丢失，代码保留 |
| `.back-to-top` | 返回顶部按钮 → Word/PDF/Markdown 按钮丢失（无影响） |

> 本文件中的 CSS 和 JS 代码片段均可直接内联到生成的 HTML 中。所有色值占位符（如 `{primary}`、`{border}` 等）需替换为 `palettes.json` 中选定调色板的真实色值，与骨架占位符替换规则一致。
