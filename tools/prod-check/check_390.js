// 本番確認（prod_check.py）が、スマホの幅（390px）で開いたページの中で走らせる判定（e の6項目）。
// prod_check.py がこのファイルを読み、ブラウザの中で1回呼ぶ。項目ごとに {n: 数, ex: [例（最大3つ）]} を返す。
// 値（16px・44px・4.5）はこのファイルに書いた決まった値で、引数では変えられない。
// 引数: {width: 画面の幅, header: ヘッダーのセレクタ（渡さないときは null。null ならヘッダーの重なりは見ない）}
// 作: ひとりAIファクトリー hitori-ai-factory.com（MIT License）
async ({width, header}) => {
  const vw = window.innerWidth;
  const res = {};
  const desc = (el) => {
    const t = (el.innerText || el.getAttribute('alt') || '').trim().replace(/\s+/g, ' ').slice(0, 24);
    const c = (el.className && typeof el.className === 'string' && el.className.trim()) ? '.' + el.className.trim().split(/\s+/)[0] : '';
    return el.tagName.toLowerCase() + c + (t ? '「' + t + '」' : '');
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const push = (k, ex) => { res[k] = res[k] || {n: 0, ex: []}; res[k].n++; if (res[k].ex.length < 3) res[k].ex.push(ex); };

  // 1. 横スクロール: 文書の幅が画面の幅より広い
  const sw = document.documentElement.scrollWidth;
  if (sw > vw + 1) push('横スクロール', '文書の幅 ' + sw + 'px（画面 ' + vw + 'px）');

  // 文字を直接持つ要素（<main> の中。<main> が無いページは <body> の中）
  const main = document.querySelector('main') || document.body;
  const textEls = [...main.querySelectorAll('*')].filter(el => visible(el) &&
    [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0));

  // 2. 16px 未満の文字
  if (width < 640) textEls.forEach(el => { if (parseFloat(getComputedStyle(el).fontSize) < 15.95) push('16px 未満の文字', desc(el)); });

  // 3. 幅より広い要素: 表・図・画像・コードの枠が画面の右端を越える（横スクロールの枠の中は除く）
  const inScroller = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll') return true; } return false; };
  main.querySelectorAll('table, pre, img, figure, picture, video, iframe').forEach(el => {
    if (!visible(el)) return;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 && !inScroller(el)) push('幅より広い要素', desc(el));
  });

  // 5. 押す部分が 44px 未満: リンク・ボタンの高さか幅が 44px 未満（文の流れの中のリンクは除く）
  const inlineInText = (a) => { const s = getComputedStyle(a); if (s.display !== 'inline') return false;
      const p = a.parentElement; if (!p) return false;
      const own = [...p.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
      return own && ['P', 'LI', 'TD', 'TH', 'DD', 'FIGCAPTION', 'BLOCKQUOTE', 'SPAN'].includes(p.tagName); };
  document.querySelectorAll('a[href], button, [role="button"], summary, input, select').forEach(el => {
    if (!visible(el) || inlineInText(el)) return;
    const r = el.getBoundingClientRect();
    if (r.height < 44 || r.width < 44) push('押す部分が 44px 未満', desc(el));
  });

  // 6. 明度差 4.5 未満: 文字の色と、その下の背景の色のコントラスト比
  const rgb = (s) => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(',').map(x => parseFloat(x));
      return {r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1}; };
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = (el) => { for (let p = el; p; p = p.parentElement) { const c = rgb(getComputedStyle(p).backgroundColor);
      if (c && c.a > 0.5) return c; } return {r: 255, g: 255, b: 255, a: 1}; };
  textEls.forEach(el => { const fg = rgb(getComputedStyle(el).color); if (!fg) return; const bg = bgOf(el);
      const l1 = lum(fg), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      if (ratio < 4.5) push('明度差 4.5 未満', desc(el)); });

  // 4. ヘッダーが見出しに重なる: 見出しや id の付いた要素へ飛んだとき、ヘッダーの下端が要素の上端より下に来る
  //    （header を渡したときだけ。渡したのにページに無いときは header_missing を返す）
  if (header) {
    const h = document.querySelector(header);
    if (!h) {
      res.header_missing = true;
    } else {
      const targets = [...main.querySelectorAll('h1, h2, [id]')].slice(0, 30);
      for (const el of targets) {
        el.scrollIntoView({block: 'start'});
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        const hb = h.getBoundingClientRect().bottom, t = el.getBoundingClientRect().top;
        if (hb > t + 1) push('ヘッダーが見出しに重なる', el.tagName.toLowerCase() + '「' + (el.innerText || el.id).trim().slice(0, 20) +
          '」（ヘッダーの下端 ' + Math.round(hb) + 'px・見出しの上端 ' + Math.round(t) + 'px）');
      }
      window.scrollTo(0, 0);
    }
  }
  return res;
}
