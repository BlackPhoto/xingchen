/* Browser-side collector: returns JSON-able flat element list.
   Real browser layout -> exact rects; computed styles -> visuals;
   DOM order + z-index -> paint order. Engine (html2pptx.py) maps to PPTX. */
(() => {
  const BLOCK = new Set(['DIV','P','H1','H2','H3','H4','H5','H6','LI','UL','OL','SECTION','ARTICLE',
    'HEADER','FOOTER','MAIN','NAV','ASIDE','TABLE','THEAD','TBODY','TFOOTER','TR','TD','TH',
    'FIGURE','FIGCAPTION','BLOCKQUOTE','PRE','FORM','FIELDSET','DL','DT','DD']);
  const INLINE_FMT = new Set(['SPAN','B','STRONG','EM','I','U','SMALL','MARK','CODE','A','LABEL',
    'SUP','SUB','ABBR','TIME','Q','CITE','S','DEL','INS','KBD','BIG','FONT','NOBR','BUTTON']);

  function px(v){ const n = parseFloat(v); return isFinite(n) ? n : 0; }
  function rectOf(el){ const r = el.getBoundingClientRect();
    return {x:+r.x.toFixed(2), y:+r.y.toFixed(2), w:+r.width.toFixed(2), h:+r.height.toFixed(2)}; }
  function selfStyled(el){
    const c = getComputedStyle(el);
    return c.backgroundColor !== 'rgba(0, 0, 0, 0)' || c.backgroundImage !== 'none' ||
      [c.borderTopWidth, c.borderRightWidth, c.borderBottomWidth, c.borderLeftWidth]
        .some((w, i) => px(w) > 0.3 && [c.borderTopStyle, c.borderRightStyle, c.borderBottomStyle, c.borderLeftStyle][i] !== 'none') ||
      c.boxShadow !== 'none';
  }

  function hasStyledDesc(el){
    const descs = el.querySelectorAll('*');
    for (const d of descs) if (selfStyled(d)) return true;
    return false;
  }

  function isInlineEl(el){
    if (el.tagName === 'IMG') return false;
    const d = getComputedStyle(el).display;
    return d === 'inline' || (INLINE_FMT.has(el.tagName) && !d.startsWith('block') && !d.startsWith('flex'));
  }

  function boxStyle(c){
    return {
      display: c.display, ai: c.alignItems, jc: c.justifyContent, position: c.position, zIndex: c.zIndex, opacity: +c.opacity,
      bg: c.backgroundColor, bgImg: c.backgroundImage, bgClip: c.backgroundClip, bs: c.backgroundSize,
      pt: px(c.paddingTop), pr: px(c.paddingRight), pb: px(c.paddingBottom), pl: px(c.paddingLeft),
      bt: [px(c.borderTopWidth), c.borderTopStyle, c.borderTopColor],
      br_: [px(c.borderRightWidth), c.borderRightStyle, c.borderRightColor],
      bb: [px(c.borderBottomWidth), c.borderBottomStyle, c.borderBottomColor],
      bl: [px(c.borderLeftWidth), c.borderLeftStyle, c.borderLeftColor],
      radius: [c.borderTopLeftRadius, c.borderTopRightRadius, c.borderBottomRightRadius, c.borderBottomLeftRadius],
      shadow: c.boxShadow === 'none' ? null : c.boxShadow,
      fw: c.fontWeight, fs: px(c.fontSize),
      lh: c.lineHeight, ls: c.letterSpacing, ta: c.textAlign, ff: c.fontFamily,
      fst: c.fontStyle, col: c.color
    };
  }

  function runStyle(n){
    const c = getComputedStyle(n.parentElement || n);
    // text-decoration PROPAGATES by rendering (not inheritance): <u><span>x</span></u>
    // reports 'none' on the span — walk ancestors for the first real decoration
    let td = c.textDecorationLine;
    if (!td || td === 'none'){
      let a = n.parentElement && n.parentElement.parentElement;
      while (a && a.nodeType === 1){
        try {
          const adc = getComputedStyle(a).textDecorationLine;
          if (adc && adc !== 'none'){ td = adc; break; }
        } catch (e) {}
        a = a.parentElement;
      }
    }
    return { color: c.color, fw: c.fontWeight, fs: px(c.fontSize),
             ls: c.letterSpacing === 'normal' ? 0 : px(c.letterSpacing), fst: c.fontStyle,
             bgImg: c.backgroundImage, bgClip: c.backgroundClip,
             tt: c.textTransform,
             td: td,
             pre: /^pre/.test(c.whiteSpace) || c.whiteSpace === 'break-spaces' };
  }

  /* collect inline runs as (node, start, end, style) segments; do NOT descend
     into block-level children. Segments keep the DOM anchor so visual lines can
     be measured afterwards with per-character Ranges. */
  function inlineSegs(el, flexRoot){
    const paras = []; let segs = [];
    function walk(n){
      let prevWasElement = false;   // text right after an atomic inline (chip) keeps its gap space
      for (const ch of n.childNodes){
        if (ch.nodeType === 3){
          const st = runStyle(ch);
          if (st.pre){
            const lines = ch.textContent.split('\n');
            let off = 0;
            lines.forEach((seg, k) => {
              if (k > 0){ paras.push(segs); segs = []; }
              if (seg !== '') segs.push({ node: ch, start: off, end: off + seg.length, st });
              off += seg.length + 1;
            });
          } else {
            const t = ch.textContent.replace(/\s+/g, ' ');
            if (t.trim() !== '') segs.push({ node: ch, start: 0, end: ch.textContent.length, st, afterElement: prevWasElement });
            else if (t === ' ' && segs.length) segs.push({ node: ch, start: 0, end: ch.textContent.length, st, afterElement: prevWasElement });
          }
        } else if (ch.nodeType === 1){
          if (ch.tagName === 'BR'){ paras.push(segs); segs = []; }
          else if (ch.tagName === 'SVG'){ continue; }
          else if ((isInlineEl(ch) || (flexRoot && INLINE_FMT.has(ch.tagName))) && !selfStyled(ch) && !hasStyledDesc(ch)) walk(ch);
        }
        prevWasElement = ch.nodeType === 1;
      }
    }
    walk(el);
    if (segs.length) paras.push(segs);
    return paras.filter(p => p.length);
  }

  function transformText(t, st){
    if (st.tt === 'uppercase') return t.toUpperCase();
    if (st.tt === 'lowercase') return t.toLowerCase();
    return t;
  }

  function segText(sg){
    const raw = sg.node.textContent.slice(sg.start, sg.end);
    return sg.st.pre ? raw.replace(/\s+$/, ' ') : raw.replace(/\s+/g, ' ');
  }

  /* segments -> legacy paras format (flow mode / tables / markers) */
  function segsToParas(paras){
    return paras.map(p => p.map(sg => ({ t: transformText(segText(sg), sg.st), st: sg.st })));
  }

  /* segments -> visual lines. Two-phase: phase 1 measures every char rect
     (Range per char, zero-size chars dropped); phase 2 groups the measured
     boxes into rows by vertical overlap (>30% of the smaller box) — no DOM
     calls interleaved with row state, so clustering is pure array logic.
     A pre-newline (null marker) forces a row break. Returns null on failure
     (caller falls back to flow mode). */
  function segsToLines(paras){
    const out = [];
    try {
      const rng = document.createRange();
      for (const segs of paras){
        const boxes = [];
        for (const sg of segs){
          const text = sg.node.textContent;
          if (sg.st.pre){
            let off = sg.start;
            for (const part of text.slice(sg.start, sg.end).split('\n')){
              for (let i = off; i < off + part.length; i++){
                rng.setStart(sg.node, i); rng.setEnd(sg.node, i + 1);
                const r = rng.getBoundingClientRect();
                if (r && (r.width || r.height))
                  boxes.push({ top: r.top, bot: r.bottom, left: r.left, right: r.right, ch: text[i], sg });
              }
              boxes.push(null);   // hard row break at the newline
              off += part.length + 1;
            }
            if (boxes[boxes.length - 1] === null && boxes.length) boxes.pop();  // trailing marker
          } else {
            for (let i = sg.start; i < sg.end; i++){
              rng.setStart(sg.node, i); rng.setEnd(sg.node, i + 1);
              const r = rng.getBoundingClientRect();
              if (r && (r.width || r.height))
                boxes.push({ top: r.top, bot: r.bottom, left: r.left, right: r.right, ch: text[i], sg });
            }
          }
        }
        // group into rows
        let row = null; let rowKeepLead = false;   // row starts with a space after an atomic inline: keep it
        const flushRow = () => {
          if (row && row.runs.length){
            if (!rowKeepLead && !row.runs[0].pre) row.runs[0].t = row.runs[0].t.replace(/^\s+/, '');
            const last = row.runs[row.runs.length - 1];
            if (!last.pre) last.t = last.t.replace(/\s+$/, '');
            const rr = row.runs.filter(r_ => r_.t !== '');
            if (rr.length) out.push({
              rect: { x:+row.left.toFixed(2), y:+row.top.toFixed(2),
                      w:+(row.right - row.left).toFixed(2), h:+(row.bot - row.top).toFixed(2) },
              runs: rr });
          }
          row = null;
        };
        for (const b of boxes){
          if (b === null){ flushRow(); continue; }
          const vSame = row && (Math.min(row.bot, b.bot) - Math.max(row.top, b.top)) >
              0.3 * Math.min(row.bot - row.top, b.bot - b.top);
          // an inline styled element (chip/tag) between chars leaves a horizontal
          // gap — split the row there so each side lands in its own textbox at
          // its own x instead of overdrawn contiguous text
          const hGap = row && (b.left - row.right) > 2.5;
          if (row && vSame && !hGap){
            row.top = Math.min(row.top, b.top); row.bot = Math.max(row.bot, b.bot);
            row.left = Math.min(row.left, b.left); row.right = Math.max(row.right, b.right);
          } else {
            flushRow();
            row = { top: b.top, bot: b.bot, left: b.left, right: b.right, runs: [], lastSg: null };
            if (!rowKeepLead && b.sg.afterElement && /\s/.test(b.ch)) rowKeepLead = true;
          }
          if (row.lastSg !== b.sg){
            row.runs.push({ t: '', st: b.sg.st, pre: !!b.sg.st.pre });
            row.lastSg = b.sg;
          }
          // raw newline/tab in source collapses to one visible space in HTML;
          // python-pptx would turn a literal '\n' into a hard break — emit ' '
          let ch = b.ch;
          if (!b.sg.st.pre){
            if (ch === String.fromCharCode(10) || ch === String.fromCharCode(13) || ch === String.fromCharCode(9)) ch = ' ';
            else if (b.sg.st.tt === 'uppercase') ch = ch.toUpperCase();
            else if (b.sg.st.tt === 'lowercase') ch = ch.toLowerCase();
          }
          row.runs[row.runs.length - 1].t += ch;
        }
        flushRow(); rowKeepLead = false;
      }
    } catch (e) { return null; }
    return out.length ? out : null;
  }

  function inlineFrom(el, flexRoot){
    return segsToParas(inlineSegs(el, flexRoot));
  }

  /* table cells: descend into EVERY element child (styled chips, nested divs,
     <b> wrappers...) — the default inlineSegs skips styled spans, which used to
     blank out whole columns of cell content */
  function cellSegs(el){
    const paras = []; let segs = [];
    function walk(n){
      for (const ch of n.childNodes){
        if (ch.nodeType === 3){
          const t = ch.textContent.replace(/\s+/g, ' ');
          if (t.trim() !== '') segs.push({ node: ch, start: 0, end: ch.textContent.length, st: runStyle(ch) });
        } else if (ch.nodeType === 1){
          if (ch.tagName === 'BR'){ paras.push(segs); segs = []; }
          else if (ch.tagName === 'SVG') continue;
          else walk(ch);
        }
      }
    }
    walk(el);
    if (segs.length) paras.push(segs);
    return paras.filter(p => p.length);
  }

  /* table cells: pure-graphic descendants (rating dots, progress bars...).
     The TABLE branch never recurses into styled children, and an element with
     NO text anywhere in its subtree contributes nothing via cellSegs — such
     dots used to vanish silently (conversion report showed nothing missing).
     Collect them as independent boxes (exact rect + computed style); the
     engine paints them as native shapes on top of the emitted table.
     Structural test (empty text + own visible styling), not tag-name matching.
     Note: dots drawn purely by ::before/::after pseudo elements are still not
     covered — pseudo elements have no DOM box to measure here. */
  function cellShapes(cell){
    const out = [];
    for (const d of cell.querySelectorAll('*')){
      if (d instanceof SVGElement) continue;
      if (d.textContent.trim() !== '') continue;   // carries text -> cellSegs handles it
      const dc = getComputedStyle(d);
      if (dc.display === 'none' || dc.visibility === 'hidden') continue;
      if (!selfStyled(d)) continue;
      const dr = rectOf(d);
      if (dr.w < 1 || dr.h < 1) continue;
      out.push({ rect: dr, box: boxStyle(dc) });
    }
    return out;
  }

  function pseudoStyle(el, which){
    const c = getComputedStyle(el, which);
    if (!c.content || c.content === 'none' || c.content === 'normal') return null;
    let text = c.content.replace(/^["']|["']$/g, '');
    if (/^url\(/i.test(text)) text = '';   // image content not renderable as text
    // the probe must measure with the pseudo's own font/wrapping/padding, or w/h
    // disagrees with the runs emitted below; text-transform applies to the
    // rendered content, so apply it to the emitted text as well
    if (c.textTransform === 'uppercase') text = text.toUpperCase();
    else if (c.textTransform === 'lowercase') text = text.toLowerCase();
    const probe = document.createElement('span');
    probe.style.cssText = 'all:initial;display:' + (c.display === 'inline' ? 'inline-block' : c.display) + ';box-sizing:border-box;';
    for (const k of ['position','left','right','top','bottom','width','height',
                     'marginTop','marginRight','marginBottom','marginLeft','transform',
                     'flexShrink','alignSelf','order','zIndex',
                     'fontFamily','fontSize','fontWeight','fontStyle','letterSpacing',
                     'lineHeight','whiteSpace','textTransform',
                     'paddingTop','paddingRight','paddingBottom','paddingLeft'])
      probe.style[k] = c[k];
    if (text) probe.textContent = text;
    el.appendChild(probe);
    const pr = probe.getBoundingClientRect();
    const w = pr.width, h = pr.height;
    probe.remove();
    if (w === 0 && h === 0 && !text.trim()) return null;
    return { text, w, h, position: c.position, rect: {x:pr.x, y:pr.y},
      paras: text.trim() ? [[{ t: text, st: { color: c.color, fw: c.fontWeight, fs: px(c.fontSize),
        ls: c.letterSpacing === 'normal' ? 0 : px(c.letterSpacing), fst: c.fontStyle } }]] : [],
      box: { display: c.display, ai: c.alignItems, opacity: 1,
        bg: c.backgroundColor, bgImg: c.backgroundImage, bgClip: c.backgroundClip,
        pt: px(c.paddingTop), pr: px(c.paddingRight), pb: px(c.paddingBottom), pl: px(c.paddingLeft),
        bt: [px(c.borderTopWidth), c.borderTopStyle, c.borderTopColor],
        br_: [px(c.borderRightWidth), c.borderRightStyle, c.borderRightColor],
        bb: [px(c.borderBottomWidth), c.borderBottomStyle, c.borderBottomColor],
        bl: [px(c.borderLeftWidth), c.borderLeftStyle, c.borderLeftColor],
        radius: [c.borderTopLeftRadius, c.borderTopRightRadius, c.borderBottomRightRadius, c.borderBottomLeftRadius],
        shadow: c.boxShadow === 'none' ? null : c.boxShadow,
        ta: c.textAlign, lh: c.lineHeight, col: c.color, ff: c.fontFamily,
        fs: px(c.fontSize), fw: c.fontWeight } };
  }

  function emitPseudo(el, info, which, order, anchorRect, itemZ, op){
    let rect;
    if (anchorRect && info.position === 'static' && which === '::before'){
      const er = el.getBoundingClientRect();
      rect = { x: er.x + px(getComputedStyle(el).paddingLeft),
               y: anchorRect.y + Math.max(0, (anchorRect.h - info.h) / 2),
               w: info.w, h: info.h };
    } else if (info.rect){
      rect = { x: info.rect.x, y: info.rect.y, w: info.w, h: info.h };
    } else {
      const er = el.getBoundingClientRect();
      rect = { x: er.x + px(getComputedStyle(el).paddingLeft),
               y: er.y + px(getComputedStyle(el).paddingTop), w: info.w, h: info.h };
    }
    els.push({ kind: 'pseudo', order, zIndex: String(itemZ || 0), rect, paras: info.paras,
               box: Object.assign({}, info.box, { opacity: op === undefined ? 1 : op }), path: CUR_PATH });
  }

  function ctmOf(s){
    try { const m = s.getCTM(); return m ? [m.a, m.b, m.c, m.d, m.e, m.f] : null; }
    catch (e) { return null; }
  }

  function svgDefs(svg){
    const out = {};
    for (const gdef of svg.querySelectorAll('linearGradient, radialGradient')){
      const stops = [];
      for (const st of gdef.querySelectorAll('stop')){
        const oa = st.getAttribute('offset') || '0';
        let off = oa.endsWith('%') ? parseFloat(oa) : parseFloat(oa) * 100;
        if (!isFinite(off)) off = 0;
        const cs = getComputedStyle(st);
        const so = parseFloat(cs.stopOpacity === undefined ? st.getAttribute('stop-opacity') || '1' : cs.stopOpacity);
        stops.push({ off, hex: (cs.stopColor && cs.stopColor.startsWith('rgb')) ? cs.stopColor : (st.getAttribute('stop-color') || '#000'), so: isFinite(so) ? so : 1 });
      }
      const num = (v, d) => { const f = parseFloat(v); return isFinite(f) ? f : d; };
      const hasAlpha = stops.some(s => s.so < 0.999);
      if (gdef.tagName.toLowerCase() === 'radialgradient'){
        out[gdef.id] = { kind: 'radial', stops, hasAlpha,
          cx: num(gdef.getAttribute('cx'), 50), cy: num(gdef.getAttribute('cy'), 50), r: num(gdef.getAttribute('r'), 50),
          units: gdef.getAttribute('gradientUnits') || 'objectBoundingBox' };
      } else {
        out[gdef.id] = { kind: 'linear', stops, hasAlpha,
          x1: num(gdef.getAttribute('x1'), 0), y1: num(gdef.getAttribute('y1'), 0),
          x2: num(gdef.getAttribute('x2'), 100), y2: num(gdef.getAttribute('y2'), 100),
          units: gdef.getAttribute('gradientUnits') || 'objectBoundingBox' };
      }
    }
    return out;
  }

  function gradRef(fill){
    const m = /url\(["']?#([^)"']+)/.exec(fill || '');
    return m ? m[1] : null;
  }

  function svgMarkers(svg){
    const out = {};
    for (const mk of svg.querySelectorAll('marker')){
      const poly = mk.querySelector('polygon');
      if (!poly) continue;
        const pv = poly.points ? (poly.points.baseVal || poly.points) : null;
      const pts = [];
      if (pv){ for (let i = 0; i < pv.numberOfItems; i++) pts.push([pv.getItem(i).x, pv.getItem(i).y]); }
      if (!pts.length) continue;
      const num = (v, d) => { const f = parseFloat(v); return isFinite(f) ? f : d; };
      out[mk.id] = { refX: num(mk.getAttribute('refX'), 0), refY: num(mk.getAttribute('refY'), 0),
        units: mk.getAttribute('markerUnits') || 'strokeWidth',
        pts, fill: getComputedStyle(poly).fill };
    }
    return out;
  }

  function svgCollect(svg, cOp){
    const gdefs = svgDefs(svg);
    const mdefs = svgMarkers(svg);
    const r = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const sc = (vb && vb.width) ? { sx: r.width / vb.width, sy: r.height / vb.height,
      ox: -vb.x * r.width / vb.width, oy: -vb.y * r.height / vb.height } : { sx: 1, sy: 1, ox: 0, oy: 0 };
    const out = [];
    let alphaGrad = false;   // any gradient with transparent stops (LO renders these wrongly -> whole-svg fallback)
    for (const s of svg.querySelectorAll('circle,ellipse,rect,line,polyline,polygon,path,text,image')){
      if (s.closest('defs')) continue;   // defs/marker content: referenced, never painted
      const c = getComputedStyle(s);
      const fillStr = (c.fill !== 'none' && !gradRef(c.fill)) ? c.fill : null;
      const strokeStr = (c.stroke !== 'none' && !gradRef(c.stroke)) ? c.stroke : null;
      // stroke-width is in viewBox user units — scale to rendered px like the
      // geometry (getBoundingClientRect) already is
      // fill-opacity participates in the fill color (radar/venn translucent
      // fills): fold it into an rgba() string so python's parse_color keeps it
      const fo = parseFloat(c.fillOpacity);
      let fillCol = fillStr;
      if (fillCol && isFinite(fo) && fo < 0.999 && fillCol.indexOf('rgba') !== 0){
        const m6 = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(fillCol);
        if (m6) fillCol = 'rgba(' + m6[1] + ',' + m6[2] + ',' + m6[3] + ',' + fo + ')';
      }
      const sh = { tag: s.tagName.toLowerCase(),
        fill: fillCol, stroke: strokeStr, sw: px(c.strokeWidth) * (sc.sx + sc.sy) / 2, cap: c.strokeLinecap };
      const meM = /url\(#([^)]+)\)/.exec(s.getAttribute('marker-end') || '');
      if (meM && mdefs[meM[1]]) sh.markerEnd = mdefs[meM[1]];
      // CSS donut technique: circle stroked with dasharray = one arc segment
      // (dashoffset = start shift, rotate(a cx cy) = start rotation). Convert to
      // a native arc segment (OOXML BLOCK_ARC) — dash → prstDash would render a
      // repeating pattern at the wrong angles instead
      if (sh.tag === 'circle' && sh.stroke){
        const dash = (c.strokeDasharray && c.strokeDasharray !== 'none') ? c.strokeDasharray : null;
        if (dash){
          const nums = dash.split(/[\s,]+/).map(parseFloat).filter(v => isFinite(v));
          const rU = (s.r && s.r.baseVal) ? s.r.baseVal.value : 0;
          if (nums.length >= 1 && rU > 0){
            const L = nums[0], G = nums.length > 1 ? nums[1] : 0;
            const C = 2 * Math.PI * rU;
            if (L > 0 && L + G >= C - 0.5){
              let rot = 0, rotOk = true;
              const rotM = /rotate\(\s*([-\d.eE+]+)(?:[\s,]+([-\d.eE+]+))?(?:[\s,]+([-\d.eE+]+))?\s*\)/.exec(s.getAttribute('transform') || '');
              if (rotM){
                rot = parseFloat(rotM[1]);
                if (rotM[2] !== undefined){
                  const dx = parseFloat(rotM[2]) - s.cx.baseVal.value;
                  const dy = parseFloat(rotM[3] !== undefined ? rotM[3] : 0) - s.cy.baseVal.value;
                  if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) rotOk = false;  // pivot != center: arc would translate
                }
              }
              if (rotOk){
                const swU = px(c.strokeWidth);
                const swPx = swU * (sc.sx + sc.sy) / 2;
                const a0 = (((-px(c.strokeDashoffset)) / C * 360 + rot) % 360 + 360) % 360;
                const sweep = Math.min(360, L / C * 360);
                const cxp = s.cx.baseVal.value * sc.sx + sc.ox + r.x;
                const cyp = s.cy.baseVal.value * sc.sy + sc.oy + r.y;
                const Rout = rU * sc.sx + swPx / 2;
                out.push({ tag: 'arcseg',
                  rect: { x:+(cxp - Rout).toFixed(2), y:+(cyp - Rout).toFixed(2),
                          w:+(2 * Rout).toFixed(2), h:+(2 * Rout).toFixed(2) },
                  a0:+a0.toFixed(2), sweep:+sweep.toFixed(2),
                  holeT:+Math.min(0.9, swPx / (2 * Rout)).toFixed(4),
                  fill: sh.stroke, op: cOp, path: CUR_PATH });
                continue;
              }
            }
          }
        }
      }
      const gref = gradRef(c.fill);
      if (gref && gdefs[gref]){ sh.grad = gdefs[gref]; if (gdefs[gref].hasAlpha) alphaGrad = true; }
      const sref = gradRef(c.stroke);
      if (sref && gdefs[sref]){ sh.strokeGrad = gdefs[sref]; if (gdefs[sref].hasAlpha) alphaGrad = true; }
      {
        const b = s.getBoundingClientRect();
        sh.rect = { x:+b.x.toFixed(2), y:+b.y.toFixed(2), w:+b.width.toFixed(2), h:+b.height.toFixed(2) };
      }
      if (sh.tag === 'rect') sh.rx = (s.rx && s.rx.baseVal.value) || 0;
      if (sh.tag === 'line'){
        sh.x1 = +s.x1.baseVal.value; sh.y1 = +s.y1.baseVal.value;
        sh.x2 = +s.x2.baseVal.value; sh.y2 = +s.y2.baseVal.value;
        sh.fill = null;
      }
      if ((sh.tag === 'polyline' || sh.tag === 'polygon') && s.points){
        sh.pts = []; const pts = s.points.baseVal || s.points;
        for (let i = 0; i < pts.numberOfItems; i++) sh.pts.push([pts.getItem(i).x, pts.getItem(i).y]);
      }
      if (sh.tag === 'path'){
        sh.d = s.getAttribute('d');
        // gauge/progress technique: single-arc path (M .. A ..) stroked with a
        // dasharray segment -> native BLOCK_ARC arcseg, like donut circles
        const am = /^\s*[Mm]\s*([-\d.eE+]+)[,\s]+([-\d.eE+]+)\s*[Aa]\s*([-\d.eE+]+)[,\s]+([-\d.eE+]+)[,\s]+([-\d.eE+]+)[,\s]+([01])[, ]+([01])[, ]+([-\d.eE+]+)[,\s]+([-\d.eE+]+)\s*$/.exec(sh.d);
        const dashM = (c.strokeDasharray && c.strokeDasharray !== 'none') ? c.strokeDasharray : null;
        if (am && dashM && sh.stroke){
          const ax1 = +am[1], ay1 = +am[2], rx = +am[3], ry = +am[4], phiD = +am[5],
                laf = +am[6], sf = +am[7], ax2 = +am[8], ay2 = +am[9];
          const dnums = dashM.split(/[\s,]+/).map(parseFloat).filter(v => isFinite(v));
          if (Math.abs(rx - ry) < 0.5 && Math.abs(phiD) < 0.5 && dnums.length >= 1 && rx > 0){
            const rU = rx, L = dnums[0], G = dnums.length > 1 ? dnums[1] : 0;
            // endpoint -> center (SVG spec F.6.5, circular)
            const dx2 = (ax1 - ax2) / 2, dy2 = (ay1 - ay2) / 2;
            const lam = (dx2 * dx2 + dy2 * dy2) / (rU * rU);
            const sc2 = lam > 1 ? Math.sqrt(lam) : 1;
            const rxp = rU * sc2;
            const co = Math.sqrt(Math.max(0, rxp * rxp - dx2 * dx2 - dy2 * dy2)) * ((laf !== sf) ? 1 : -1);
            const cx = co * dy2 / rxp + (ax1 + ax2) / 2;
            const cy = -co * dx2 / rxp + (ay1 + ay2) / 2;
            const th1 = Math.atan2(ay1 - cy, ax1 - cx);
            let dth = Math.atan2(ay2 - cy, ax2 - cx) - th1;
            if (sf === 0 && dth > 0) dth -= 2 * Math.PI;
            if (sf === 1 && dth < 0) dth += 2 * Math.PI;
            const arcLen = rU * Math.abs(dth);
            if (arcLen > 1 && L + G >= arcLen - 0.5){
              const swU = px(c.strokeWidth);
              const swPx = swU * (sc.sx + sc.sy) / 2;
              const D = px(c.strokeDashoffset);
              let v0 = -D / arcLen;                       // visible window in path-length units
              let v1 = v0 + Math.min(L, arcLen);
              // clamp to [0, arcLen]; a dash crossing the path end wraps the ring
              const spans = [];
              const push = (p0, p1) => {
                let a = th1 + (p0 / arcLen) * dth, b = th1 + (p1 / arcLen) * dth;
                let A, B;
                if (sf === 1){ A = a; B = b; } else { A = b; B = a; }   // block arc sweeps clockwise
                const d0 = ((A * 180 / Math.PI) % 360 + 360) % 360;
                const swDeg = (B - A) * 180 / Math.PI;
                spans.push([d0, swDeg]);
              };
              if (v0 < 0){ push(0, Math.min(v1, arcLen)); if (v1 > arcLen) push(v0 + arcLen, arcLen); }
              else if (v1 > arcLen){ push(v0, arcLen); push(0, v1 - arcLen); }
              else push(v0, v1);
              // round linecap: the visible ink extends sw/2 past each dash end —
              // drawn as native cap circles (BLOCK_ARC has flat ends)
              let capPts = null;
              if (c.strokeLinecap === 'round' && swU > 0 && v1 - v0 < arcLen - 0.5){
                capPts = [[v0, v1].map(p => {
                  const th = th1 + (p / arcLen) * dth;
                  return [+(cx * sc.sx + sc.ox + r.x + rU * sc.sx * Math.cos(th)).toFixed(2),
                          +(cy * sc.sy + sc.oy + r.y + rU * sc.sy * Math.sin(th)).toFixed(2)];
                }), swPx];
              }
              for (const [d0, swDeg] of spans){
                if (swDeg < 0.5) continue;
              // BLOCK_ARC's center/radius come from its (full-circle square) box —
              // emit the whole-circle square; the swept angles select the arc
              const pcx = cx * sc.sx + sc.ox + r.x, pcy = cy * sc.sy + sc.oy + r.y;
              const Rout = rU * sc.sx + swPx / 2;
              const rect = { x:+(pcx - Rout).toFixed(2), y:+(pcy - Rout).toFixed(2),
                             w:+(2 * Rout).toFixed(2), h:+(2 * Rout).toFixed(2) };
                out.push({ tag: 'arcseg', rect,
                  a0:+d0.toFixed(2), sweep:+swDeg.toFixed(2),
                  holeT:+Math.min(0.9, swPx / (Math.max(rect.w, rect.h))).toFixed(4),
                  fill: sh.stroke, op: cOp, path: CUR_PATH });
              }
              if (capPts)
                out.push({ tag: 'arccaps', pts: capPts[0], d: capPts[1], fill: sh.stroke, op: cOp, path: CUR_PATH });
              continue;
            }
          }
        }
        // straight two-point path (M x,y L x,y) -> native connector in pptx
        const sm = /^\s*[Mm]\s*([-\d.eE+]+)[,\s]+([-\d.eE+]+)\s*[Ll]\s*([-\d.eE+]+)[,\s]+([-\d.eE+]+)\s*$/.exec(sh.d);
        if (sm) sh.straight = [+sm[1], +sm[2], +sm[3], +sm[4]];
      }
      if (['line','polyline','polygon','path'].includes(sh.tag)){
        sh.ctm = ctmOf(s);
        // round linecap on stroked open shapes -> cap circles at both endpoints
        if (sh.stroke && px(c.strokeWidth) > 0 && c.strokeLinecap === 'round' && sh.tag !== 'polygon'){
          let ep = null;
          if (sh.tag === 'line') ep = [[sh.x1, sh.y1], [sh.x2, sh.y2]];
          else if (sh.tag === 'polyline' && sh.pts) ep = [sh.pts[0], sh.pts[sh.pts.length - 1]];
          else if (sh.tag === 'path'){
            const nums = (sh.d.match(/[-\d.eE+]+/g) || []).map(Number);
            if (nums.length >= 4) ep = [[nums[0], nums[1]], [nums[nums.length - 2], nums[nums.length - 1]]];
          }
          if (ep) sh.capEnds = ep.map(([ux, uy]) => [+(ux * sc.sx + sc.ox + r.x).toFixed(2),
                                                     +(uy * sc.sy + sc.oy + r.y).toFixed(2)]);
        }
      }
      sh.dash = (c.strokeDasharray && c.strokeDasharray !== 'none') ? c.strokeDasharray : null;
      if (sh.tag === 'image'){
        sh.href = s.getAttribute('href') || s.getAttributeNS('http://www.w3.org/1999/xlink', 'href');
        const cp = (s.getAttribute('clip-path') || '');
        const cm = /url\(["']?#([^)"']+)/.exec(cp);
        if (cm){
          const cpEl = svg.querySelector('#' + CSS.escape(cm[1]) + ' > *');
          if (cpEl){
            sh.clipShape = cpEl.tagName.toLowerCase();
            const dd = cpEl.getAttribute('d') || '';
            sh.clipCurved = /[ACQS]/i.test(dd);
            sh.clipStraight = /[LlHhVv]/.test(dd);
          }
        }
      }
      if (sh.tag === 'text'){
        const rng = document.createRange(); rng.selectNodeContents(s);
        const tb = rng.getBoundingClientRect();
        sh.rect = { x:+tb.x.toFixed(2), y:+tb.y.toFixed(2), w:+tb.width.toFixed(2), h:+tb.height.toFixed(2) };
        sh.content = s.textContent.replace(/\s+/g, ' ').trim();
        // SVG text font-size is in user units: multiply by the viewBox->viewport
        // scale or the emitted run renders (1/scale)x too small text in (1/scale)x
        // narrower boxes — the GLM architecture page rendered all labels ~26% large
        sh.fs = px(c.fontSize) * (sc.sx + sc.sy) / 2;
        sh.anchor = c.textAnchor; sh.fw = c.fontWeight; sh.lh = c.lineHeight;
        // multi-line <text> (positioned tspans): one row per y-cluster instead of
        // concatenated textContent
        const tsp = [...s.querySelectorAll('tspan')];
        if (tsp.length > 1){
          const rows = [];
          for (const ts of tsp){
            const tr2 = ts.getBoundingClientRect();
            if ((!tr2.width && !tr2.height)) continue;
            const t = ts.textContent.replace(/\s+/g, ' ').trim();
            if (!t) continue;
            const hit = rows.find(rw =>
              (Math.min(rw.rect.y + rw.rect.h, tr2.bottom) - Math.max(rw.rect.y, tr2.top)) >
              0.3 * Math.min(rw.rect.h, tr2.height));
            if (hit){
              const nx = Math.min(hit.rect.x, tr2.x), ny = Math.min(hit.rect.y, tr2.y);
              const nr = Math.max(hit.rect.x + hit.rect.w, tr2.right);
              const nb = Math.max(hit.rect.y + hit.rect.h, tr2.bottom);
              hit.rect = { x:+nx.toFixed(2), y:+ny.toFixed(2), w:+(nr-nx).toFixed(2), h:+(nb-ny).toFixed(2) };
              hit.text += ' ' + t;
            } else {
              rows.push({ rect: { x:+tr2.x.toFixed(2), y:+tr2.y.toFixed(2), w:+tr2.width.toFixed(2), h:+tr2.height.toFixed(2) }, text: t });
            }
          }
          rows.sort((a2, b2) => a2.rect.y - b2.rect.y);
          if (rows.length > 1) sh.tspans = rows;
        }
      }
      out.push(sh);
    }
    return { rect: {x:+r.x.toFixed(2), y:+r.y.toFixed(2), w:+r.width.toFixed(2), h:+r.height.toFixed(2)}, sc, shapes: out, alphaGrad };
  }

  const els = []; let order = 0;
  let CUR_PATH = '';   // dom path of the element being visited (for conversion report)

  const bodyRect = document.body.getBoundingClientRect();
  const CW = bodyRect.width, CH = bodyRect.height;   // canvas = slide container size
  function itemZof(c, inhZ){
    const oz = (c.zIndex !== 'auto' && c.position !== 'static') ? parseInt(c.zIndex) : null;
    return (oz !== null) ? oz : (inhZ || 0);   // keep negative z negative (paints below zero-z siblings)
  }

  function visit(el, inhZ, inhOp){
    const c = getComputedStyle(el);
    const r = rectOf(el);
    const cOp = (parseFloat(c.opacity) || 0) * (inhOp === undefined ? 1 : inhOp);
    if (c.display === 'none' || c.visibility === 'hidden' || cOp === 0) return;
    // entirely outside the canvas (clipped by overflow:hidden in the browser)
    if (r.x >= bodyRect.x + CW - 1 || r.y >= bodyRect.y + CH - 1 ||
        r.x + r.w <= bodyRect.x + 1 || r.y + r.h <= bodyRect.y + 1) return;
    // dom path like body[1]/div[2]/span[3] (same-tag index) for report readability
    let _idx = 1;
    if (el.parentElement) for (const s of el.parentElement.children){
      if (s === el) break;
      if (s.tagName === el.tagName) _idx++;
    }
    const _prev = CUR_PATH;
    CUR_PATH = _prev + (_prev ? '/' : '') + el.tagName.toLowerCase() + '[' + _idx + ']';
    if (el instanceof SVGElement){
      if (el.tagName === 'svg'){
        const sc2 = svgCollect(el, cOp);
        if (sc2.alphaGrad)
          els.push({ kind: 'fallback', order: order++, zIndex: String(itemZof(c, inhZ)), rect: r, why: 'svg-alpha-gradient', path: CUR_PATH, op: cOp });
        else
          els.push({ kind: 'svg', order: order++, zIndex: String(itemZof(c, inhZ)), ...sc2, path: CUR_PATH });
        CUR_PATH = _prev;
        return;
      }
      CUR_PATH = _prev;
      return;
    }
    if (el.tagName === 'TABLE'){
      const t = { kind: 'table', order: order++, zIndex: String(itemZof(c, inhZ)), rect: r, box: boxStyle(c), rows: [], shapes: [], path: CUR_PATH };
      for (const tr of el.rows){
        const row = [];
        // zebra stripes / row rules are painted on the ROW (tr:nth-child rules),
        // not the cell — a transparent cell shows the row's paint through.
        // The cell-only collector used to drop them silently (empty report,
        // stripes gone). Inherit row-level bg / border-top onto cells whose own
        // is unset — matches browser compositing (cell over row over tbody);
        // a cell with its OWN bg/border always wins, same as border-collapse
        const rc = getComputedStyle(tr);
        const rowBg = rc.backgroundColor !== 'rgba(0, 0, 0, 0)' ? rc.backgroundColor : null;
        const rowBt = (rc.borderTopStyle !== 'none' && rc.borderTopStyle !== 'hidden' && px(rc.borderTopWidth) > 0.3)
          ? [px(rc.borderTopWidth), rc.borderTopStyle, rc.borderTopColor] : null;
        for (const cell of tr.cells){
          const cb = boxStyle(getComputedStyle(cell));
          if (rowBg && cb.bg === 'rgba(0, 0, 0, 0)') cb.bg = rowBg;
          if (rowBt && cb.bt[0] <= 0.3 && (cb.bt[1] === 'none' || cb.bt[1] === 'hidden')) cb.bt = rowBt;
          row.push({ rect: rectOf(cell), box: cb,
                     paras: segsToParas(cellSegs(cell)), tag: cell.tagName,
                     colspan: cell.colSpan, rowspan: cell.rowSpan });
          for (const shp of cellShapes(cell))
            t.shapes.push({ ...shp, cell: { x: cell.getBoundingClientRect().x, y: cell.getBoundingClientRect().y } });
        }
        t.rows.push(row);
      }
      els.push(t); CUR_PATH = _prev; return;
    }
    if (el.tagName === 'IMG'){
      const src = el.currentSrc || el.src;
      if (src) els.push({ kind: 'image', order: order++, zIndex: String(itemZof(c, inhZ)), rect: r, src,
        radius: c.borderTopLeftRadius, fit: c.objectFit, op: cOp,
        shadow: c.boxShadow === 'none' ? null : c.boxShadow, path: CUR_PATH });
      CUR_PATH = _prev;
      return;
    }
    const ownZ = (c.zIndex !== 'auto' && c.position !== 'static') ? parseInt(c.zIndex) : null;
    const ctxZ = (ownZ !== null) ? ownZ : inhZ;   // stacking context floor for descendants
    const itemZ = (ownZ !== null) ? ownZ : (inhZ || 0);
    // content we cannot map natively -> one screenshot crop covering the element
    // (children skipped: their rects are post-transform / inside the filtered or clipped subtree)
    let why = el.tagName === 'CANVAS' ? 'canvas' : el.tagName === 'IFRAME' ? 'iframe'
      : el.tagName === 'VIDEO' ? 'video' : (el.tagName === 'OBJECT' || el.tagName === 'EMBED') ? 'embed'
      : c.filter !== 'none' ? 'filter' : c.transform !== 'none' ? 'transform'
      : c.clipPath !== 'none' ? 'clip-path' : null;
    // transform/clip-path/filter fallback only for elements with OWN visible
    // styling (a rotated card's bg can't be reproduced natively). Transparent
    // containers must NOT fall back: their children are emitted individually at
    // post-transform rects, and a screenshot band would double-draw them
    // clip-path:polygon(...) with real styling -> native freeform. Parse the
    // vertex list here; actual emission happens after paras/lines are collected
    let polyPts = null;
    if (why === 'clip-path' && selfStyled(el)){
      const pm = /polygon\(([^)]*)\)/.exec(c.clipPath);
      if (pm){
        const toks = pm[1].split(/[\s,]+/).filter(t => t.length);
        const pts = [];
        for (let i = 0; i + 1 < toks.length; i += 2){
          const nx = parseFloat(toks[i]), ny = parseFloat(toks[i + 1]);
          if (!isFinite(nx) || !isFinite(ny)) { pts.length = 0; break; }
          pts.push([nx / 100, ny / 100]);   // percent of box
        }
        if (pts.length >= 3) polyPts = pts;
      }
    }
    if (polyPts) why = null;   // handled natively below
    if (why === 'transform' || why === 'clip-path' || why === 'filter'){
      // keep the fallback for elements that both look styled AND carry real
      // content (a rotated card with text). A faint-alpha decorative band with
      // no content must be skipped: its screenshot crop spans other elements'
      // pixels and double-draws them under the natively emitted content
      const substance = el.textContent.trim() || el.querySelector('img,canvas,svg,video,iframe');
      if (!selfStyled(el) || !substance) why = null;
    }
    if (why){
      els.push({ kind: 'fallback', order: order++, zIndex: String(itemZ), rect: r, why, path: CUR_PATH, op: cOp });
      CUR_PATH = _prev;
      return;
    }
    // conic-gradient: OOXML has no native equivalent and leaving the box empty
    // loses the chart — screenshot fallback carries the pixels
    if (c.backgroundImage && c.backgroundImage.indexOf('conic-gradient') >= 0){
      els.push({ kind: 'fallback', order: order++, zIndex: String(itemZ), rect: r, why: 'conic-gradient', path: CUR_PATH, op: cOp });
      CUR_PATH = _prev;
      return;
    }
    const bo = () => { const b = boxStyle(c); b.opacity = cOp; return b; };
    // CSS background of an SVG data-URI: python-pptx can't embed SVG and LO
    // won't rasterize it -> screenshot fallback carries the pixels instead
    let bgU = null;
    if (c.backgroundImage !== 'none' && c.backgroundImage.indexOf('url(') >= 0){
      const mU = c.backgroundImage.match(/url[(]["']?([^"')]+)["']?[)]/);
      if (mU) bgU = mU[1];
    }
    if (bgU && /data:image\/svg/i.test(bgU)){
      els.push({ kind: 'fallback', order: order++, zIndex: String(itemZ), rect: r, why: 'svg-bg-image', path: CUR_PATH, op: cOp });
      CUR_PATH = _prev;
      return;
    }
    const before = pseudoStyle(el, '::before');
    const after = pseudoStyle(el, '::after');
    const kids = [...el.children];
    const isFlex = c.display.startsWith('flex');
    // unstyled inline labels inside a flex container get blockified by CSS — keep them in the parent's text flow;
    // styled inline elements (chips/tags/pills) become their own boxes
    const inlineChild = (ch) => !selfStyled(ch) && !hasStyledDesc(ch) &&
      (isInlineEl(ch) || (isFlex && INLINE_FMT.has(ch.tagName)));
    const parasSegs = inlineSegs(el, isFlex);
    const paras = segsToParas(parasSegs);
    const lines = segsToLines(parasSegs);   // null when measurement fails (flow fallback)
    const svgKids = kids.filter(ch => ch instanceof SVGElement && ch.tagName === 'svg');
    const blockKids = kids.filter(ch => !(ch instanceof SVGElement) && !inlineChild(ch));
    const isLeaf = blockKids.length === 0;
    const gradText = c.backgroundClip === 'text';
    const sb = {
      bg: c.backgroundColor !== 'rgba(0, 0, 0, 0)',
      img: c.backgroundImage !== 'none' && !gradText,
      bd: [[c.borderTopWidth, c.borderTopStyle],[c.borderRightWidth, c.borderRightStyle],
           [c.borderBottomWidth, c.borderBottomStyle],[c.borderLeftWidth, c.borderLeftStyle]]
          .some(b => px(b[0]) > 0.3 && b[1] !== 'none'),
      sh: c.boxShadow !== 'none'
    };

    const styled = sb.bg || sb.img || sb.bd || sb.sh;
    if (polyPts){
      const bc = boxStyle(c); bc.opacity = cOp;
      els.push({ kind: 'polyclip', order: order++, zIndex: String(itemZ), rect: r,
                 pts: polyPts, box: bc, path: CUR_PATH,
                 paras: (isLeaf && paras.length) ? paras : null,
                 ...(isLeaf && lines ? { lines } : {}) });
      for (const sv of svgKids) els.push({ kind: 'svg', order: order++, zIndex: String(itemZ), ...svgCollect(sv, cOp), path: CUR_PATH });
      for (const ch of blockKids) visit(ch, ctxZ, cOp);
      if (after) emitPseudo(el, after, '::after', order++, null, itemZ, cOp);
      CUR_PATH = _prev;
      return;
    }
    const contentOrigin = () => ({ x: r.x + px(c.paddingLeft), y: r.y + px(c.paddingTop),
        w: Math.max(8, r.w - px(c.paddingLeft) - px(c.paddingRight)),
        h: Math.max(14, r.h - px(c.paddingTop) - px(c.paddingBottom)) });
    const pushBefore = (anchorRect) => {
      if (before) emitPseudo(el, before, '::before', order++, anchorRect || contentOrigin(), itemZ, cOp);
    };
    const pushRangeText = (rect, paras_, cbox, flowOnly) => {
      els.push({ kind: 'text', order: order++, zIndex: c.zIndex,
        rect: { x:+rect.x.toFixed(2), y:+rect.y.toFixed(2), w:+(rect.width != null ? rect.width : rect.w).toFixed(2), h:+(rect.height != null ? rect.height : rect.h).toFixed(2) },
        paras: paras_, box: cbox, path: CUR_PATH, ...(flowOnly ? { flowOnly: true } : {}) });
    };
    const pushContainerText = (cbox, withBefore) => {
      let pushed = false;
      if (lines && lines.length){
        // line mode: ONE item carrying every measured visual line of this container
        // (consumed by --text-mode line; the per-node items below are flowOnly)
        let uL = Infinity, uT = Infinity, uR = -Infinity, uB = -Infinity;
        for (const l of lines){
          uL = Math.min(uL, l.rect.x); uT = Math.min(uT, l.rect.y);
          uR = Math.max(uR, l.rect.x + l.rect.w); uB = Math.max(uB, l.rect.y + l.rect.h);
        }
        els.push({ kind: 'text', order: order++, zIndex: String(itemZ), lineOnly: true,
                   rect: { x:+uL.toFixed(2), y:+uT.toFixed(2), w:+(uR - uL).toFixed(2), h:+(uB - uT).toFixed(2) },
                   lines, box: cbox, path: CUR_PATH });
      }
      for (const n of el.childNodes){
        if (n.nodeType === 3 && n.textContent.trim()){
          const rng = document.createRange(); rng.selectNodeContents(n);
          const tr = rng.getBoundingClientRect();
          if (tr.width >= 2 && tr.height >= 2){
            if (withBefore && before && !pushed) pushBefore({ x: tr.x, y: tr.y, w: tr.width, h: tr.height });
            pushRangeText(tr, [[{ t: transformText(n.textContent.replace(/\s+/g, ' ').trim(), runStyle(n)), st: runStyle(n) }]], cbox, true);
            pushed = true;
          }
        } else if (n.nodeType === 1 && !(n instanceof SVGElement) && !selfStyled(n) && !hasStyledDesc(n) &&
                   (isInlineEl(n) || (isFlex && INLINE_FMT.has(n.tagName)))){
          const rng = document.createRange(); rng.selectNodeContents(n);
          const tr = rng.getBoundingClientRect();
          if (tr.width >= 2 && tr.height >= 2){
            if (withBefore && before && !pushed) pushBefore({ x: tr.x, y: tr.y, w: tr.width, h: tr.height });
            pushRangeText(tr, inlineFrom(n, false), cbox, true);
            pushed = true;
          }
        }
      }
      if (!pushed){
        if (withBefore && before) pushBefore(contentOrigin());
        pushRangeText(contentOrigin(), paras, cbox, true);
      }
    };

    if (styled){
      const leafText = isLeaf && paras.length;
      els.push({ kind: 'box', order: order++, zIndex: String(itemZ), rect: r,
                 paras: leafText ? paras : null, box: bo(), path: CUR_PATH,
                 ...(leafText && lines ? { lines } : {}) });
      if (!leafText && paras.length) pushContainerText(bo(), false);
      if (before) pushBefore(null);
    } else if (isLeaf && paras.length){
      // x: union of descendant TEXT NODE rects (inline icons/svgs excluded so the
      //    text box never covers them); y/h: element content box (CSS line layout)
      const contentL = r.x + px(c.paddingLeft);
      const contentR = r.x + r.w - px(c.paddingRight);
      let tr = { x: contentL, y: r.y + px(c.paddingTop),
                 w: Math.max(8, contentR - contentL),
                 h: Math.max(14, r.h - px(c.paddingTop) - px(c.paddingBottom)) };
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let uL = null, uR = null;
      while (walker.nextNode()){
        const n = walker.currentNode;
        if (!n.textContent.trim()) continue;
        const rng = document.createRange(); rng.selectNodeContents(n);
        const b = rng.getBoundingClientRect();
        if (b.width < 1) continue;
        if (uL === null){ uL = b.x; uR = b.x + b.width; }
        else { uL = Math.min(uL, b.x); uR = Math.max(uR, b.x + b.width); }
      }
      if (uL !== null && uR - uL > 2 && uL >= contentL - 2 && uL <= contentR){
        tr = { x: uL, y: tr.y, w: Math.max(8, contentR - uL), h: tr.h };
      }
      if (c.display === 'list-item' && c.listStyleType && c.listStyleType !== 'none' && c.listStylePosition !== 'inside'){
        const fsM = px(c.fontSize);
        let label = ({disc:'\u2022', circle:'\u25CB', square:'\u25AA'})[c.listStyleType] || null;
        if (c.listStyleType === 'decimal' || c.listStyleType === 'decimal-leading-zero'){
          let idx = 1;
          for (const sib of el.parentElement.children){
            if (sib === el) break;
            if (getComputedStyle(sib).display === 'list-item') idx++;
          }
          label = (c.listStyleType === 'decimal-leading-zero' && idx < 10 ? '0' : '') + idx + '.';
        }
        if (!label) label = '\u2022';
        // hang the marker where the browser does — LEFT of the content box
        // (clamping it inside caused overlap, which LibreOffice renders broken)
        const xM = r.x + px(c.paddingLeft) - fsM * 1.35;
        // marker is deferred: pushed AFTER the li text item below — overlapping
        // boxes paint in emission order in LibreOffice, an earlier marker gets covered
      // separate marker textbox: hangs LEFT of the content box (LO renders
      // overlapping/shrunken markers otherwise). +0.06em vertical compensation
      // calibrated in TestCase/vcalib.py. A native buChar variant was tried and
      // reverted: LO wraps bulleted paragraphs even with wrap=none (see DEFECTS)
      var markerItem = { kind: 'text', order: 0, zIndex: c.zIndex,
          rect: { x: xM, y: r.y + px(c.paddingTop) + fsM * 0.06, w: fsM * 1.25, h: Math.max(14, r.h - px(c.paddingTop) - px(c.paddingBottom)) },
          paras: [[{ t: label, st: { color: c.color, fw: c.fontWeight, fs: fsM, ls: 0, fst: 'normal', td: 'none', pre: false } }]],
          path: CUR_PATH,
          box: { display: 'block', ai: 'center', jc: '', position: 'static', zIndex: 'auto', opacity: cOp,
                 bg: 'rgba(0, 0, 0, 0)', bgImg: 'none', bgClip: 'border-box', bs: 'auto',
                 pt: 0, pr: 0, pb: 0, pl: 0,
                 bt: [0,'none',''], br_: [0,'none',''], bb: [0,'none',''], bl: [0,'none',''],
                 radius: ['0','0','0','0'], shadow: null, ta: 'right', lh: c.lineHeight, col: c.color, fs: fsM, ff: c.fontFamily } };
      }
      if (before) emitPseudo(el, before, '::before', order++, tr, itemZ, cOp);
      els.push({ kind: 'text', order: order++, zIndex: String(itemZ), rect: tr, paras, box: bo(),
                 path: CUR_PATH, ...(lines ? { lines } : {}) });
      if (typeof markerItem !== 'undefined' && markerItem){ markerItem.order = order++; markerItem.zIndex = String(itemZ); els.push(markerItem); markerItem = null; }
    } else if (!isLeaf && paras.length){
      pushContainerText(bo(), true);
    }
    for (const sv of svgKids){
      const sc2 = svgCollect(sv, cOp);
      if (sc2.alphaGrad)
        els.push({ kind: 'fallback', order: order++, zIndex: String(itemZ), rect: rectOf(sv), why: 'svg-alpha-gradient', path: CUR_PATH, op: cOp });
      else
        els.push({ kind: 'svg', order: order++, zIndex: String(itemZ), ...sc2, path: CUR_PATH });
    }
    for (const ch of blockKids) visit(ch, ctxZ, cOp);
    if (after) emitPseudo(el, after, '::after', order++, null, itemZ, cOp);
    CUR_PATH = _prev;
  }

  function collect(){
    visit(document.body, 0);
    const bodyStyle = getComputedStyle(document.body);
    const htmlStyle = getComputedStyle(document.documentElement);
    return { schema: 2, page: { w: Math.round(CW) || 1280,
      h: Math.round(CH) || 768,
      url: location.href,
      bodyBg: bodyStyle.backgroundColor, bodyBgImg: bodyStyle.backgroundImage,
      htmlBg: htmlStyle.backgroundColor }, els };
  }
  return (document.fonts && document.fonts.ready)
    ? document.fonts.ready.then(() => collect()).catch(() => collect())
    : Promise.resolve(collect());
})()
