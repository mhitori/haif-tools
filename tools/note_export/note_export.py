#!/usr/bin/env python3
"""note転載キット（note_export）── 記事の md を1本入れると、note に貼る直前までの5つを出す。

出るもの（--out/<slug>/）:
  1. note_body.txt  note に貼る本文（表・図の位置に札「[画像N: …]」・引用とコードの枠は「実物:」＋中身の文字）
  2. table_NN.png   本文の表を画像にしたもの（幅1200・列幅と折り返しを調整）
  3. fig_NN.<ext>   本文の図・画面の写し（貼る順に番号）
  4. header.png     note の見出し画像（1280×670・題名＋URL のカード型。ロゴは任意）
  5. checklist.md   貼る手順書（札の位置と画像・リンクにする箇所・タグの候補・書く人が埋める欄）

止まるとき（何も出力しない）:
  - --words で渡した検査語が本文・見出し画像の文字にある
  - 本文に > や ``` で始まる行が残った（note に貼ると空の枠になる）
  - 図の元ファイルが見つからない

やらないこと: note への投稿・題名の生成・本文の言い換え（貼るのは手）。

使い方:
    python3 note_export.py 記事.md --font-dir ./fonts --site-url https://example.com --url https://example.com/posts/slug/
    python3 note_export.py 記事.md --font-dir ./fonts --note-only        # note だけに書く記事（転載の2行を付けない）
作: ひとりAIファクトリー hitori-ai-factory.com（MIT License）
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

# 実行時に main() で決まる値
FONT_BOLD = FONT_REG = None      # Noto Sans JP の Bold・Regular（--font-dir）
BASE_URL = ""                     # サイト内リンク（/…）を絶対URLにするときの頭（--site-url）
ASSETS_ROOT = Path(".")           # 「/」で始まる図のパスの基点（--assets-root）
SRC_BASE = Path(".")              # 相対パスの図の基点（記事の md のフォルダ）

TABLE_W = 1200
TABLE_BAND = "#F5C94F"     # 見出し行の上の太線
TABLE_HEAD_BG = "#FBF8EE"
TABLE_LINE = "#E3E3E0"
TABLE_INK = "#1F1F1F"
TABLE_FONT_SIZE = 32
TABLE_KINSOKU = "、。，．」』）】〕］〉》ーっゃゅょぁぃぅぇぉゎッャュョァィゥェォヮ々…‥？！?!─・"
TABLE_BREAK_BEFORE = "（＋"   # この文字の前で優先的に折り返す
TABLE_SEP_RE = re.compile(r"^\|[\s:|+-]+\|$")

HEADER_SIZE = (1280, 670)
HEADER_MARGIN_X = 96
OG_BG, OG_BAND, OG_INK, OG_SUB = "#F4F1EA", "#F5C94F", "#1F1F1F", "#5F5F59"

HASHTAG_RULES = [
    (r"Claude", "#ClaudeCode"),
    (r"非エンジニア", "#非エンジニア"),
    (r"個人開発|サイト|公開", "#個人開発"),
    (r"AI", "#AI"),
]


# ---------------------------------------------------------------------------
# 読み取り・点検
# ---------------------------------------------------------------------------

def parse_front_matter(text):
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip('"')
            body = text[end + 4:].lstrip("\n")
    return meta, body


def strip_md(cell):
    cell = re.sub(r"\*\*(.+?)\*\*", r"\1", cell)
    cell = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)
    return re.sub(r"`(.+?)`", r"\1", cell).strip()


def load_words(path):
    """検査語のファイル（1行1語。# で始まる行と空行は飛ばす。re: で始まる行は正規表現）。
    英字を含む語は語の境界で当てる（前後が英字なら当てない）。"""
    terms = []
    if not path:
        return terms
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        w = raw.strip()
        if not w or w.startswith("#"):
            continue
        if w.startswith("re:"):
            terms.append((w, re.compile(w[3:])))
        else:
            pat = re.escape(w)
            if re.search(r"[A-Za-z]", w):
                pat = r"(?<![A-Za-z])" + pat + r"(?![A-Za-z])"
            terms.append((w, re.compile(pat, re.I)))
    return terms


def word_hits(text, terms):
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx in terms:
            if rx.search(line):
                hits.append((i, name, line.strip()[:60]))
    return hits


# ---------------------------------------------------------------------------
# 見出し画像（題名の折り返しは語の切れ目優先・禁則つき）
# ---------------------------------------------------------------------------

OG_SAFE_X = 230

# 行頭禁則: この文字で行を始めない（句読点・閉じ括弧・長音・小書き文字・罫線ダッシュ等）
OG_KINSOKU_HEAD = ("、。，．・」』）】〕］〉》ーっゃゅょぁぃぅぇぉゎッャュョァィゥェォヮ々…‥？！?!─")   # 】〕］ は 2026-09-22 に追加
OG_SIZES = (72, 64, 56, 48, 44)
OG_SIZES_3PLUS = tuple(s for s in OG_SIZES if s <= 56)   # 3行以上になる題名の最大は56px（2026-09-20）


def _og_break_candidates(title):
    """優先折返し位置のリスト（このインデックスの直前で折る）。
    「──」「、」半角/全角スペースの直後を候補にする（「──」の間では折らない）。"""
    idxs = []
    for i in range(1, len(title)):
        if title[i - 2:i] == "──" or title[i - 1] in "、 　":
            if title[i] != "─":   # 「──」の1文字目直後（間）は除外
                idxs.append(i)
    return idxs


OG_OPEN = "「『（(〈《【"
OG_CLOSE = "」』）)〉》】"


def _og_is_hira(ch):
    return "\u3041" <= ch <= "\u309f"


def _og_break_sets(title):
    """折ってよい位置（このインデックスの直前で折る）を2段で返す（2026-09-20 禁則）。
    loose: 文字単位で折るときの許可位置。次の位置では折らない──
      (a) 数字・英字の並びの途中 (b)「」（）等の括弧の内側と、開き括弧の直後
      (d) 句読点・閉じ括弧・長音・小書き文字など（OG_KINSOKU_HEAD）の直前 ／「──」の間
    phrase: loose のうち語の切れ目（「、」「──」空白・閉じ括弧の後／開き括弧の前／ひらがな→ひらがな以外の変わり目）。"""
    loose, phrase, depth = set(), set(), 0
    for i in range(1, len(title)):
        prev, cur = title[i - 1], title[i]
        depth += (prev in OG_OPEN) - (prev in OG_CLOSE)
        if (depth > 0 or cur in OG_KINSOKU_HEAD or prev in OG_OPEN
                or (prev.isascii() and prev.isalnum() and cur.isascii() and cur.isalnum())):
            continue
        loose.add(i)
        if (prev in "、。 　" or prev in OG_CLOSE or title[i - 2:i] == "──" or cur in OG_OPEN
                or (_og_is_hira(prev) and not _og_is_hira(cur))):
            phrase.add(i)
    return loose, phrase


def _og_wrap(title, font, max_width, draw, max_lines, allowed, prio=()):
    """許可位置 allowed だけで貪欲に折る。max_lines 行に収まらなければ None。
    (c) 1文字だけの行を作る折り方は避ける（候補から外す。他に候補が無いときだけ使う）。
    「、」「──」等の優先位置は、その行が幅の6割以上になるなら最長の候補より先に使う。"""
    def width(t):
        return draw.textlength(t.strip(" 　"), font=font)
    n, lines, start = len(title), [], 0
    while start < n:
        if width(title[start:]) <= max_width:
            lines.append(title[start:].strip(" 　"))
            break
        if len(lines) == max_lines - 1:
            return None
        cands = [j for j in allowed if start < j < n and width(title[start:j]) <= max_width]
        good = [j for j in cands if len(title[start:j].strip(" 　")) > 1 and len(title[j:].strip(" 　")) > 1]
        cands = good or cands
        if not cands:
            return None
        pj = [j for j in cands if j in prio and width(title[start:j]) >= max_width * 0.6]
        j = max(pj) if pj else max(cands)
        lines.append(title[start:j].strip(" 　"))
        start = j
        while start < n and title[start] in " 　":
            start += 1
    return lines


def _og_layout(title, draw, max_width, font_path):
    """(フォント, 行リスト) を返す。判定順（文字サイズは各段とも72pxから順に下げる）:
    ① 72/64pxで1行に収まればそのまま1行
    ② 優先位置（──・、・スペース直後）で2行
    ③「1行に収まる最大サイズ（56px以下）」と「語の切れ目で2行の最大サイズ」の大きい方
    ④ 3行（優先位置2か所 → 語の切れ目）→ 4行（語の切れ目）。3行以上は56pxから（OG_SIZES_3PLUS）
    ⑤ 語の切れ目で収まらなければ文字単位（禁則つき）で2→3→4行。題名は切り捨てない
    禁則（数字・英字の並び／括弧の内側／1文字の行／行頭の句読点・閉じ括弧）は _og_break_sets・_og_wrap（2026-09-20）
    """
    from PIL import ImageFont
    fonts = {size: ImageFont.truetype(str(font_path), size) for size in OG_SIZES}
    loose, phrase = _og_break_sets(title)
    prio = [i for i in _og_break_candidates(title) if i in loose]

    def fits(s, font):
        return draw.textlength(s, font=font) <= max_width

    def ok(parts):
        return all(len(x) > 1 for x in parts)

    for size in (72, 64):                      # ① 大サイズで1行に収まるならそのまま
        if fits(title, fonts[size]):
            return fonts[size], [title]
    for size in OG_SIZES:                      # ② 優先規則: 「──」「、」空白の直後（後ろの候補ほど1行目を長く）
        font = fonts[size]
        for i in reversed(prio):
            parts = [title[:i].rstrip(" 　"), title[i:].lstrip(" 　")]
            if ok(parts) and all(fits(x, font) for x in parts):
                return font, parts
    # ③ 1行（56px以下）と語の切れ目で2行のうちフォントが大きい方
    single = next((s for s in OG_SIZES if s <= 56 and fits(title, fonts[s])), None)
    two = next((s for s in OG_SIZES if _og_wrap(title, fonts[s], max_width, draw, 2, phrase, prio)), None)
    if single is not None and (two is None or single >= two):
        return fonts[single], [title]
    if two is not None:
        return fonts[two], _og_wrap(title, fonts[two], max_width, draw, 2, phrase, prio)
    for size in OG_SIZES_3PLUS:                # ④ 3行: 優先位置2か所（1・2行目を長く取る組から）
        font = fonts[size]
        for j in reversed(prio):
            for i in reversed([c for c in prio if c < j]):
                parts = [x.strip(" 　") for x in (title[:i], title[i:j], title[j:])]
                if ok(parts) and all(fits(x, font) for x in parts):
                    return font, parts
    for n in (3, 4):                           # ④ 語の切れ目で3行→4行
        for size in OG_SIZES_3PLUS:
            lines = _og_wrap(title, fonts[size], max_width, draw, n, phrase, prio)
            if lines:
                return fonts[size], lines
    all_pos = set(range(1, len(title)))
    for allowed in (loose, all_pos):           # ⑤ 文字単位（禁則つき → 最後の手段は禁則なし）
        for n in (2, 3, 4):
            for size in (OG_SIZES if n == 2 else OG_SIZES_3PLUS):
                lines = _og_wrap(title, fonts[size], max_width, draw, n, allowed, prio)
                if lines:
                    return fonts[size], lines
    font = fonts[OG_SIZES[-1]]                 # 4行・最小サイズでも溢れる題名は想定外（…で止める）
    lines = []
    for ch in title:
        if not lines or (len(lines) < 4 and not fits(lines[-1] + ch, font)):
            lines.append(ch)
        elif fits(lines[-1] + ch, font):
            lines[-1] += ch
    lines[-1] = lines[-1][:-1] + "…"
    return font, lines



def render_title_card(title, footer, out_path, logo_path=None, size=HEADER_SIZE, margin_x=HEADER_MARGIN_X):
    """（任意でロゴ）＋題名＋下の1行のカード画像を描く。Pillow・書体が無ければ False。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    if not FONT_BOLD or not Path(FONT_BOLD).exists():
        return False
    W, H = size
    img = Image.new("RGB", (W, H), OG_BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 20, H], fill=OG_BAND)
    top = 64
    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        logo_h = 60
        logo = logo.resize((round(logo.width * logo_h / logo.height), logo_h), Image.LANCZOS)
        img.paste(logo, (margin_x, top), logo)
        top += logo_h
    max_width = W - margin_x * 2
    font, lines = _og_layout(title, draw, max_width, FONT_BOLD)
    line_h = round(font.size * 1.5)
    y = top + (H - top - 110 - line_h * len(lines)) // 2
    for line in lines:
        bearing = min(0, font.getbbox(line)[0])
        draw.text((margin_x - bearing, y), line, font=font, fill=OG_INK)
        y += line_h
    footer_font = ImageFont.truetype(str(FONT_BOLD), 30)
    draw.text((margin_x, H - 84), footer, font=footer_font, fill=OG_SUB)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return True


# ---------------------------------------------------------------------------
# 表の画像
# ---------------------------------------------------------------------------

def _alnum(ch):
    return ch.isascii() and ch.isalnum()


def _cell_wrap(text, font, max_w, draw):
    """セル内の折返し で書き直し）。
    - 「（」「＋」の前を優先し、無理なら文字単位で入るだけ入れる
    - 行頭の禁則: 次の行の頭に閉じ記号など（TABLE_KINSOKU）が来るあいだは、2つ以上続いても全部を前の行に残す
      （切る位置を前へ戻して、閉じ記号の直前の1文字ごと次の行へ送る）
    - 数字・英字の並びの途中では折らない
    - 末尾の行が1文字だけなら、前の行から1〜2文字を送る（行頭の禁則を破る送り方はしない）
    - 行端の空白は残さない"""
    def fits(s):
        return draw.textlength(s, font=font) <= max_w

    def ok_cut(rest, cut):
        return not (rest[cut] in TABLE_KINSOKU or (_alnum(rest[cut - 1]) and _alnum(rest[cut])))

    lines, rest = [], text
    while rest and not fits(rest):
        cut = None
        for i in range(1, len(rest)):
            if rest[i] in TABLE_BREAK_BEFORE and fits(rest[:i]) and ok_cut(rest, i):
                cut = i
        if cut is None:
            cut = 1
            while cut < len(rest) and fits(rest[:cut + 1]):
                cut += 1                      # 入るだけ入れる
            while cut > 1 and not ok_cut(rest, cut):
                cut -= 1                      # 禁則に当たる間は、切る位置を前へ戻す（閉じ記号が続いても全部）
        lines.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        lines.append(rest)
    lines = [l.strip() for l in lines] or [""]
    # 末尾の行が1文字だけなら、前の行から1〜2文字を送る
    if len(lines) >= 2 and len(lines[-1]) == 1:
        for k in (1, 2):
            prev, last = lines[-2], lines[-1]
            if len(prev) <= k:
                break
            new_prev, new_last = prev[:-k], prev[-k:] + last
            if (new_last[0] not in TABLE_KINSOKU and not (_alnum(new_prev[-1]) and _alnum(new_last[0]))
                    and fits(new_last)):
                lines[-2:] = [new_prev, new_last]
                break
    return lines


LAST_CELLS = []   # 直前に描いた表の全セルの行（行頭の禁則の数え上げに使う）
LAST_WIDTH_MODE = ["既定"]   # 直前に描いた表の列幅の決め方（手指定／既定／比例）


def parse_table_widths(value):
    """front matter の table_widths（例: "2=22/36/42; 3=20/30/50"）を {表の番号: [%,...]} にする。
    表ごとの列幅の指定追記）。指定の無い表は従来の決め方のまま。"""
    out = {}
    for part in filter(None, (x.strip() for x in (value or "").split(";"))):
        no, _, pcts = part.partition("=")
        out[int(no)] = [float(x) for x in pcts.split("/")]
    return out


COL_MIN_PCT, COL_MAX_PCT = 8, 50   # 比例の規則の下限・上限（%）


# 途中で折らないかたまり（日付・数字や英字の並び）。列の下限の幅を決めるのに使う
UNBREAKABLE_RE = re.compile(r"\d+年\d+月\d+日|\d+月\d+日|[A-Za-z0-9][A-Za-z0-9._\-/:%]*")


def proportional_widths(rows, pad_x=24):
    """列幅を各列の最長の文字数に比例させる（上限50%）。下限は列ごとに「その列でいちばん長い、途中で折らない
    かたまり（日付・数字や英字の並び）の幅＋余白」。ただし8%を下回らない で下限を変更）。
    下限・上限に当たった列は固定し、残りを文字数の比で配り直す。"""
    from PIL import Image, ImageDraw, ImageFont
    fonts = [ImageFont.truetype(str(FONT_BOLD), TABLE_FONT_SIZE), ImageFont.truetype(str(FONT_REG), TABLE_FONT_SIZE)]
    draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    n = len(rows[0])
    longest = [max(len(r[ci]) for r in rows) or 1 for ci in range(n)]
    lo = []
    for ci in range(n):
        px = max((draw.textlength(chunk, font=fonts[0 if ri == 0 else 1])
                  for ri, r in enumerate(rows) for chunk in UNBREAKABLE_RE.findall(r[ci])), default=0)
        lo.append(max(COL_MIN_PCT / 100, (px + pad_x * 2) / TABLE_W))
    if sum(lo) > 1:
        lo = [x / sum(lo) for x in lo]
    hi = COL_MAX_PCT / 100
    share, fixed = [0.0] * n, [False] * n
    for _ in range(n + 1):
        free = [ci for ci in range(n) if not fixed[ci]]
        rest = 1 - sum(share[ci] for ci in range(n) if fixed[ci])
        total = sum(longest[ci] for ci in free) or 1
        for ci in free:
            share[ci] = rest * longest[ci] / total
        changed = False
        for ci in free:
            if share[ci] < lo[ci]:
                share[ci], fixed[ci], changed = lo[ci], True, True
            elif share[ci] > hi:
                share[ci], fixed[ci], changed = hi, True, True
        if not changed:
            break
    widths = [round(TABLE_W * x) for x in share]
    widths[-1] += TABLE_W - sum(widths)
    return widths


def default_widths(rows, measurer, cell_font, pad_x):
    """従来の列幅の決め方（自然幅の比・3列は1列目を16〜30%に）。"""
    n_cols = len(rows[0])
    nat = [max(measurer.textlength(rows[ri][ci], font=cell_font(ri)) for ri in range(len(rows))) + pad_x * 2
           for ci in range(n_cols)]
    if sum(nat) <= TABLE_W:
        scale = TABLE_W / sum(nat)
        widths = [round(w * scale) for w in nat]
    elif n_cols == 3:
        # 3列は「1列目＝見出し列」が多い。1列目は自然幅（幅の16〜30%）、残りを2・3列目の
        # 自然幅の比で分ける（どちらも幅の25%以上）。1文字だけの行が出にくい配分（2026-09-19 の調整）
        first = round(min(max(nat[0], TABLE_W * 0.16), TABLE_W * 0.30))
        rest = TABLE_W - first
        share = nat[1] / (nat[1] + nat[2])
        second = round(min(max(rest * share, TABLE_W * 0.25), rest - TABLE_W * 0.25))
        widths = [first, second, rest - second]
    else:
        widths = [round(w) for w in nat]
        floor = max(160, TABLE_W // (n_cols * 2))
        over = sum(widths) - TABLE_W
        while over > 0:
            i = widths.index(max(widths))
            cut = min(over, widths[i] - floor)
            if cut <= 0:
                scale = TABLE_W / sum(widths)
                widths = [max(floor, round(w * scale)) for w in widths]
                break
            widths[i] -= cut
            over -= cut
        widths[-1] += TABLE_W - sum(widths)

    return widths


def render_table_image(rows, out_path, pct=None):
    """Markdown表1つをPNGへ（幅1200・白背景・見出し上に太線・外枠なし）。"""
    from PIL import Image, ImageDraw, ImageFont
    font_head = ImageFont.truetype(str(FONT_BOLD), TABLE_FONT_SIZE)
    font_body = ImageFont.truetype(str(FONT_REG), TABLE_FONT_SIZE)
    measurer = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    pad_x, pad_y = 24, 16
    band_h, grid_w = 8, 2
    line_h = round(TABLE_FONT_SIZE * 1.45)

    def cell_font(ri):
        return font_head if ri == 0 else font_body

    def layout(widths):
        cells, heights = [], []
        for ri, row in enumerate(rows):
            wrapped = [_cell_wrap(row[ci], cell_font(ri), widths[ci] - pad_x * 2, measurer) for ci in range(n_cols)]
            cells.append(wrapped)
            heights.append(max(len(w) for w in wrapped) * line_h + pad_y * 2)
        return cells, heights

    if pct and len(pct) == n_cols:
        # 表ごとの指定（%）。合計が100でなくても比で配る
        widths = [round(TABLE_W * x / sum(pct)) for x in pct]
        widths[-1] += TABLE_W - sum(widths)
        mode = "手指定"
        cells, heights = layout(widths)
    else:
        # 指定が無い表は、既定と比例の両方で組み、低い方を使う（同じ高さなら既定
        widths = default_widths(rows, measurer, cell_font, pad_x)
        cells, heights = layout(widths)
        mode = "既定"
        p_widths = proportional_widths(rows, pad_x)
        p_cells, p_heights = layout(p_widths)
        if sum(p_heights) < sum(heights):
            widths, cells, heights, mode = p_widths, p_cells, p_heights, "比例"
    LAST_CELLS.clear()
    LAST_CELLS.extend(l for wrapped in cells for w in wrapped for l in w)
    LAST_WIDTH_MODE[0] = mode

    img = Image.new("RGB", (TABLE_W, band_h + sum(heights)), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, TABLE_W, band_h - 1], fill=TABLE_BAND)
    draw.rectangle([0, band_h, TABLE_W, band_h + heights[0] - 1], fill=TABLE_HEAD_BG)

    y = band_h
    for ri, row_cells in enumerate(cells):
        x = 0
        for ci, lines in enumerate(row_cells):
            ty = y + pad_y
            for line in lines:
                draw.text((x + pad_x, ty), line, font=cell_font(ri), fill=TABLE_INK)
                ty += line_h
            x += widths[ci]
        y += heights[ri]
        if ri < len(cells) - 1:
            draw.rectangle([0, y - grid_w // 2, TABLE_W, y + grid_w // 2 - 1], fill=TABLE_LINE)
    x = 0
    for ci in range(n_cols - 1):
        x += widths[ci]
        draw.rectangle([x - grid_w // 2, band_h, x + grid_w // 2 - 1, img.height], fill=TABLE_LINE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return img.size



# ---------------------------------------------------------------------------
# 変換
# ---------------------------------------------------------------------------

def convert(body, out_dir, slug):
    """本文を note 用に変換する。返り値: (本文, 札の一覧, 表の一覧, 図の一覧, 絶対URLの一覧)。"""
    lines = body.splitlines()
    out, marks, tables, figs, quotes = [], [], [], [], []
    heading = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        m_head = re.match(r"^(#{1,6})\s+(.*)$", line)
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line.strip())
        is_table = (line.lstrip().startswith("|") and i + 1 < len(lines)
                    and TABLE_SEP_RE.match(lines[i + 1].strip()))
        if line.startswith("```"):
            # コードの枠: 引用と同じく「実物:」＋中身をそのまま（``` の行は外す・前後に空行。
            j = i + 1
            inner = []
            while j < len(lines) and not lines[j].startswith("```"):
                inner.append(lines[j])
                j += 1
            quotes.append(len(inner))
            out += ([""] if out and out[-1].strip() else []) + ["実物:"] + inner + [""]
            i = j + 1
        elif line.startswith(">"):
            # 実物の枠（引用ブロック）: note では引用の中の見出し・箇条書きが崩れて空の灰色の枠になるため、
            # 1行目「実物:」＋中身をそのまま出す（前後に空行
            j = i
            inner = []
            while j < len(lines) and lines[j].startswith(">"):
                inner.append(re.sub(r"^> ?", "", lines[j]))
                j += 1
            quotes.append(len(inner))
            out += ([""] if out and out[-1].strip() else []) + ["実物:"] + inner + [""]
            i = j
        elif m_head:
            heading = strip_md(m_head.group(2))
            mark = "##" if len(m_head.group(1)) <= 2 else "###"   # noteの大見出し／小見出しの2段
            out += ([""] if out and out[-1].strip() else []) + [f"{mark} {heading}", ""]
            i += 1
        elif is_table:
            block = [lines[i]]
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                block.append(lines[j])
                j += 1
            rows = [[strip_md(c) for c in l.strip().strip("|").split("|")] for l in (block[:1] + block[2:])]
            name = f"table_{len(tables) + 1:02d}.png"
            title = f"{heading}の表" if heading else f"表{len(tables) + 1}"
            tables.append({"name": name, "rows": rows, "title": title, "no": len(marks) + 1})
            marks.append({"no": len(marks) + 1, "kind": "表", "title": title, "file": name})
            out.append(f"[画像{len(marks)}: {title}]")
            out.append("")
            i = j
        elif m_img:
            alt, src = strip_md(m_img.group(1)), m_img.group(2)
            title = (alt if len(alt) <= 40 else alt[:39] + "…") or f"図{len(figs) + 1}"
            src_path = (ASSETS_ROOT / src.lstrip("/")) if src.startswith("/") else (SRC_BASE / src)
            name = f"fig_{len(figs) + 1:02d}{src_path.suffix.lower() or '.png'}"
            figs.append({"name": name, "src": src_path, "title": title, "exists": src_path.exists()})
            marks.append({"no": len(marks) + 1, "kind": "図", "title": title, "file": name})
            out.append(f"[画像{len(marks)}: {title}]")
            out.append("")
            i += 1
        else:
            out.append(line)
            i += 1

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # サイト内リンクは本番の絶対URLに
    text = re.sub(r"\]\((/[^)]*)\)", lambda m: f"]({BASE_URL}{m.group(1)})" if BASE_URL else m.group(0), text)
    urls = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", text)
    return text, marks, tables, figs, urls, len(quotes)


def checklist_md(meta, url, marks, urls, tags, warn, n_quotes=0):
    lines = [f"# note に貼る手順（{meta.get('title', '')}）", "",
             "note版の題名（書く人が埋める）: ",
             "", (f"元記事: {url}" if url else "元記事: なし（note だけの記事）"), ""]
    if warn:
        lines += [f"注意: {warn}", ""]
    lines += ["## 画像の貼り位置", "",
              "| 札 | 種類 | 題 | ファイル | 列幅 |", "|---|---|---|---|---|"]
    for m in marks:
        lines.append(f"| [画像{m['no']}] | {m['kind']} | {m['title']} | {m['file']} | {m.get('width', '—')} |")
    lines += ["", "本文の札（[画像N: …]）の行を消して、その位置にファイルをドラッグする。", "",
              "## 貼ったあとの確認（5つ）", "",
              "- [ ] 本文: note_body.txt を貼った",
              f"- [ ] 表: 表の画像（{sum(1 for m in marks if m['kind'] == '表')} 枚）を札の位置に貼った",
              f"- [ ] 図: 図の画像（{sum(1 for m in marks if m['kind'] == '図')} 枚）を札の位置に貼った",
              "- [ ] 見出し画像: header.png を note の見出しに設定した",
              f"- [ ] 実物の枠（{n_quotes} か所）の中身: note には引用のボタンが無いため、実物は本文の灰色の枠（コード）に貼る。# や - はそのまま残す",
              "", "公開の前に、表・図・実物の3か所を上から順に画面で確かめる。", ""]
    lines += [
              "## 選択→リンクにする箇所", ""]
    if urls:
        lines += ["| 文字 | リンク先 |", "|---|---|"]
        lines += [f"| {t} | {u} |" for t, u in urls]
    else:
        lines.append("- なし")
    lines += ["", "## タグの候補（2〜3個）", "", "- " + " ".join(tags), "",
              "## やらないこと", "",
              "- note への投稿は手動（このツールは投稿しない）",
              "- 題名と本文の言い換えはこのツールでは行わない（書く人が埋める）"]
    return "\n".join(lines) + "\n"



def main():
    global FONT_BOLD, FONT_REG, BASE_URL, ASSETS_ROOT, SRC_BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="記事の md（front matter 付き・title は必須）")
    ap.add_argument("--font-dir", required=True, help="NotoSansJP-Regular.otf と NotoSansJP-Bold.otf を置いたフォルダ")
    ap.add_argument("--out", default="note_export_out", help="出力先の親フォルダ（既定 ./note_export_out）")
    ap.add_argument("--url", help="元記事の URL（転載の2行と見出し画像の下の行に使う）")
    ap.add_argument("--site-url", default="", help="サイトの頭（例 https://example.com）。本文の /… のリンクを絶対URLにする")
    ap.add_argument("--site-name", help="転載の1行目に出すサイトの名前（既定は --site-url のホスト名）")
    ap.add_argument("--assets-root", help="「/」で始まる図のパスの基点（既定は記事の md のフォルダ）")
    ap.add_argument("--words", help="検査語のファイル（1行1語。当たったら出力せずに止まる）")
    ap.add_argument("--logo", help="見出し画像の左上に置くロゴの画像（任意）")
    ap.add_argument("--voice", help="note版の前半に置く「語り」の md（任意）")
    ap.add_argument("--note-only", action="store_true", help="note だけの記事（転載の2行を付けない。front matter の kind: note_only でも同じ）")
    a = ap.parse_args()

    font_dir = Path(a.font_dir)
    FONT_BOLD, FONT_REG = font_dir / "NotoSansJP-Bold.otf", font_dir / "NotoSansJP-Regular.otf"
    for f in (FONT_BOLD, FONT_REG):
        if not f.exists():
            sys.exit(f"エラー: 書体 {f} がありません（README の「用意するもの」）")
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("エラー: Pillow が入っていません（pip install pillow）")

    path = Path(a.path)
    if not path.exists():
        sys.exit(f"エラー: {path} がありません")
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    if meta.get("draft") == "true":
        sys.exit(f"エラー: {path.name} は下書き（draft: true）です")
    note_only = a.note_only or meta.get("kind") == "note_only"
    BASE_URL = a.site_url.rstrip("/")
    SRC_BASE = path.resolve().parent
    ASSETS_ROOT = Path(a.assets_root) if a.assets_root else SRC_BASE
    slug = path.stem
    url = None if note_only else (a.url or "")
    site_name = a.site_name or re.sub(r"^https?://", "", BASE_URL) or "元のサイト"
    terms = load_words(a.words)

    voice = ""
    if a.voice:
        _vm, voice = parse_front_matter(Path(a.voice).read_text(encoding="utf-8"))
        voice = voice.strip()

    out_dir = Path(a.out) / slug
    head = [] if note_only else [f"この記事は {site_name} の転載です。", f"元記事 → {url or '（元記事の URL）'}", ""]
    converted, marks, tables, figs, urls, n_quotes = convert(body, out_dir, slug)
    note_body = "\n".join(head + ([voice, ""] if voice else []) + [converted.strip()]) + "\n"

    hits = word_hits(note_body, terms)
    if hits:
        print("止まりました: 検査語が本文にあります（出力しません）", file=sys.stderr)
        for ln, name, snip in hits[:10]:
            print(f"  {ln}行目 [{name}] {snip}", file=sys.stderr)
        return 1
    bad = [(k, l) for k, l in enumerate(note_body.splitlines(), 1) if l.startswith(">") or l.startswith("```")]
    if bad:
        print("止まりました: 本文に > や ``` で始まる行があります（note に貼ると空の枠になる・出力しません）", file=sys.stderr)
        for k, l in bad[:10]:
            print(f"  {k}行目: {l[:40]}", file=sys.stderr)
        return 1
    for t in tables:
        th = word_hits("\n".join(" ".join(r) for r in t["rows"]), terms)
        if th:
            print(f"止まりました: 表の文字に検査語があります（{t['name']}・出力しません）", file=sys.stderr)
            return 1
    header_title = meta.get("note_title") or meta.get("title", slug)
    header_url = url or (BASE_URL + "/" if BASE_URL else "")
    if word_hits(f"{header_title}\n{header_url}", terms):
        print("止まりました: 見出し画像の文字に検査語があります（出力しません）", file=sys.stderr)
        return 1
    missing = [f["src"] for f in figs if not f["exists"]]
    if missing:
        print("止まりました: 図の元ファイルがありません（--assets-root を確かめてください・出力しません）", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "note_body.txt").write_text(note_body, encoding="utf-8")
    widths_spec = parse_table_widths(meta.get("table_widths"))
    for no, t in enumerate(tables, 1):
        t["size"] = render_table_image(t["rows"], out_dir / t["name"], widths_spec.get(no))
        t["width_mode"] = LAST_WIDTH_MODE[0]
        for m in marks:
            if m["file"] == t["name"]:
                m["width"] = t["width_mode"]
    for f in figs:
        shutil.copy2(f["src"], out_dir / f["name"])
    if not render_title_card(header_title, header_url, out_dir / "header.png", a.logo):
        print("警告: 見出し画像を作れませんでした（Pillow または書体が無い）", file=sys.stderr)
    tags = [tag for pat, tag in HASHTAG_RULES if re.search(pat, note_body)][:3] or ["#AI", "#個人開発"]
    (out_dir / "checklist.md").write_text(checklist_md(meta, url, marks, urls, tags, "", n_quotes), encoding="utf-8")

    print(f"[note_export] {out_dir}/ へ出力: 本文 {len(note_body)}字／表 {len(tables)}枚／図 {len(figs)}枚／札 {len(marks)}個")
    for t in tables:
        print(f"  {t['name']}  {t['size'][0]}×{t['size'][1]}  {t['title']}（列幅: {t['width_mode']}）")
    for f in figs:
        print(f"  {f['name']}  ← {f['src']}")
    print(f"  header.png  {HEADER_SIZE[0]}×{HEADER_SIZE[1]}  {header_title}")
    print(f"  実物の枠（引用・コード）: {n_quotes} か所 → 本文に「実物:」＋中身で出力")
    return 0


if __name__ == "__main__":
    sys.exit(main())
