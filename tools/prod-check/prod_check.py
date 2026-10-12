#!/usr/bin/env python3
"""本番確認（prod_check）── push のあとに、公開中のページを1ページずつ確かめる。

見るもの（ページごと）:
  a 開けるか   ページが 200 で開けるか。--dist で手元の出力（build したフォルダ）を渡したときは、
               <main> の中が手元の同じページと同じになったかも見る。そろわなければ 30秒おきに最大3分待ち、
               それでもそろわなければ「未」。比べる前に、両方から @ を含む語と、メール保護のリンク
               （/cdn-cgi/l/email-protection へのリンクと、class が __cf_email__ の要素）を外す。
               手元の出力に無いページと、<main> の無いページは 200 だけを見る
  b OG         og:title・og:description・og:image の3つの meta があり、og:image の URL が 200 で開けるか
               （meta の属性の順は問わない。property でも name でも読む）
  c 画像       スマホの幅（390px）でページを最後までスクロールして、ブラウザが img から読んだ画像のうち、
               いちばん大きい1枚が上限（--img-limit-kb・既定 300KB）以下か。合計は値だけ出す
  e 390px      スマホの幅（390px）での6項目（横スクロール・16px 未満の文字・幅より広い要素・
               ヘッダーが見出しに重なる・押す部分が 44px 未満・明度差 4.5 未満）が全部 0 か。
               判定は同じフォルダの check_390.js。ヘッダーの重なりは --header でセレクタを渡したときだけ見る
1つでも × か「未」があれば、終了コード 1 で止まる。直すのは人。

見るページ: --urls で渡した URL（パスか、--site と同じドメインの完全な URL）。渡さないときは、
  サイトの sitemap.xml に書かれたページ（sitemap の索引なら、1段だけたどる）。

使い方:
    python3 prod_check.py --site https://example.com                                  # sitemap.xml の全ページ
    python3 prod_check.py --site https://example.com --urls /posts/hello/ /about/     # 渡したページだけ
    python3 prod_check.py --site https://example.com --dist ./public                  # 手元の出力とも比べる
    python3 prod_check.py --site https://example.com --header .site-header --log ~/prod_check.jsonl
      --header セレクタ: 上に固定したヘッダー（例: .site-header・header）。渡したときだけ重なりを見る
      --img-limit-kb N: 画像1枚の上限（KB・既定 300）
      --log ファイル: 結果を1行（JSON）追記する（任意。渡さないときはどこにも書かない）
本番のページは、URL の後ろにキャッシュよけの問い合わせ文字列（?pc=<時刻>）を付けて読む。
終了コード: 全部 ○ なら 0、× か「未」が1つでもあれば 1、確かめられなかったとき
  （Playwright か Chromium が無い・sitemap.xml を読めない・ほかのドメインの URL を渡した・--dist のフォルダが無いなど）は 2
用意するもの: Python 3 と Playwright（pip install playwright）と Chromium（playwright install chromium）
作: ひとりAIファクトリー hitori-ai-factory.com（MIT License）
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
CHECK_JS = HERE / "check_390.js"
WAIT_MAX, WAIT_STEP = 180, 30   # a: 30秒おきに最大3分
WIDTH, HEIGHT = 390, 844
UA = {"User-Agent": "prod-check (+https://github.com/mhitori/haif-tools)"}
ITEMS = ["横スクロール", "16px 未満の文字", "幅より広い要素", "ヘッダーが見出しに重なる", "押す部分が 44px 未満", "明度差 4.5 未満"]


class CannotCheck(Exception):
    """確かめられなかった（終了コード 2）。"""


def fetch(url, bust=True):
    """(応答の番号, 本文 or None)。bust のときはキャッシュよけの ?pc=<時刻> を付ける。"""
    if bust:
        url = f"{url}{'&' if '?' in url else '?'}pc={int(time.time())}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def text_of(raw):
    return raw.decode("utf-8", "replace") if raw is not None else None


# --- a: <main> の比べ方 ---------------------------------------------------------------------------
MAIN_RE = re.compile(r"<main\b[^>]*>(.*)</main\s*>", re.S | re.I)
EMAIL_WORD_RE = re.compile(r"[^\s<>\"'（）()]*@[^\s<>\"'（）()]*")
CF_LINK_RE = re.compile(r"<a\b[^>]*href=\"/cdn-cgi/l/email-protection[^\"]*\"[^>]*>.*?</a\s*>", re.S | re.I)
CF_SPAN_RE = re.compile(r"<(\w+)\b[^>]*class=\"[^\"]*__cf_email__[^\"]*\"[^>]*>.*?</\1\s*>", re.S | re.I)


def main_for_compare(html_text):
    """<main> の中から、メール保護のリンクと @ を含む語を外したもの。<main> が無ければ None。"""
    m = MAIN_RE.search(html_text or "")
    if not m:
        return None
    body = CF_SPAN_RE.sub("", CF_LINK_RE.sub("", m.group(1)))
    return EMAIL_WORD_RE.sub("", body)


def first_diff(a, b):
    """違いの最初の場所（前後の文字）を短く出す。"""
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    cut = lambda s: s[max(0, i - 15): i + 25].replace("\n", " ")
    return f"最初の違いは {i + 1}字目のあたり: 本番「{cut(b)}」／手元「{cut(a)}」"


def local_file(dist, path):
    """ページのパス → 手元の出力のファイル（無ければ None）。"""
    p = path.split("?")[0].split("#")[0]
    rel = p.strip("/")
    cands = [dist / rel / "index.html"] if p.endswith("/") or not rel else []
    if rel:
        cands += [dist / rel] if rel.endswith((".html", ".htm")) else [dist / rel / "index.html", dist / (rel + ".html")]
    return next((c for c in cands if c.is_file()), None)


def kb(n):
    """バイト → KB の表示（10KB 未満は小数1桁）。"""
    return f"{n / 1024:.1f}KB" if n < 10 * 1024 else f"{n / 1024:.0f}KB"


def check_open(site, path, dist):
    """a: 戻り値 (○/未, 説明, 本番の HTML)。"""
    want, note_local = None, ""
    if dist is not None:
        lf = local_file(dist, path)
        if lf is None:
            note_local = "手元の出力に無いページ（200 だけ見た）"
        else:
            want = main_for_compare(lf.read_text(encoding="utf-8", errors="replace"))
            if want is None:
                note_local = "手元のページに <main> が無い（200 だけ見た）"
    waited = 0
    while True:
        st, raw = fetch(urljoin(site, path))
        text = text_of(raw)
        got = main_for_compare(text) if want is not None else None
        if st == 200 and (want is None or got == want):
            how = "本文が手元の出力と同じ" if want is not None else (note_local or "200")
            return "○", f"200・{how}" + (f"・{waited}秒待った" if waited else ""), text
        if waited >= WAIT_MAX:
            if st != 200:
                why = f"応答 {st or 'なし'}"
            elif got is None:
                why = "200 だが本番のページに <main> が無い"
            else:
                why = "200 だが <main> が手元の出力と違う。" + first_diff(want, got)
            return "未", f"{WAIT_MAX // 60}分待ってもそろわない。{why}", text
        time.sleep(WAIT_STEP)
        waited += WAIT_STEP


# --- b: OG ----------------------------------------------------------------------------------------
META_RE = re.compile(r"<meta\b([^>]*)>", re.I)
ATTR_RE = re.compile(r"([a-zA-Z:-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+)")


def og_values(text):
    got = {}
    for m in META_RE.finditer(text or ""):
        attrs = {k.lower(): v.strip("\"'") for k, v in ATTR_RE.findall(m.group(1))}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in ("og:title", "og:description", "og:image") and key not in got:
            got[key] = attrs.get("content", "").strip()
    return got


def check_og(site, path, text):
    got = og_values(text)
    missing = [k for k in ("og:title", "og:description", "og:image") if not got.get(k)]
    if missing:
        return "×", "無い: " + "・".join(missing)
    img = urljoin(urljoin(site, path), got["og:image"])
    st, _ = fetch(img, bust=False)
    return ("○", f"3つあり・og:image {st}") if st == 200 else ("×", f"og:image が {st or '応答なし'}（{img}）")


# --- c と e: ブラウザで（390px） ---------------------------------------------------------------------
def load_js():
    """check_390.js を読む（先頭の // の説明の行は外す）。"""
    lines = CHECK_JS.read_text(encoding="utf-8").splitlines()
    while lines and (lines[0].startswith("//") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines)


def browser_checks(site, paths, img_limit_kb, header):
    """{path: ((c, c の説明), (e, e の説明), 6項目の数)}"""
    from playwright.sync_api import sync_playwright
    js = load_js()
    out, version = {}, ""
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            raise CannotCheck("Chromium を起動できない（playwright install chromium を実行する）: " + str(e).splitlines()[0][:120])
        version = b.version
        pg = b.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        for path in paths:
            try:
                pg.goto(urljoin(site, path), wait_until="load", timeout=60000)
            except Exception as e:
                why = ("×", "ブラウザで開けない: " + str(e).splitlines()[0][:120])
                out[path] = (why, why, {k: 0 for k in ITEMS})
                continue
            pg.evaluate("async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); } scrollTo(0, 0); }")
            try:
                pg.wait_for_function("[...document.images].every(i => i.complete)", timeout=5000)
            except Exception:
                pass
            imgs = pg.evaluate("""() => performance.getEntriesByType('resource')
                .filter(e => e.initiatorType === 'img')
                .map(e => [e.name, e.encodedBodySize || 0])""")
            sized = []
            for name, size in imgs:
                if not size:   # ほかのドメインの画像などで大きさが取れないときは、取り直して測る
                    st, raw = fetch(name, bust=False)
                    size = len(raw) if st == 200 and raw else 0
                sized.append((name, size))
            if not sized:
                c = ("○", "img の画像なし")
            else:
                total = sum(s for _n, s in sized)
                big = max(sized, key=lambda x: x[1])
                short = urlsplit(big[0]).path.rsplit("/", 1)[-1] or big[0]
                if big[1] / 1024 <= img_limit_kb:
                    c = ("○", f"{len(sized)}枚・合計 {kb(total)}・最大 {kb(big[1])}（{short}）")
                else:
                    c = ("×", f"最大 {kb(big[1])} が上限 {img_limit_kb}KB を超える（{big[0]}）・{len(sized)}枚・合計 {kb(total)}")
            found = pg.evaluate(js, {"width": WIDTH, "header": header})
            counts = {k: (found.get(k) or {}).get("n", 0) for k in ITEMS}
            bad = {k: n for k, n in counts.items() if n}
            notes = []
            if found.get("header_missing"):
                notes.append(f"ヘッダー（{header}）がページに無い")
            if not bad:
                e = ("○", "6項目 0" if header else "5項目 0（ヘッダーの重なりは見ていない）")
            else:
                e = ("×", "・".join(f"{k} {n}（例: {'／'.join(found[k]['ex'])}）" for k, n in bad.items()))
            if notes:
                e = (e[0], e[1] + "・" + "・".join(notes))
            out[path] = (c, e, counts)
        b.close()
    return out, version


# --- 見るページ ------------------------------------------------------------------------------------
def norm_site(site):
    s = urlsplit(site)
    if s.scheme not in ("http", "https") or not s.netloc:
        raise CannotCheck(f"--site は https://example.com の形で渡す（受けた値: {site}）")
    return f"{s.scheme}://{s.netloc}{s.path.rstrip('/')}/"


def paths_from_urls(site, given):
    host = urlsplit(site).netloc
    out = []
    for u in given:
        u = u.strip()
        if re.match(r"https?://", u):
            if urlsplit(u).netloc != host:
                raise CannotCheck(f"--urls に --site と違うドメインの URL（{u}）。--site と同じドメインのページだけを渡す")
            s = urlsplit(u)
            u = s.path + (f"?{s.query}" if s.query else "")
        u = u.split("#")[0]
        if not u.startswith("/"):
            u = urlsplit(site).path + u
        if u not in out:
            out.append(u)
    return out


def paths_from_sitemap(site):
    sm = urljoin(site, "sitemap.xml")
    st, raw = fetch(sm)
    if st != 200 or raw is None:
        raise CannotCheck(f"sitemap.xml を読めない（{sm}・応答 {st or 'なし'}）。--urls でページを渡す")
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text_of(raw))
    pages = []
    for loc in locs:
        if loc.endswith(".xml"):   # sitemap の索引: 1段だけたどる
            st2, raw2 = fetch(loc)
            if st2 == 200 and raw2:
                pages += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text_of(raw2))
        else:
            pages.append(loc)
    host, other, out = urlsplit(site).netloc, 0, []
    for loc in pages:
        s = urlsplit(loc)
        if s.netloc and s.netloc != host:
            other += 1
        path = (s.path or "/") + (f"?{s.query}" if s.query else "")
        if path not in out:
            out.append(path)
    if not out:
        raise CannotCheck(f"sitemap.xml にページが無い（{sm}）。--urls でページを渡す")
    note = f"・sitemap の {other}件は --site と違うドメインだった（パスだけを --site で開いた）" if other else ""
    return out, f"sitemap.xml の {len(out)}ページ{note}"


def run(a):
    try:
        import playwright.sync_api  # noqa: F401  c と e に要る。無ければ何も見ずに止める
    except ImportError:
        raise CannotCheck("Playwright が入っていない（pip install playwright のあと playwright install chromium）")
    site = norm_site(a.site)
    dist = None
    if a.dist:
        dist = Path(a.dist).expanduser().resolve()
        if not dist.is_dir():
            raise CannotCheck(f"--dist のフォルダが無い（{a.dist}）")
    if a.urls:
        paths = paths_from_urls(site, a.urls)
        how = f"渡した {len(paths)}ページ"
    else:
        paths, how = paths_from_sitemap(site)
    print(f"[prod_check] {site} の {how}・手元の出力 {'あり（' + str(a.dist) + '）' if dist else 'なし（200 だけ見る）'}"
          f"・画像の上限 {a.img_limit_kb}KB・ヘッダー {a.header or '指定なし（重なりは見ない）'}")

    rows, details, opened = [], [], []
    for path in paths:
        a_, a_note, text = check_open(site, path, dist)
        if a_ != "○":
            rows.append([path, a_, "未", "未", "未"])
            details.append(f"{path} a: {a_note}")
            continue
        b_, b_note = check_og(site, path, text)
        rows.append([path, a_, b_, None, None])
        opened.append(path)
        if b_ != "○":
            details.append(f"{path} b: {b_note}")
        if "待った" in a_note:
            details.append(f"{path} a: {a_note}")
    br, version = browser_checks(site, opened, a.img_limit_kb, a.header) if opened else ({}, "")
    counts_by_page = {}
    for r in rows:
        if r[0] in br:
            (c_, c_note), (e_, e_note), counts = br[r[0]]
            r[3], r[4] = c_, e_
            counts_by_page[r[0]] = counts
            details.append(f"{r[0]} c: {c_note}")
            if e_ != "○" or "無い" in e_note:
                details.append(f"{r[0]} e: {e_note}")

    print("\n| ページ | a 開けるか | b OG | c 画像 | e 390px |\n|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(str(x) for x in r) + " |")
    if counts_by_page:
        cols = [k if (k != ITEMS[3] or a.header) else k + "（見ない）" for k in ITEMS]
        print("\n390px の6項目（数）\n\n| ページ | " + " | ".join(cols) + " |\n|---|" + "---|" * len(ITEMS))
        for pth, counts in counts_by_page.items():
            print(f"| {pth} | " + " | ".join("—" if (k == ITEMS[3] and not a.header) else str(counts[k]) for k in ITEMS) + " |")
    print("\n詳細:\n" + ("\n".join(f"- {d}" for d in details) or "- なし"))
    n_bad = sum(1 for r in rows if any(x != "○" for x in r[1:]))
    n_wait = sum(1 for r in rows if r[1] == "未")
    ok = n_bad == 0
    stamp = datetime.now().astimezone()
    summary = (f"{len(rows)}ページ 全部 ○" if ok else f"{len(rows)}ページのうち {n_bad}ページで止まった（未 {n_wait}・× {n_bad - n_wait}）")
    print(f"\n[prod_check] {summary}（{stamp:%Y-%m-%d %H:%M}・Chromium {version or '起動せず'}）")
    if a.log:
        entry = {"ts": stamp.isoformat(timespec="seconds"), "site": site, "ok": ok, "summary": summary,
                 "pages": how, "dist": bool(dist), "rows": rows, "details": details}
        with Path(a.log).expanduser().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[prod_check] {a.log} に1行追記した")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="push のあとに、公開中のページを1ページずつ確かめる（本番確認）")
    ap.add_argument("--site", required=True, help="サイトの URL（例: https://example.com）")
    ap.add_argument("--urls", nargs="+", help="確かめるページ（パスか、--site と同じドメインの完全な URL）。渡さないときは sitemap.xml の全ページ")
    ap.add_argument("--dist", help="手元の出力（build したフォルダ）。渡すと <main> の中が同じかも見る")
    ap.add_argument("--img-limit-kb", type=int, default=300, help="画像1枚の上限（KB・既定 300）")
    ap.add_argument("--header", help="上に固定したヘッダーのセレクタ（渡したときだけ、見出しへの重なりを見る）")
    ap.add_argument("--log", help="結果を1行（JSON）追記するファイル（任意）")
    a = ap.parse_args()
    try:
        return run(a)
    except CannotCheck as e:
        print(f"[prod_check] 確かめられなかった: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
