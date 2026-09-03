#!/usr/bin/env python3
"""ネタ帳ボード ── ネタ帳（Markdown 1ファイル）を読んで、候補カードを1枚のHTMLに並べる。

これだけで動きます（Python 3 標準ライブラリのみ・追加インストール不要・ネット接続不要）。

    python3 neta_board.py                       # ./neta.md → ./candidates.html
    python3 neta_board.py 自分のネタ帳.md -o 出力.html
    python3 neta_board.py neta_example.md --today 2026-09-07   # 記入例を固定日で描く
    python3 neta_board.py neta_example.md --today 2026-09-07 --example   # 上部に「記入例」の帯を出す

決めごと（このボードが守っていること）:
  - 正本はネタ帳の .md だけ。ボードは読んで表示する側で、何も書き戻さない（データの二重保存をしない）
  - 「出所」（自分の実務のつまずき）が空のカードは赤枠で警告する。一覧や思いつきからの候補を棚に入れないため
  - 「説明」（誰の何をどうするものか）が空のカードは黄枠で警告する
  - ○×（棚の移動・段階の変更）は人が決める。ボードは判定しない
  - 書式が読めないカードは消さずに「書式エラー」欄に出す（静かに消えるのが一番怖い）
"""

import argparse
import html
import re
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# ネタ帳の書式（README参照）
# ---------------------------------------------------------------------------
SHELVES = ["提案", "在庫", "済み", "没ネタ"]
MARK = "【プロダクト候補】"
# カード内で読む項目（未知のキーも「キー: 値」なら落とさず保持する）
FIELD_KEYS = ["説明", "段階", "出所", "形", "層", "評価", "枠該当", "備考", "記帳", "素材",
              "履歴", "使用", "一言", "解放予定", "一体記事", "記事状況", "理由"]
STAGES = ["提案中", "議論中", "承認済み", "着手", "公開済み", "見送り"]
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{1,2})/(\d{1,2})")

# 表示ラベル（評価行の3項目）
EVAL_LABELS = {"1問題1商品": "解く問題は1つか",
               "記入例・実測の同梱": "実例を付けて配れるか",
               "サポート負荷": "配った後の手間"}
FRAME_LABEL = "狙う枠に当たるか"
FRAME_TIP = "自分で決めた「出す商品の条件」（例: 自分が使っている実物・低価格・サポート不要）に当てはまるか"

STAGE_STYLE = {
    "提案中":  "background:#efece3;color:var(--sub)",
    "議論中":  "background:#fdf3d0;color:var(--warn)",
    "承認済み": "background:#e3ede7;color:var(--ok)",
    "着手":    "background:#e3ede7;color:var(--ok)",
    "公開済み": "background:#2f5d46;color:#fff",
    "見送り":  "background:#eee;color:var(--sub);text-decoration:line-through",
}


def extract_date(text, default_year=None):
    """文字列から最初の日付をISOで返す（YYYY-MM-DD / M/D 両対応。無ければ空）。"""
    m = DATE_RE.search(text or "")
    if not m:
        return ""
    if m.group(1):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    y = default_year or date.today().year
    return f"{y}-{int(m.group(4)):02d}-{int(m.group(5)):02d}"


def parse(path):
    """ネタ帳を読んで (候補カードのリスト, 書式エラーのリスト) を返す。

    カード: {"title", "shelf", "fields": {キー: 値}, "history": [行], "unknown": [行], "line": 行番号}
    """
    text = Path(path).read_text(encoding="utf-8")
    shelf = None
    cards, errors = [], []
    cur = None

    def close():
        nonlocal cur
        if cur is not None:
            cards.append(cur)
            cur = None

    for n, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"## 【(提案|在庫|済み|没ネタ)】", line)
        if m:
            close()
            shelf = m.group(1)
            continue
        if shelf is None:
            continue
        m = re.match(r"- 仮タイトル:\s*(.*)$", line)
        if m:
            close()
            title = m.group(1).strip()
            if MARK in title:
                cur = {"title": title.replace(MARK, "").strip(), "shelf": shelf,
                       "fields": {}, "history": [], "unknown": [], "line": n}
            continue
        if line.startswith("- ") and MARK in line:
            # 仮タイトル行の書式に沿っていないプロダクト候補（例: 1行直書き）
            errors.append({"shelf": shelf, "line": n,
                           "reason": "仮タイトル行の書式外", "raw": line.strip()})
            continue
        if cur is not None:
            body = line.strip()
            if not body:
                close()
                continue
            m = re.match(r"([^:：]{1,12})[:：]\s*(.*)$", body)
            if m and m.group(1).strip() == "履歴":
                cur["history"].append(m.group(2).strip())   # 追記式・複数行
            elif m and m.group(1).strip() in FIELD_KEYS:
                cur["fields"][m.group(1).strip()] = m.group(2).strip()
            elif m and re.match(r"^[\w一-龠ぁ-んァ-ヶ・]+$", m.group(1).strip()):
                cur["fields"][m.group(1).strip()] = m.group(2).strip()   # 未知のキーも保持
            else:
                cur["unknown"].append(body)
    close()

    for c in cards:
        if c["unknown"]:
            errors.append({"shelf": c["shelf"], "line": c["line"],
                           "reason": "キー:値 形式で読めない行あり",
                           "raw": c["title"] + " ── " + " / ".join(c["unknown"][:2])})
    return cards, errors


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------
CSS = """
  :root { --yellow:#f5c94f; --ink:#1f1f1f; --sub:#5f5f59; --line:#e5e2d9; --bg:#faf9f5;
           --warn:#8a6d1a; --red:#a32c12; --ok:#2f5d46; }
  * { box-sizing:border-box; }
  body { font-family:"Helvetica Neue","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
         background:var(--bg); color:var(--ink); margin:0; padding:20px 16px 64px;
         max-width:640px; margin-inline:auto; line-height:1.7; }
  @media (min-width:1000px){ body { max-width:1160px; } }
  .gen { font-size:26px; font-weight:800; margin:0 0 2px; }
  .gen-note { font-size:12px; color:var(--sub); margin:0 0 6px; }
  h2 { font-size:15px; font-weight:800; border-left:4px solid var(--yellow); padding-left:8px;
       margin:26px 0 10px; display:flex; align-items:center; gap:8px; }
  h2 .cnt { font-size:12px; background:#efece3; color:var(--sub); border-radius:10px; padding:1px 8px; }
  .grid { display:grid; gap:14px; grid-template-columns:1fr; margin-bottom:8px; }
  @media (min-width:1000px){ .grid { grid-template-columns:repeat(auto-fill, minmax(340px, 1fr)); } }
  .card { background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:0; }
  .card.violation { border:2px solid var(--red); }
  .card.no-desc { border:2px solid var(--yellow); }
  .waitlabel { font-size:10.5px; color:var(--sub); letter-spacing:0.06em; margin:0 0 2px; }
  .title { font-size:15px; font-weight:800; margin:0 0 2px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
  .title .no { color:var(--sub); font-weight:700; }
  .desc { font-size:13.5px; font-weight:500; margin:0 0 6px; }
  .field { font-size:13px; margin:2px 0; }
  .field b { font-weight:700; color:var(--sub); font-size:12px; margin-right:4px; }
  .hist { font-size:12.5px; margin:2px 0 2px 0.5em; color:var(--ink); }
  .hist::before { content:"・"; color:var(--sub); }
  .badge { font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; white-space:nowrap; }
  .badge.new { background:var(--yellow); }
  .badge.upd { background:#fdf3d0; color:var(--warn); }
  .ev { display:flex; gap:6px; flex-wrap:wrap; margin:6px 0 4px; }
  .ev span { font-size:11px; padding:2px 7px; border-radius:4px; background:#efece3; color:var(--sub); white-space:nowrap; }
  .ev .m-ok { background:#e3ede7; color:var(--ok); }
  .ev .m-mid { background:#fdf3d0; color:var(--warn); }
  .ev .m-low { background:#eee; color:var(--sub); }
  .qmark { cursor:help; border-bottom:1px dotted var(--sub); }
  details { margin-top:6px; }
  details summary { font-size:12px; color:var(--sub); cursor:pointer; user-select:none; }
  .tane { font-size:15px; font-weight:700; margin:0 0 14px; }
  .err { font-size:13px; color:var(--red); font-weight:700; }
  .warnline { font-size:13px; color:var(--warn); font-weight:700; }
  .empty { font-size:13px; color:var(--sub); }
  .example-band { font-size:12.5px; color:var(--warn); background:#fdf3d0; border:1px solid #f1e2a6;
                  border-radius:6px; padding:6px 10px; margin:0 0 12px; }
  .lane { display:grid; gap:10px; grid-template-columns:repeat(5, 1fr); margin-bottom:8px; }
  @media (max-width:999px){ .lane { grid-template-columns:repeat(2, 1fr); } }
  .lane-col { background:#fff; border:1px solid var(--line); border-radius:10px; padding:8px 10px; min-height:60px; }
  .lane-head { font-size:12px; font-weight:800; color:var(--sub); margin:0 0 6px; letter-spacing:0.04em; }
  .fuda { display:block; font-size:12.5px; font-weight:700; color:var(--ink); text-decoration:none;
          background:#faf9f5; border:1px solid var(--line); border-left:4px solid var(--yellow);
          border-radius:6px; padding:6px 8px; margin:0 0 6px; }
  .fuda .fno { color:var(--sub); font-weight:700; margin-right:2px; }
  .fuda .fst { display:block; font-size:11px; font-weight:500; color:var(--sub); margin-top:2px; }
  .fuda .fnote { display:block; font-size:10.5px; font-weight:400; color:var(--sub); }
  .fuda.done { border-left-color:var(--ok); }
  .fuda.done .fst { color:var(--ok); }
  .fuda.late { border:2px solid var(--red); border-left:4px solid var(--red); }
  .fuda.late .fst { color:var(--red); font-weight:700; }
"""


def esc(s):
    return html.escape(str(s), quote=False)


def parse_eval(value):
    """評価行「1問題1商品=○／…／サポート負荷=低」を [(ラベル, 記号, 理由全文)] に分解。"""
    out = []
    for piece in value.split("／"):
        piece = piece.strip()
        for key, label in EVAL_LABELS.items():
            if piece.startswith(key):
                val = piece[len(key):].lstrip("=＝").strip()
                if key == "サポート負荷":
                    mark = "○" if val.startswith("低") and "中" not in val[:3] else \
                           ("×" if val.startswith("高") else "△")
                else:
                    mark = next((ch for ch in val if ch in "○△×"), "—")
                out.append((label, mark, piece))
                break
    return out


def card_dates(c, default_year):
    """(記帳日, 履歴の最新日付) をISOで返す（無ければ空文字）。"""
    reg = extract_date(c["fields"].get("記帳", ""), default_year)
    hist = max((extract_date(h, default_year) for h in c["history"]), default="")
    return reg, hist


def release_status(card):
    """一体記事の準備状況。ネタ帳の「記事状況」欄（手入力）を読む → (表示文, 公開済みか)。
    ※このボードは自分のサイトの構造を知らないので、自動判定はしない。"""
    article = card["fields"].get("一体記事", "").strip()
    status = card["fields"].get("記事状況", "").strip()
    stage = card["fields"].get("段階", "").strip()
    if not article:
        return "一体記事なし", stage == "公開済み"
    done = status.startswith("公開済み") or stage == "公開済み"
    return (status or "記事状況 未記入"), done


def release_lane_html(cards, today):
    """解放計画レーン: 当月から3ヶ月＋未定の列に、順番・道具名・一体記事の準備状況の札を並べる。"""
    months = []
    y, mth = today.year, today.month
    for _ in range(4):
        months.append(f"{y:04d}-{mth:02d}")
        mth += 1
        if mth == 13:
            y, mth = y + 1, 1
    cur = months[0]
    cols = {m: [] for m in months}
    cols["未定"] = []
    for c in sorted(cards, key=lambda x: x.get("_no", 999)):
        if c["shelf"] == "没ネタ":
            continue
        plan = c["fields"].get("解放予定", "").strip()
        m = re.match(r"(\d{4}-\d{2})", plan)
        month = m.group(1) if m else "未定"
        status, done = release_status(c)
        late = month != "未定" and month < cur and not done
        note = plan[len(month):].strip() if m else plan
        cls = "fuda" + (" late" if late else "") + (" done" if done else "")
        fuda = (f'<a class="{cls}" href="#{c["_anchor"]}"><span class="fno">#{c.get("_no", "?")}</span> '
                f'{esc(c["title"])}<span class="fst">{esc(status)}</span>'
                + (f'<span class="fnote">{esc(note)}</span>' if note else "") + "</a>")
        (cols[month] if month in cols else cols["未定"]).append(fuda)
    col_html = ""
    for key in months + ["未定"]:
        items = "".join(cols[key]) or '<p class="empty">なし</p>'
        col_html += f'<div class="lane-col"><p class="lane-head">{esc(key)}</p>{items}</div>'
    return (f'<h2>解放計画 <span class="cnt">{sum(len(v) for v in cols.values())}</span></h2>'
            f'<p class="gen-note">列=解放予定（当月から3ヶ月＋未定）。札=順番・道具名・一体記事の準備状況'
            f'（ネタ帳の「記事状況」欄）。予定月を過ぎて未公開は赤。正本はネタ帳のカード。</p>'
            f'<div class="lane">{col_html}</div>')


def render(cards, errors, today, source_name, example=False):
    counts = {s: sum(1 for c in cards if c["shelf"] == s) for s in SHELVES}
    week_ago = date.fromordinal(today.toordinal() - 7).isoformat()

    # 今週の種: 新規=記帳日7日以内／変化=履歴の最新日付7日以内（新規は除く）
    for c in cards:
        reg, hist = card_dates(c, today.year)
        c["_is_new"] = bool(reg and reg >= week_ago)
        c["_is_upd"] = (not c["_is_new"]) and bool(hist and hist >= week_ago)
        c["_anchor"] = f"c{c['line']}"
    n_new = sum(1 for c in cards if c["_is_new"])
    n_upd = sum(1 for c in cards if c["_is_upd"])

    # 番号（#1〜）: 提案→在庫→済み→没ネタの順に通し。○×を口頭・チャットで指定するときの番号
    ordered = sorted(cards, key=lambda x: (SHELVES.index(x["shelf"]), x["line"]))
    for i, c in enumerate(ordered, start=1):
        c["_no"] = i

    sections = []
    for shelf in SHELVES:
        label = {"提案": "提案（判定待ち）", "在庫": "在庫（○済み）",
                 "済み": "済み", "没ネタ": "没ネタ"}[shelf]
        rows = []
        for c in (x for x in ordered if x["shelf"] == shelf):
            f = c["fields"]
            violation = not f.get("出所", "").strip()
            no_desc = not f.get("説明", "").strip()
            stage = f.get("段階", "")
            style = STAGE_STYLE.get(stage, "background:#efece3;color:var(--sub)")
            badges = f'<span class="badge" style="{style}">{esc(stage or "段階未記入")}</span>'
            if c["_is_new"]:
                badges += '<span class="badge new">NEW</span>'
            if c["_is_upd"]:
                badges += '<span class="badge upd">更新</span>'

            parts = []
            if shelf == "提案":
                parts.append('<p class="waitlabel">判定待ち ── ○×は人が決める（番号で指定）</p>')
            parts.append(f'<p class="title"><span class="no">#{c["_no"]}</span> {esc(c["title"])} {badges}</p>')
            if no_desc:
                parts.append('<p class="warnline">説明なし ── 「誰の何をどうするものか」を1行で書く</p>')
            else:
                parts.append(f'<p class="desc">{esc(f["説明"])}</p>')
            if violation:
                parts.append('<p class="err">入口条件違反（出所なし）── 出所を書くか棚から外す</p>')
            else:
                parts.append(f'<p class="field"><b>出所</b>{esc(f["出所"])}</p>')
            evals = parse_eval(f.get("評価", ""))
            ev_html = ""
            for lab, mark, _reason in evals:
                cls = {"○": "m-ok", "△": "m-mid", "×": "m-low"}.get(mark, "")
                ev_html += f'<span class="{cls}">{esc(lab)} {esc(mark)}</span>'
            frame = f.get("枠該当", "").strip()
            if frame:
                fcls = "m-ok" if frame.startswith("○") else ("m-low" if frame.startswith("×") else "")
                ev_html += (f'<span class="{fcls} qmark" title="{html.escape(FRAME_TIP, quote=True)}">'
                            f'{esc(FRAME_LABEL)}? {esc(frame[:1])}</span>')
            if ev_html:
                parts.append(f'<div class="ev">{ev_html}</div>')
            if f.get("形") or f.get("層"):
                layer = f.get("層", "").strip()
                layer_badge = (f' <span class="badge" style="background:#efece3;color:var(--sub)">'
                               f'{esc(layer)}</span>') if layer else ""
                parts.append(f'<p class="field"><b>形</b>{esc(f.get("形", "—"))}{layer_badge}</p>')

            # 下層（詳細・既定は閉）
            detail = []
            for _lab, _m, reason in evals:
                detail.append(f'<p class="field"><b>評価の理由</b>{esc(reason)}</p>')
            shown = ["説明", "段階", "出所", "形", "層", "評価", "枠該当"]
            for key in ["備考", "記帳", "素材", "使用", "理由"]:
                if f.get(key):
                    detail.append(f'<p class="field"><b>{esc(key)}</b>{esc(f[key])}</p>')
                    shown.append(key)
            for key, val in f.items():
                if key not in shown and val:
                    detail.append(f'<p class="field"><b>{esc(key)}</b>{esc(val)}</p>')
            if c["history"]:
                detail.append('<p class="field"><b>履歴</b></p>')
                detail += [f'<p class="hist">{esc(h)}</p>' for h in c["history"]]
            if detail:
                parts.append(f'<details><summary>詳細</summary>{"".join(detail)}</details>')

            cls = "card" + (" violation" if violation else "") + (" no-desc" if no_desc and not violation else "")
            rows.append(f'<div class="{cls}" id="{c["_anchor"]}">{"".join(parts)}</div>')
        body = f'<div class="grid">{"".join(rows)}</div>' if rows else '<p class="empty">なし</p>'
        sections.append(f'<h2>{esc(label)} <span class="cnt">{counts[shelf]}</span></h2>\n{body}')

    err_html = ""
    if errors:
        lines = "".join(f'<p class="err">L{e["line"]} [{esc(e["shelf"])}] {esc(e["reason"])}: '
                        f'{esc(e["raw"][:80])}</p>' for e in errors)
        err_html = f'<h2>書式エラー <span class="cnt">{len(errors)}</span></h2>\n{lines}'

    uchiwake = " / ".join(f"{s}{counts[s]}" for s in SHELVES)
    band = (f'<p class="example-band">これは記入例です。候補はすべて架空です（{esc(source_name)}）</p>\n'
            if example else "")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>ネタ帳ボード</title>
<!-- 生成: neta_board.py（閲覧専用・書き込みなし）。正本はネタ帳の .md。
     このページはパーサで読んで表示するだけ（候補データの二重保存はしない）。○×はネタ帳側で -->
<style>{CSS}</style>
</head>
<body>
{band}<p class="gen">候補 {len(cards)}件（生成: {today.isoformat()}）</p>
<p class="gen-note">棚別内訳: {esc(uchiwake)}。正本は {esc(source_name)}（このページは閲覧専用）。</p>
<p class="tane">今週の種: 新規{n_new}件・変化{n_upd}件</p>
{release_lane_html(cards, today)}
{err_html}
{chr(10).join(sections)}
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="ネタ帳（.md）からネタ帳ボード（.html）を生成")
    ap.add_argument("neta", nargs="?", default="neta.md", help="ネタ帳のMarkdown（既定: ./neta.md）")
    ap.add_argument("-o", "--out", default=None, help="出力HTML（既定: ネタ帳と同じ場所の candidates.html）")
    ap.add_argument("--today", default=None, help="基準日 YYYY-MM-DD（既定: 今日。記入例を固定日で描くとき用）")
    ap.add_argument("--check", action="store_true", help="HTMLを書かず、件数と書式エラーだけ表示")
    ap.add_argument("--example", action="store_true",
                    help="最上部に「これは記入例です」の帯を出す（見本HTMLを作るとき用）")
    a = ap.parse_args()

    src = Path(a.neta)
    if not src.exists():
        sys.exit(f"エラー: ネタ帳が見つかりません: {src}")
    today = datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else date.today()
    cards, errors = parse(src)

    counts = {s: sum(1 for c in cards if c["shelf"] == s) for s in SHELVES}
    print(f"候補 {len(cards)}件（" + " / ".join(f"{s}{n}" for s, n in counts.items()) + "）")
    for c in cards:
        flag = "" if c["fields"].get("出所", "").strip() else " ★出所なし（入口条件違反）"
        print(f"  [{c['shelf']}] {c['title']}{flag}")
    if errors:
        print(f"書式エラー {len(errors)}件:")
        for e in errors:
            print(f"  L{e['line']} [{e['shelf']}] {e['reason']}: {e['raw'][:60]}")
    if a.check:
        return 0

    out = Path(a.out) if a.out else src.with_name("candidates.html")
    out.write_text(render(cards, errors, today, src.name, example=a.example), encoding="utf-8")
    print(f"生成: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
