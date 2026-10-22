/* ============================================================================
 * slide-audit · engine.js
 * 页面内注入的几何审计引擎（纯浏览器 JS，无任何依赖）
 *
 * 设计目标：把「肉眼/视觉模型才能发现」的排版问题，转成可计算的数值判定。
 * 全部判定基于真实 layout 结果（getBoundingClientRect / Range / elementFromPoint），
 * 因此能覆盖字体度量、自动换行、flex/grid、绝对定位叠加等静态解析无法处理的场景。
 *
 * 对外暴露：window.__SLIDE_AUDIT__(options) -> { meta, slides, issues, stats }
 * ========================================================================== */
(function (global) {
  'use strict';

  var DEFAULTS = {
    tol: 1.0,            // 通用几何容差 px
    overflowTol: 1.5,    // 溢出判定容差 px
    minOverlapArea: 24,  // 重叠告警最小面积 px^2
    minOverlapDim: 4,    // 重叠告警最小边长 px（过滤行盒「贴边」误报）
    occludeRatio: 0.25,  // 文字被遮挡比例阈值
    minFontSize: 18,     // 最小字号告警 px（本技能要求最小18px）
    minContrast: 3.0,    // 对比度告警阈值
    sampleStep: 8,       // 遮挡命中测试采样步长 px
    maxSample: 600,      // 单个元素最大采样点数
    decorOpacity: 0.15,  // 低于此不透明度视为装饰
    canvasW: 1280,
    canvasH: 768
  };

  /* ---------------------------- 基础工具 ---------------------------- */

  function px(v) { var n = parseFloat(v); return isFinite(n) ? n : 0; }
  function r2(n) { return Math.round(n * 100) / 100; }
  function num(v, d) { return (typeof v === 'number' && isFinite(v)) ? v : d; }

  function box(r) {
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
  }
  function area(r) { return r ? Math.max(0, r.width) * Math.max(0, r.height) : 0; }
  function intersect(a, b) {
    if (!a || !b) return null;
    var x1 = Math.max(a.left, b.left), y1 = Math.max(a.top, b.top);
    var x2 = Math.min(a.right, b.right), y2 = Math.min(a.bottom, b.bottom);
    if (x2 - x1 <= 0 || y2 - y1 <= 0) return null;
    return { left: x1, top: y1, right: x2, bottom: y2, width: x2 - x1, height: y2 - y1 };
  }
  function union(a, b) {
    if (!a) return b ? box(b) : null;
    if (!b) return a;
    // 直接算出 width/height，不依赖调用方再调 norm() 修正
    // （旧实现返回 width:0/height:0，一旦有调用点忘记 norm() 就会用 0 尺寸做交集/面积判定）
    var left = Math.min(a.left, b.left), top = Math.min(a.top, b.top);
    var right = Math.max(a.right, b.right), bottom = Math.max(a.bottom, b.bottom);
    return {
      left: left, top: top, right: right, bottom: bottom,
      width: right - left, height: bottom - top
    };
  }
  function norm(u) { if (u) { u.width = u.right - u.left; u.height = u.bottom - u.top; } return u; }

  function parseColor(str) {
    if (!str) return null;
    str = String(str).trim();
    if (str === 'transparent' || str === 'none') return [0, 0, 0, 0];
    var m = str.match(/^rgba?\(([^)]+)\)$/i);
    if (m) {
      var p = m[1].split(',').map(function (s) { return parseFloat(s); });
      if (p.length < 3) return null;
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    m = str.match(/^#([0-9a-f]{3})$/i);
    if (m) return [parseInt(m[1][0] + m[1][0], 16), parseInt(m[1][1] + m[1][1], 16), parseInt(m[1][2] + m[1][2], 16), 1];
    m = str.match(/^#([0-9a-f]{6})$/i);
    if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), 1];
    return null;
  }

  function lum(c) {
    var f = [0, 1, 2].map(function (i) {
      var v = c[i] / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  }
  function contrast(a, b) {
    var l1 = lum(a), l2 = lum(b);
    var hi = Math.max(l1, l2), lo = Math.min(l1, l2);
    return (hi + 0.05) / (lo + 0.05);
  }
  function blend(fg, bg) { // fg over bg
    var a = fg[3];
    return [
      fg[0] * a + bg[0] * (1 - a),
      fg[1] * a + bg[1] * (1 - a),
      fg[2] * a + bg[2] * (1 - a),
      1
    ];
  }

  /* ------------------------- 元素画像 (Profile) ------------------------- */

  var uidSeq = 0;
  var profileMap = new WeakMap();

  function ownText(el) {
    var s = '';
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3) s += n.nodeValue;
    }
    return s;
  }

  function effectiveOpacity(el) {
    var o = 1, cur = el;
    while (cur && cur.nodeType === 1) {
      o *= px(getComputedStyle(cur).opacity);
      cur = cur.parentElement;
    }
    return o;
  }

  // 该元素所有文字行的真实外接矩形（用 Range，比元素 box 精确）
  function textRects(el) {
    var out = [];
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType !== 3 || !n.nodeValue.trim()) continue;
      var rg = document.createRange();
      try { rg.selectNodeContents(n); } catch (e) { continue; }
      var list = rg.getClientRects();
      for (var k = 0; k < list.length; k++) {
        var r = list[k];
        if (r.width > 0.5 && r.height > 0.5) out.push(box(r));
      }
    }
    return out;
  }

  function textUnion(el) {
    var rs = textRects(el);
    var u = null;
    for (var i = 0; i < rs.length; i++) u = union(u, rs[i]);
    return norm(u);
  }

  function profile(el, root) {
    if (profileMap.has(el)) return profileMap.get(el);
    var cs = getComputedStyle(el);
    var r = el.getBoundingClientRect();
    var tag = el.tagName.toLowerCase();
    var ot = ownText(el).replace(/\s+/g, ' ').trim();
    var allText = (el.textContent || '').replace(/\s+/g, ' ').trim();

    var bg = parseColor(cs.backgroundColor) || [0, 0, 0, 0];
    var bgImg = cs.backgroundImage && cs.backgroundImage !== 'none' ? cs.backgroundImage : '';
    var hasBg = bg[3] > 0.02 || !!bgImg;
    var borderW = ['borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth']
      .reduce(function (s, k) { return s + px(cs[k]); }, 0);

    var p = {
      uid: ++uidSeq,
      el: el,
      tag: tag,
      cls: (el.getAttribute('class') || '').trim(),
      id: el.id || '',
      rect: box(r),
      cssText: el.getAttribute('style') || '',
      cs: cs,
      ownText: ot,
      allText: allText,
      hasOwnText: ot.length > 0,
      textUnion: textUnion(el),
      opacity: effectiveOpacity(el),
      bg: bg,
      bgImg: bgImg,
      hasBg: hasBg,
      borderW: borderW,
      display: cs.display,
      position: cs.position,
      overflowX: cs.overflowX,
      overflowY: cs.overflowY,
      zIndex: cs.zIndex,
      fontSize: px(cs.fontSize),
      lineHeight: cs.lineHeight,
      whiteSpace: cs.whiteSpace,
      textOverflow: cs.textOverflow,
      pointerEvents: cs.pointerEvents,
      visibility: cs.visibility,
      color: parseColor(cs.color) || [0, 0, 0, 1]
    };

    p.isSvg = tag === 'svg' || !!el.closest('svg');
    p.visible = p.rect.width > 0.5 && p.rect.height > 0.5 &&
      p.display !== 'none' && p.visibility !== 'hidden' && p.opacity > 0.02;

    // 装饰元素：无文字 + (SVG / 不透明度极低 / 不参与命中)
    p.decor = p.isSvg || !p.hasOwnText && (
      p.opacity <= DEFAULTS.decorOpacity ||
      p.pointerEvents === 'none'
    );
    // 有实际视觉存在感的「实体」
    p.solid = p.visible && (p.hasOwnText || p.hasBg || p.borderW > 0 || tag === 'img' || tag === 'canvas' || tag === 'video');
    p.path = cssPath(el, root);

    profileMap.set(el, p);
    return p;
  }

  function cssPath(el, root) {
    var parts = [];
    var cur = el;
    var guard = 0;
    while (cur && cur.nodeType === 1 && guard++ < 40) {
      if (cur === root) {
        parts.unshift(root.classList && root.classList[0] ? '.' + root.classList[0] : root.tagName.toLowerCase());
        break;
      }
      var s = cur.tagName.toLowerCase();
      if (cur.id) s += '#' + cur.id;
      var cls = (cur.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
      if (cls.length) s += '.' + cls.join('.');
      var p = cur.parentElement;
      if (p) {
        var sibs = Array.prototype.filter.call(p.children, function (c) { return c.tagName === cur.tagName; });
        if (sibs.length > 1) s += ':' + (sibs.indexOf(cur) + 1);
      }
      parts.unshift(s);
      cur = cur.parentElement;
      if (!cur) break;
    }
    return parts.join(' > ');
  }

  // 内容外接框：所有后代文字行 + 无文字的实体盒（色块/图标）
  function contentBounds(el, root) {
    var u = null;
    var tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    var n;
    while ((n = tw.nextNode())) {
      if (!n.nodeValue.trim()) continue;
      // 跳过 script / style 内文本
      var pe = n.parentElement;
      if (!pe || pe.tagName === 'SCRIPT' || pe.tagName === 'STYLE') continue;
      var rg = document.createRange();
      try { rg.selectNodeContents(n); } catch (e) { continue; }
      var list = rg.getClientRects();
      for (var i = 0; i < list.length; i++) {
        var r = list[i];
        if (r.width > 0.5 && r.height > 0.5) u = union(u, box(r));
      }
    }
    var kids = el.querySelectorAll('*');
    for (var k = 0; k < kids.length; k++) {
      var c = kids[k];
      if (c.tagName === 'SCRIPT' || c.tagName === 'STYLE') continue;
      var cp = profile(c, root);
      if (!cp.visible) continue;
      if (cp.hasOwnText) continue;         // 文字已由 Range 覆盖
      if (cp.isSvg) continue;              // 装饰 SVG 不参与
      if (cp.hasBg || cp.borderW > 0 || c.tagName === 'IMG') u = union(u, c.getBoundingClientRect());
    }
    return norm(u);
  }

  /* --------------------- 祖先裁剪区 (overflow clip) --------------------- */

  function clipRect(el, root) {
    var clip = null;
    var cur = el;
    var guard = 0;
    while (cur && cur.nodeType === 1 && guard++ < 60) {
      var cs = getComputedStyle(cur);
      var hidden = cs.overflowX !== 'visible' || cs.overflowY !== 'visible';
      if (hidden) {
        var r = cur.getBoundingClientRect();
        // CSS overflow:hidden 裁剪区域是 padding box（border 内侧，含 padding），
        // 不是 content box。误用 content box 会把 padding 内可见的文字报为被裁切。
        var cr = {
          left: r.left + px(cs.borderLeftWidth),
          top: r.top + px(cs.borderTopWidth),
          right: r.right - px(cs.borderRightWidth),
          bottom: r.bottom - px(cs.borderBottomWidth)
        };
        cr.width = cr.right - cr.left; cr.height = cr.bottom - cr.top;
        clip = clip ? intersect(clip, cr) : cr;
      }
      if (cur === root) break;
      cur = cur.parentElement;
    }
    return clip;
  }

  /* --------------------------- 建议生成 --------------------------- */

  function suggestForOverflow(p, cb, cbBox, root, canvas) {
    var out = [];
    var cs = p.cs;
    var padV = px(cs.paddingTop) + px(cs.paddingBottom);
    var borderV = px(cs.borderTopWidth) + px(cs.borderBottomWidth);
    var boxSizing = cs.boxSizing || 'content-box';
    var inlineH = /height\s*:\s*([\d.]+)px/i.exec(p.cssText);
    // box-sizing 影响 height 属性的含义：
    // border-box: height 含 padding+border → needH = 内容高 + padding + border + 1
    // content-box: height 仅内容区 → needH = 内容高 + 1
    var needH = boxSizing === 'border-box'
      ? Math.ceil(cb.height + padV + borderV + 1)
      : Math.ceil(cb.height + 1);
    var haveH = p.rect.height;

    if (inlineH) {
      out.push({ type: 'style', from: 'height:' + inlineH[1] + 'px', to: 'height:' + needH + 'px', note: '容器高度不足，按内容实算' });
    } else if (haveH > 0) {
      out.push({ type: 'style', from: null, to: 'height:' + needH + 'px', note: '容器高度不足（当前 ' + r2(haveH) + 'px），按内容实算需 ' + needH + 'px' });
    }

    // border-box: needH 是 border box 高度，top + needH 即为新的底边
    // content-box: needH 是内容区高度，border box 底边 = top + needH + padding + border
    var newBottom = boxSizing === 'border-box'
      ? p.rect.top + needH
      : p.rect.top + needH + padV + borderV;
    if (canvas && newBottom > canvas.bottom - 4) {
      var newTop = Math.max(4, Math.floor(canvas.bottom - needH - 8));
      out.push({ type: 'style', from: null, to: 'top:' + newTop + 'px（配合上方高度）', note: '加高后会超出画布下边界（' + r2(canvas.bottom) + 'px），需同步上移或压缩内容' });
    }

    if (p.fontSize > 0) {
      // haveH 是 border box 高度，需减去 padding 和 border 才是可用内容区高度
      var availH = haveH - padV - borderV;
      if (cb.height > availH && cb.height > 0) {
        var scaled = Math.max(10, Math.floor(p.fontSize * (availH / cb.height)));
        if (scaled < p.fontSize) {
          out.push({ type: 'style', from: 'font-size:' + r2(p.fontSize) + 'px', to: 'font-size:' + scaled + 'px', note: '备选方案：缩小字号以适配固定高度' + (scaled < DEFAULTS.minFontSize ? '（注意：低于 ' + DEFAULTS.minFontSize + 'px 可读性差）' : '') });
        }
      }
    }
    return out;
  }

  /* --------------------------- 规则实现 --------------------------- */

  var RULES = {};

  /* R1 文字/内容溢出容器 */
  RULES.TEXT_OVERFLOW = {
    title: '文字/内容溢出容器',
    run: function (ctx) {
      var found = [];
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
        var p = ctx.prof(el);
        if (!p.visible) continue;
        if (el === ctx.root) continue;
        // 快速预判：scrollHeight > clientHeight 说明内容超出可视区
        // 覆盖 inline style 和 CSS class 两种设高方式（旧代码仅查 inline style 的 hasFixedH）
        var hasOverflow = el.scrollHeight > el.clientHeight + 2;
        var isCard = p.hasBg || p.borderW > 0;
        var hasClip = p.cs.overflowY !== 'visible' || p.cs.overflowX !== 'visible';
        if (!hasClip && !isCard && !hasOverflow) continue;

        var cb = contentBounds(el, ctx.root);
        if (!cb) continue;
        var cs = p.cs;
        var pad = { t: px(cs.paddingTop), r: px(cs.paddingRight), b: px(cs.paddingBottom), l: px(cs.paddingLeft) };
        var cbox = {
          left: p.rect.left + px(cs.borderLeftWidth) + pad.l,
          top: p.rect.top + px(cs.borderTopWidth) + pad.t,
          right: p.rect.right - px(cs.borderRightWidth) - pad.r,
          bottom: p.rect.bottom - px(cs.borderBottomWidth) - pad.b
        };
        cbox.width = cbox.right - cbox.left; cbox.height = cbox.bottom - cbox.top;

        var over = {
          bottom: cb.bottom - cbox.bottom,
          right: cb.right - cbox.right,
          top: cbox.top - cb.top,
          left: cbox.left - cb.left
        };
        var maxOver = Math.max(over.bottom, over.right, over.top, over.left);
        if (maxOver <= ctx.opt.overflowTol) continue;

        var side = 'bottom'; var mv = over.bottom;
        if (over.right > mv) { side = 'right'; mv = over.right; }
        if (over.top > mv) { side = 'top'; mv = over.top; }
        if (over.left > mv) { side = 'left'; mv = over.left; }

        var clipped = p.cs.overflowY !== 'visible' || p.cs.overflowX !== 'visible';
        // 文字溢出「有色块/描边的卡片」= 肉眼可见的破版，即使 overflow:visible 也算错误
        var spillingOutOfCard = !clipped && mv >= 6 && (p.hasBg || p.borderW > 0);
        var sev = (clipped || spillingOutOfCard) ? 'error' : (mv >= 3 ? 'warning' : 'info');
        var sides = [];
        ['top', 'right', 'bottom', 'left'].forEach(function (s) {
          if (over[s] > ctx.opt.overflowTol) sides.push(SIDE_CN[s] + '越出 ' + r2(over[s]) + 'px');
        });

        found.push({
          side: side, amount: r2(mv), over: {
            bottom: r2(over.bottom), right: r2(over.right), top: r2(over.top), left: r2(over.left)
          },
          clipped: clipped,
          contentH: r2(cb.height), boxH: r2(cbox.height),
          contentW: r2(cb.width), boxW: r2(cbox.width),
          suggestions: suggestForOverflow(p, cb, cbox, ctx.root, ctx.canvas)
        });
        ctx.issue({
          rule: 'TEXT_OVERFLOW', severity: sev, el: el, p: p,
          rect: cb,
          message: '容器内容区 ' + r2(cbox.width) + '×' + r2(cbox.height) + 'px，实际内容 ' +
            r2(cb.width) + '×' + r2(cb.height) + 'px → ' + sides.join('、') +
            (clipped ? '；overflow 非 visible，该部分会被直接裁掉'
              : '；overflow:visible，内容会溢出到背景块之外并压住相邻元素'),
          data: found[found.length - 1]
        });
      }
    }
  };

  var SIDE_CN = { bottom: '底部', top: '顶部', right: '右侧', left: '左侧' };

  /* R2 子元素越出父容器可视范围（更精确：父子关系） */
  RULES.CHILD_OUT_OF_PARENT = {
    title: '子元素越出父容器',
    run: function (ctx) {
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || p.decor) continue;
        if (!p.hasOwnText && !p.hasBg) continue;
        var par = el.parentElement;
        if (!par || par === ctx.root || !ctx.root.contains(par)) continue;
        var pp = ctx.prof(par);
        if (!pp.visible) continue;
        // 父容器必须是「有边界的实体卡」才判定
        // 检查：有背景/边框，或 overflow 非visible，或内容超出可视区（覆盖 CSS class 设高）
        var ppHasBoundary = pp.hasBg || pp.borderW > 0 ||
          pp.cs.overflowY !== 'visible' || pp.cs.overflowX !== 'visible' ||
          par.scrollHeight > par.clientHeight + 2;
        if (!ppHasBoundary) continue;
        var cs = pp.cs;
        var pb = {
          left: pp.rect.left + px(cs.borderLeftWidth) + px(cs.paddingLeft),
          top: pp.rect.top + px(cs.borderTopWidth) + px(cs.paddingTop),
          right: pp.rect.right - px(cs.borderRightWidth) - px(cs.paddingRight),
          bottom: pp.rect.bottom - px(cs.borderBottomWidth) - px(cs.paddingBottom)
        };
        pb.width = pb.right - pb.left; pb.height = pb.bottom - pb.top;
        var cb = p.hasOwnText && p.textUnion ? p.textUnion : p.rect;
        var over = {
          bottom: cb.bottom - pb.bottom, right: cb.right - pb.right,
          top: pb.top - cb.top, left: pb.left - cb.left
        };
        var maxOver = Math.max(over.bottom, over.right, over.top, over.left);
        if (maxOver <= ctx.opt.overflowTol) continue;
        var side = 'bottom', mv = over.bottom;
        if (over.right > mv) { side = 'right'; mv = over.right; }
        if (over.top > mv) { side = 'top'; mv = over.top; }
        if (over.left > mv) { side = 'left'; mv = over.left; }

        // 若父级已在同一轴向报 TEXT_OVERFLOW，跳过（去噪）
        if (ctx.parentOverflowSides(par, side, maxOver)) continue;

        ctx.issue({
          rule: 'CHILD_OUT_OF_PARENT',
          severity: pp.cs.overflowY !== 'visible' ? 'error' : 'warning',
          el: el, p: p, rect: cb,
          message: '子元素' + SIDE_CN[side] + '超出父容器 ' + r2(mv) + 'px（父：' + pp.path + '）',
          data: { side: side, amount: r2(mv), parentPath: pp.path, parentRect: pp.rect }
        });
      }
    }
  };

  /* R3 内容被祖先 overflow 裁切 */
  RULES.TEXT_CLIPPED = {
    title: '文字被容器裁切',
    run: function (ctx) {
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || p.decor || !p.hasOwnText) continue;
        var cr = clipRect(el, ctx.root);
        if (!cr) continue;
        var tr = p.textUnion || p.rect;
        var cut = {
          bottom: tr.bottom - cr.bottom, right: tr.right - cr.right,
          top: cr.top - tr.top, left: cr.left - tr.left
        };
        var mx = Math.max(cut.bottom, cut.right, cut.top, cut.left);
        if (mx <= ctx.opt.overflowTol) continue;
        var side = 'bottom', mv = cut.bottom;
        if (cut.right > mv) { side = 'right'; mv = cut.right; }
        if (cut.top > mv) { side = 'top'; mv = cut.top; }
        if (cut.left > mv) { side = 'left'; mv = cut.left; }
        ctx.issue({
          rule: 'TEXT_CLIPPED', severity: 'error', el: el, p: p, rect: tr,
          message: '文字' + SIDE_CN[side] + '被上级容器裁掉 ' + r2(mv) + 'px（不可见）',
          data: { side: side, amount: r2(mv), clipRect: cr }
        });
      }
    }
  };

  /* R4 超出画布边界 */
  RULES.OUT_OF_CANVAS = {
    title: '内容超出画布',
    run: function (ctx) {
      if (!ctx.canvas) return;
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || p.decor) continue;
        if (!p.hasOwnText && !p.hasBg) continue;
        var r = p.hasOwnText && p.textUnion ? p.textUnion : p.rect;
        var c = ctx.canvas;
        var out = {
          bottom: r.bottom - c.bottom, right: r.right - c.right,
          top: c.top - r.top, left: c.left - r.left
        };
        var mx = Math.max(out.bottom, out.right, out.top, out.left);
        if (mx <= ctx.opt.overflowTol) continue;
        var inside = intersect(r, c);
        var side = 'bottom', mv = out.bottom;
        if (out.right > mv) { side = 'right'; mv = out.right; }
        if (out.top > mv) { side = 'top'; mv = out.top; }
        if (out.left > mv) { side = 'left'; mv = out.left; }
        ctx.issue({
          rule: 'OUT_OF_CANVAS',
          severity: !inside ? 'error' : (mv >= 2 ? 'error' : 'warning'),
          el: el, p: p, rect: r,
          message: (!inside ? '元素完全在画布之外' : '元素' + SIDE_CN[side] + '越出画布 ' + r2(mv) + 'px，该部分不会出现在 PPT 里'),
          data: { side: side, amount: r2(mv), fully: !inside }
        });
      }
    }
  };

  /* R5 兄弟元素相互重叠 */
  RULES.OVERLAP = {
    title: '元素相互重叠',
    run: function (ctx) {
      var seen = {};
      var all = [ctx.root].concat(Array.prototype.slice.call(ctx.root.querySelectorAll('*')));
      for (var i = 0; i < all.length; i++) {
        var par = all[i];
        if (par.tagName === 'SCRIPT' || par.tagName === 'STYLE') continue;
        var kids = Array.prototype.slice.call(par.children).filter(function (c) {
          if (c.tagName === 'SCRIPT' || c.tagName === 'STYLE') return false;
          var cp = ctx.prof(c);
          return cp.visible && cp.solid && !cp.decor;
        });
        if (kids.length < 2) continue;
        for (var a = 0; a < kids.length; a++) {
          for (var b = a + 1; b < kids.length; b++) {
            var A = ctx.prof(kids[a]), B = ctx.prof(kids[b]);
            // 使用元素矩形（border box）做重叠检测，而非文字矩形（textUnion）。
            // 旧代码用 textUnion 会导致两个有大面积背景重叠但文字在不同位置的色块被漏检。
            // textHit 过滤仍保证只报告有实际视觉干扰的重叠。
            var ra = A.rect;
            var rb = B.rect;
            var x = intersect(ra, rb);
            if (!x || area(x) < ctx.opt.minOverlapArea) continue;
            if (Math.min(x.width, x.height) < ctx.opt.minOverlapDim) continue;
            var key = A.uid + '-' + B.uid;
            if (seen[key]) continue;
            seen[key] = 1;
            var ratio = area(x) / Math.max(1, Math.min(area(ra), area(rb)));
            // textHit 判定：两个元素中至少一方有文字，另一方有文字或有明显视觉背景。
            // hasBg 已包含纯色背景（bg[3]>0.02）和渐变/图片背景（bgImg 非空），
            // 但旧代码只检查 bg[3]>0.35，漏掉了渐变背景（backgroundColor=transparent）的容器。
            // 此外容器元素自身 may not have hasOwnText（文字在子元素里），
            // 所以对无文字容器，只要 hasBg 即视为有视觉存在感。
            function hasVisualPresence(p) { return p.hasOwnText || p.bg[3] > 0.35 || !!p.bgImg; }
            var textHit = hasVisualPresence(A) && hasVisualPresence(B);
            if (!textHit) continue;
            var sev = ratio >= 0.3 ? 'error' : (ratio >= 0.08 ? 'warning' : 'info');
            ctx.issue({
              rule: 'OVERLAP', severity: sev, el: kids[a], p: A, rect: x,
              message: '与兄弟元素重叠 ' + r2(x.width) + '×' + r2(x.height) + 'px（占较小者 ' +
                Math.round(ratio * 100) + '%）→ ' + B.path,
              data: {
                overlapRect: x, area: r2(area(x)), ratio: r2(ratio),
                otherPath: B.path, otherText: B.ownText.slice(0, 40)
              }
            });
          }
        }
      }
    }
  };

  /* R6 文字被其它元素遮挡（命中测试 + 绘制顺序双重判定） */
  RULES.OCCLUDED = {
    title: '文字被上层元素遮挡',
    run: function (ctx) {
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || p.decor || !p.hasOwnText) continue;
        var rects = textRects(el);
        if (!rects.length) continue;
        var cr = clipRect(el, ctx.root);
        var total = 0, occluded = 0;
        var occluders = {};
        for (var ri = 0; ri < rects.length; ri++) {
          var r = cr ? intersect(rects[ri], cr) : rects[ri];
          if (!r || r.width < 1 || r.height < 1) continue;
          var stepX = Math.max(2, ctx.opt.sampleStep);
          var cols = Math.min(40, Math.max(2, Math.ceil(r.width / stepX)));
          var rows = Math.min(40, Math.max(2, Math.ceil(r.height / stepX)));
          for (var cx = 0; cx < cols; cx++) {
            for (var cy = 0; cy < rows; cy++) {
              if (total >= ctx.opt.maxSample) break;
              var x = r.left + (cx + 0.5) * (r.width / cols);
              var y = r.top + (cy + 0.5) * (r.height / rows);
              var hit = document.elementFromPoint(x, y);
              total++;
              if (!hit) { occluded++; continue; }
              if (hit === el || el.contains(hit)) continue;
              if (hit.contains(el)) continue;   // 祖先命中 => 裁切场景，交由 TEXT_CLIPPED
              occluded++;
              var hp = ctx.prof(hit);
              var k = hp.path + ' | ' + (hp.ownText || hp.tag).slice(0, 24);
              occluders[k] = (occluders[k] || 0) + 1;
            }
          }
        }
        if (total < 4) continue;
        var ratio = occluded / total;
        if (ratio < ctx.opt.occludeRatio) continue;
        var top = Object.keys(occluders).sort(function (a, b) { return occluders[b] - occluders[a]; }).slice(0, 3);
        ctx.issue({
          rule: 'OCCLUDED',
          severity: ratio >= 0.6 ? 'error' : 'warning',
          el: el, p: p, rect: p.textUnion || p.rect,
          message: '文字约 ' + Math.round(ratio * 100) + '% 的面积被其它元素盖住（遮挡者：' + top.join('；') + '）',
          data: { ratio: r2(ratio), occluders: top, samples: total }
        });
      }
    }
  };

  /* R7 单行文本被截断（nowrap / ellipsis） */
  RULES.TEXT_TRUNCATED = {
    title: '单行文本被截断',
    run: function (ctx) {
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || !p.hasOwnText) continue;
        if (p.whiteSpace !== 'nowrap' && p.textOverflow !== 'ellipsis') continue;
        var overW = el.scrollWidth - el.clientWidth;
        if (overW <= 1) continue;
        ctx.issue({
          rule: 'TEXT_TRUNCATED', severity: 'warning', el: el, p: p, rect: p.rect,
          message: '单行文本超宽 ' + r2(overW) + 'px，' +
            (p.textOverflow === 'ellipsis' ? '将以省略号截断' : '会被裁掉且无省略号'),
          data: { overWidth: r2(overW), text: p.ownText.slice(0, 60) }
        });
      }
    }
  };

  /* R8 字号过小 */
  RULES.FONT_TOO_SMALL = {
    title: '字号过小',
    run: function (ctx) {
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || p.decor || !p.hasOwnText) continue;
        if (p.fontSize <= 0 || p.fontSize >= ctx.opt.minFontSize) continue;
        ctx.issue({
          rule: 'FONT_TOO_SMALL', severity: 'info', el: el, p: p, rect: p.textUnion || p.rect,
          message: '字号 ' + r2(p.fontSize) + 'px 小于 ' + ctx.opt.minFontSize + 'px，投影/转 PPT 后难以辨认',
          data: { fontSize: r2(p.fontSize), text: p.ownText.slice(0, 40) }
        });
      }
    }
  };

  /* R9 文字与背景对比度过低 */
  RULES.LOW_CONTRAST = {
    title: '文字对比度过低',
    run: function (ctx) {
      var all = ctx.root.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var p = ctx.prof(el);
        if (!p.visible || p.decor || !p.hasOwnText) continue;
        var bg = effectiveBg(el, ctx.root);
        if (!bg) continue;
        var fg = p.color[3] < 1 ? blend(p.color, bg) : p.color;
        var ratio = contrast(fg, bg);
        var large = p.fontSize >= 24 || px(p.cs.fontWeight) >= 700 && p.fontSize >= 18;
        var th = large ? Math.max(2.2, ctx.opt.minContrast - 0.8) : ctx.opt.minContrast;
        if (ratio >= th) continue;
        ctx.issue({
          rule: 'LOW_CONTRAST', severity: ratio < 2 ? 'error' : 'warning', el: el, p: p, rect: p.textUnion || p.rect,
          message: '文字与背景对比度 ' + r2(ratio) + ':1，低于建议值 ' + r2(th) + ':1（大字/粗体门槛更低）',
          data: {
            ratio: r2(ratio), threshold: r2(th),
            fg: 'rgb(' + fg.slice(0, 3).map(Math.round).join(',') + ')',
            bg: 'rgb(' + bg.slice(0, 3).map(Math.round).join(',') + ')',
            approx: !!(bgImgOf(el))
          }
        });
      }
    }
  };

  function bgImgOf(el) {
    var cur = el;
    while (cur && cur.nodeType === 1) {
      var cs = getComputedStyle(cur);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return cs.backgroundImage;
      cur = cur.parentElement;
    }
    return '';
  }

  function effectiveBg(el, root) {
    var cur = el;
    var guard = 0;
    while (cur && cur.nodeType === 1 && guard++ < 40) {
      var cs = getComputedStyle(cur);
      var c = parseColor(cs.backgroundColor);
      if (c && c[3] > 0.85) return c;
      if (c && c[3] > 0.02) {
        var under = effectiveBgFrom(cur.parentElement, root);
        return under ? blend(c, under) : c;
      }
      if (cs.backgroundImage && cs.backgroundImage !== 'none') {
        // 渐变：提取第一个出现的颜色做近似
        var m = cs.backgroundImage.match(/rgba?\([^)]+\)|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}/);
        if (m) { var g = parseColor(m[0]); if (g) return g[3] > 0.5 ? g : [g[0], g[1], g[2], 1]; }
      }
      if (cur === root) break;
      cur = cur.parentElement;
    }
    return [255, 255, 255, 1];
  }
  function effectiveBgFrom(el, root) {
    if (!el || el.nodeType !== 1) return [255, 255, 255, 1];
    return effectiveBg(el, root);
  }

  /* ----------------------------- 主流程 ----------------------------- */

  function auditSlide(root, opt) {
    var issues = [];
    var canvas = null;
    var r = root.getBoundingClientRect();
    canvas = { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };

    var overflowRegistry = {}; // parentUid -> {side: amount}

    var ctx = {
      root: root, opt: opt, canvas: canvas,
      prof: function (el) { return profile(el, root); },
      issue: function (o) {
        if (o.rule === 'TEXT_OVERFLOW') {
          var uid = profile(o.el, root).uid;
          overflowRegistry[uid] = o.data;
        }
        var p = o.p;
        issues.push({
          rule: o.rule,
          ruleTitle: (RULES[o.rule] || {}).title || o.rule,
          severity: o.severity,
          path: p.path,
          tag: p.tag,
          text: (p.ownText || p.allText || '').slice(0, 80),
          style: p.cssText.slice(0, 220),
          rect: o.rect ? { x: r2(o.rect.left), y: r2(o.rect.top), w: r2(o.rect.width), h: r2(o.rect.height) } : null,
          message: o.message,
          data: o.data || {}
        });
      },
      // 父级已在同一轴向上报过 TEXT_OVERFLOW 时，子元素的越界是同一根因的连带表现，跳过以免刷屏
      parentOverflowSides: function (par, side, maxOver) {
        var rec = overflowRegistry[profile(par, root).uid];
        if (!rec) return false;
        var axisOf = function (s) { return (s === 'top' || s === 'bottom') ? 'v' : 'h'; };
        return axisOf(rec.side) === axisOf(side) && rec.amount >= maxOver * 0.5;
      }
    };

    var order = ['TEXT_OVERFLOW', 'CHILD_OUT_OF_PARENT', 'TEXT_CLIPPED', 'OUT_OF_CANVAS',
      'OVERLAP', 'OCCLUDED', 'TEXT_TRUNCATED', 'LOW_CONTRAST', 'FONT_TOO_SMALL'];
    order.forEach(function (name) {
      if (!RULES[name]) return;
      if (opt.rules && opt.rules[name] === false) return;
      try { RULES[name].run(ctx); } catch (e) {
        issues.push({
          rule: 'ENGINE_ERROR', ruleTitle: '引擎异常', severity: 'error', path: name,
          tag: '', text: '', style: '', rect: null,
          message: '规则 ' + name + ' 执行失败：' + (e && e.message ? e.message : e), data: {}
        });
      }
    });

    // 去重：同一 rule + 相近矩形 只保留最严重的一条
    return dedupe(issues);
  }

  function dedupe(list) {
    var rank = { error: 3, warning: 2, info: 1 };
    var map = {};
    var out = [];
    list.forEach(function (it) {
      var key = it.rule + '|' + it.path + '|' +
        (it.rect ? [Math.round(it.rect.x / 4), Math.round(it.rect.y / 4), Math.round(it.rect.w / 4), Math.round(it.rect.h / 4)].join(',') : '');
      var prev = map[key];
      if (!prev) { map[key] = it; out.push(it); return; }
      if ((rank[it.severity] || 0) > (rank[prev.severity] || 0)) {
        out[out.indexOf(prev)] = it; map[key] = it;
      }
    });
    return out;
  }

  /* --------------------------- 幻灯片根节点发现 --------------------------- */

  function findSlideRoots(opt) {
    var cands = Array.prototype.slice.call(document.querySelectorAll('.slide, [class*="slide"], [class*="Slide"], [id^="slide-"], [id^="slide_"]'));
    var roots = cands.filter(function (el) {
      var r = el.getBoundingClientRect();
      return r.width >= 400 && r.height >= 200;
    });
    if (roots.length === 0) {
      // 没找到幻灯片容器：若页面靠 iframe 播放幻灯片，则这是「播放器外壳页」，不应体检
      var frames = document.querySelectorAll('iframe, frame').length;
      return { roots: [document.body], shell: frames > 0 };
    }
    // 去掉互为祖先的（只保留最外层）
    return {
      roots: roots.filter(function (a) {
        return !roots.some(function (b) { return b !== a && b.contains(a); });
      }),
      shell: false
    };
  }

  /* ------------------------------ 入口 ------------------------------ */

  global.__SLIDE_AUDIT__ = function (options) {
    var opt = {};
    for (var k in DEFAULTS) opt[k] = DEFAULTS[k];
    if (options) for (var k2 in options) opt[k2] = options[k2];

    var found = findSlideRoots(opt);
    if (found.shell && !(opt.includeShell)) {
      return {
        skipped: true,
        meta: {
          url: location.href, title: document.title,
          reason: '未找到 .slide 容器且页面含 iframe —— 判定为播放器外壳页，已跳过（用 --include-shell 强制检查）'
        },
        slides: [], issues: [], stats: { error: 0, warning: 0, info: 0 }
      };
    }
    var roots = found.roots;
    var slides = [];
    var allIssues = [];
    var stats = { error: 0, warning: 0, info: 0 };

    roots.forEach(function (root, idx) {
      var r = root.getBoundingClientRect();
      var issues = auditSlide(root, opt);
      issues.forEach(function (it) {
        it.slide = idx + 1;
        // 转成相对幻灯片的坐标，便于画标注
        if (it.rect) {
          it.rect.rx = r2(it.rect.x - r.left);
          it.rect.ry = r2(it.rect.y - r.top);
        }
        stats[it.severity] = (stats[it.severity] || 0) + 1;
      });
      allIssues = allIssues.concat(issues);
      slides.push({
        index: idx + 1,
        path: cssPath(root, root),
        width: r2(r.width), height: r2(r.height),
        rect: { x: r2(r.left + window.scrollX), y: r2(r.top + window.scrollY), w: r2(r.width), h: r2(r.height) },
        counts: {
          error: issues.filter(function (i) { return i.severity === 'error'; }).length,
          warning: issues.filter(function (i) { return i.severity === 'warning'; }).length,
          info: issues.filter(function (i) { return i.severity === 'info'; }).length
        }
      });
    });

    return {
      meta: {
        url: location.href,
        title: document.title,
        viewport: { w: window.innerWidth, h: window.innerHeight },
        options: opt,
        slideCount: slides.length,
        engineVersion: '1.0.0'
      },
      slides: slides,
      issues: allIssues,
      stats: stats
    };
  };

  /* 标注注入：把问题框画到页面上（可选，用于截图复核）
     issue.rect 是 viewport 坐标（getBoundingClientRect 直接返回），
     而 host 是 absolute 定位到文档坐标系，页面有滚动时必须加上 scrollX/scrollY，
     否则标注框会与截图 clip（文档坐标）错位。 */
  global.__SLIDE_AUDIT_ANNOTATE__ = function (result, rootIndex) {
    var COLOR = { error: '#e5342c', warning: '#f5a623', info: '#2b7de9' };
    var host = document.createElement('div');
    host.id = '__slide_audit_overlay__';
    host.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;';
    document.body.appendChild(host);
    var sx = window.scrollX || 0, sy = window.scrollY || 0;
    var roots = findSlideRoots({}).roots || [];
    result.issues.forEach(function (it, i) {
      if (!it.rect) return;
      var root = roots[(it.slide || 1) - 1] || roots[0];
      if (!root) return;
      var c = COLOR[it.severity] || '#888';
      var d = document.createElement('div');
      d.style.cssText = 'position:absolute;border:2px dashed ' + c + ';background:' + c + '22;' +
        'left:' + (it.rect.x + sx) + 'px;top:' + (it.rect.y + sy) + 'px;width:' + it.rect.w + 'px;height:' + it.rect.h + 'px;' +
        'box-sizing:border-box;pointer-events:none;z-index:2147483647;';
      var lb = document.createElement('div');
      lb.textContent = String(i + 1) + '·' + it.rule;
      lb.style.cssText = 'position:absolute;left:0;top:-16px;background:' + c + ';color:#fff;font:11px/14px monospace;' +
        'padding:0 4px;white-space:nowrap;border-radius:2px;';
      d.appendChild(lb);
      host.appendChild(d);
    });
    return host.childNodes.length;
  };

})(typeof window !== 'undefined' ? window : this);
