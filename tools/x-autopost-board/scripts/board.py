#!/usr/bin/env python3
"""board ── 棚と台帳から、表示専用のボード（board/index.html）を作る。HTML 1枚で完結し、JS はコピーのボタンだけ。

入力: 棚（data/shelf.json・状態の正）／投稿ログ／受領票／支出カウンタ／自分の投稿の台帳／（任意）記事フォルダ
区画: 今朝の実行・支出・印の説明・予定・投稿済み・見送り・記事（記事の設定があるときだけ）
ボードからは何も書き換えない。承認・見送りは shelf.py で棚に記帳し、ボードはその結果を映す。
赤は異常のときだけ（工程の失敗・未告知・支出80%超）。

使い方:
    python3 scripts/board.py
"""

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KIT_ROOT, now_jst, path, section   # noqa: E402

STATUS_JA = {"draft": "下書き（承認待ち）", "approved": "承認済み", "posted": "投稿済み",
             "skipped": "見送り", "expired": "失効（予定日超過）",
             "superseded": "差し替え済み", "held": "保留"}
STEP_JA = {"success": "成功", "failure": "失敗", "cancelled": "中止", "skipped": "飛ばし"}
STEP_NAME = {"own_posts": "取り込み", "post": "投稿", "board": "ボード更新", "receipt": "受領票"}
EVENT_JA = {"schedule": "定時", "workflow_dispatch": "手動起動", "local": "手元の試運転"}


def esc(s):
    return html.escape(str(s), quote=False)


def load_jsonl(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def receipt_line(today, rows, gen):
    """「今朝の実行」行。当日の受領票の最後の行があれば、日付・開始時刻と各工程の成否。無ければ「未実行」。
    どちらも末尾にボードの生成時刻を付ける（実行が動かなかった日はボードも作り直されず、前の日の行が残るため）。
    戻り値: (css class, 本文)。"""
    tail = f"｜このボードの生成 {gen}"
    todays = [r for r in rows if r.get("event") in EVENT_JA
              and str(r.get("started_at") or r.get("ts") or "")[:10] == today]
    if not todays:
        return "warn", f"{today} 未実行（当日の受領票が無い）{tail}"
    r = todays[-1]
    steps = r.get("steps") or {}
    started = str(r.get("started_at") or r.get("ts") or "")[11:16]
    parts = [f"{STEP_NAME.get(k, k)} {STEP_JA.get(v, v if v else '記録なし')}" for k, v in steps.items()]
    ok = bool(steps) and all(v == "success" for v in steps.values())
    return ("ok" if ok else "err"), (f"{today} {started} 開始（{EVENT_JA.get(r.get('event'), r.get('event'))}・受領票 #{r.get('run_number', '—')}）｜"
                                     + "・".join(parts) + tail)


def main():
    now = now_jst()
    today = now.date().isoformat()
    shelf = json.loads(path("shelf").read_text(encoding="utf-8")) if path("shelf").exists() else {"items": []}
    runs = load_jsonl(path("post_log"))
    today_runs = [r for r in runs if r.get("ts", "")[:10] == today and r.get("mode") in ("dryrun", "live")]
    last = today_runs[-1] if today_runs else None
    post_time = str(section("schedule").get("post_time") or "07:00")

    spend = json.loads(path("spend").read_text(encoding="utf-8")) if path("spend").exists() else {}
    month = now.strftime("%Y-%m")
    used = float(spend.get(month, 0))
    spend_limit = float(section("spend").get("monthly_limit_usd", 20) or 0)
    spend_red = spend_limit > 0 and used >= spend_limit * 0.8

    def _slug(i):
        if i.get("slug"):
            return i["slug"]
        p = re.sub(r"^https?://[^/]+", "", i.get("url") or "").strip("/")
        return p.split("/")[-1] if p else ""
    logged = {p.get("id") for r in runs for p in (r.get("posted") or [])}
    posted_slugs = {_slug(i) for i in shelf["items"]
                    if (i.get("status") == "posted" or i["id"] in logged) and _slug(i)}

    sched_count = {}
    for i in shelf["items"]:
        if (i.get("status", "draft") in ("approved", "draft") and i.get("channel", "auto") != "manual"
                and i.get("scheduled_date") not in (None, "", "未定")):
            k = (i["scheduled_date"], i.get("scheduled_time", ""))
            sched_count[k] = sched_count.get(k, 0) + 1

    led = json.loads(path("own_posts").read_text(encoding="utf-8")) if path("own_posts").exists() else {"posts": []}
    x_seen = {}
    try:
        import own_posts as _op
        for i in shelf["items"]:
            if i.get("status", "draft") in ("draft", "approved", "held"):
                hit = _op.matches(i, led.get("posts") or [])
                if hit:
                    x_seen[i["id"]] = hit[0][0]["created_at"][5:10].replace("-", "/")
    except Exception:
        _op = None

    def card_html(i):
        manual = i.get("channel", "auto") == "manual"
        dup = ""
        if i["id"] in x_seen and not manual:
            dup += f'<span class="tag dup">Xに同じ投稿あり（{esc(x_seen[i["id"]])}）</span>'
        if (not manual and i.get("status", "draft") in ("approved", "draft")
                and sched_count.get((i.get("scheduled_date"), i.get("scheduled_time", "")), 0) >= 2):
            dup = '<span class="tag dup">予定重複（1日1本なので後ろへずれる）</span>'
        if not manual and i.get("status", "draft") in ("draft", "approved", "held") and _slug(i) in posted_slugs:
            dup += '<span class="tag warn">同じURLを前に投稿済み（注意）</span>'
        over = f'<span class="tag dup">文字数超過（{esc(i.get("x_length"))}）</span>' if i.get("x_over") else ""
        posted = (f'<div class="note">投稿日時: {esc(i.get("posted_at", "—"))} ／ X: {esc(i.get("x_url", "—"))}</div>'
                  if i.get("status") == "posted" else "")
        url_note = f'<div class="note">URL: {esc(i["url"])}（コピーに含む）</div>' if i.get("url") else ""
        copy_payload = i["text"] + ("\n" + i["url"] if i.get("url") else "")
        return f"""<div class="card">
  <div class="meta"><span class="date">{esc(i.get('scheduled_date') or '未定')} {esc(i.get('scheduled_time', ''))} ｜ <span class="sid">{esc(i['id'][:4])}</span></span>
    <span class="tag">{esc(i['kind'])}</span><span class="tag ch-{'manual' if manual else 'auto'}">{'手動' if manual else '自動'}</span>
    <span class="tag st-{esc(i.get('status', 'draft'))}">{esc(STATUS_JA.get(i.get('status', 'draft'), i.get('status')))}</span>
    {over}{dup}</div>
  <pre class="body">{esc(i['text'])}</pre>
  {url_note}{posted}
  <button onclick="cp(this)" data-t="{html.escape(copy_payload, quote=True)}">コピー（本文＋URL）</button>
</div>"""

    def _date(i):
        return i.get("scheduled_date") if i.get("scheduled_date") not in (None, "", "未定") else "9999-99-99"
    by = lambda st: [i for i in shelf["items"] if i.get("status", "draft") == st]
    scheduled = sorted(by("approved"), key=lambda i: (_date(i), i.get("scheduled_time", "")))
    posted_items = sorted(by("posted"), key=lambda i: i.get("posted_at") or i.get("scheduled_date") or "", reverse=True)
    dismissed = sorted([i for i in shelf["items"] if i.get("status", "draft") not in ("approved", "posted")],
                       key=lambda i: i.get("posted_at") or i.get("created_at") or "", reverse=True)
    n_draft = sum(1 for i in dismissed if i.get("status") == "draft")

    def section_html(title, items, open_=True):
        body = "".join(card_html(i) for i in items) if items else '<p class="empty">0件</p>'
        if open_:
            return f'<h2>{title} <span class="cnt">{len(items)}件</span></h2>\n{body}'
        return (f'<details class="sec"><summary><h2>{title} <span class="cnt">{len(items)}件</span></h2></summary>'
                f'{body}</details>')

    # 記事区画（記事の設定があるときだけ）
    articles_html = ""
    n_un = n_wait = n_plan = 0
    if _op is not None:
        try:
            recs, _src = _op.article_status(led, shelf)
        except Exception as e:
            recs, _src = None, str(e)
        if recs:
            n_un = sum(1 for r in recs if r["status"] == "未告知")
            n_wait = sum(1 for r in recs if r["status"] == "承認待ち")
            n_plan = sum(1 for r in recs if r["status"] == "予定あり")
            cards_a = []
            for r in sorted(recs, key=lambda r: r["date"], reverse=True):
                cls = {"告知済み": "", "承認待ち": " art-wait", "予定あり": "", "未告知": " art-none"}[r["status"]]
                if r["status"] == "告知済み":
                    by_shelf = "・棚の記帳（台帳には次の取り込みで入る）" if r.get("announced_by") == "棚" else ""
                    days = f"公開から{r['days']:+d}日・" if r.get("days") is not None else ""
                    st = (f'<span class="tag ok-tag">告知済み</span> 告知日 {esc(r["announced_at"])}（{days}{esc(r.get("announced_kind", "投稿"))}{by_shelf}'
                          + (f'・他{r["n_posts"] - 1}本' if r["n_posts"] > 1 else "") + f'）　<a href="{esc(r["announced_url"])}">告知投稿</a>')
                elif r["status"] == "予定あり":
                    st = f'<span class="note">{esc(r["shelf_note"])}</span>'
                elif r["status"] == "承認待ち":
                    st = f'<span class="tag warn">承認待ち</span> {esc(r["shelf_note"])}'
                else:
                    st = '<span class="tag dup">未告知</span> 台帳にも棚にも同じURLの投稿・カードなし'
                cards_a.append(f"""<div class="card art{cls}">
  <div class="meta"><span class="date">{esc(r["date"])} ｜ <span class="sid">{esc(r["pillar"])}</span></span></div>
  <p class="art-title"><a href="{esc(r["url"])}">{esc(r["title"])}</a></p>
  <div class="note">{st}</div>
</div>""")
            articles_html = (f'<h2>記事（公開記事の告知状態） <span class="cnt">未告知{n_un}・承認待ち{n_wait}</span></h2>\n'
                             f'<p class="art-sum">未告知 <b>{n_un}</b>本／承認待ち <b>{n_wait}</b>本／予定あり <b>{n_plan}</b>本（記事{len(recs)}本・台帳{len(led.get("posts") or [])}件）</p>'
                             + "".join(cards_a))

    sections_html = (
        section_html(f"予定（承認済み・日付順。自動＝定時に機械が投稿／手動＝予定日に自分で出す）", scheduled)
        + section_html("投稿済み（新しい順・自動・手動とも）", posted_items, open_=False)
        + section_html("見送り（見送り・失効・差し替え・保留" + (f"・承認待ちの下書き{n_draft}件" if n_draft else "") + "）", dismissed, open_=False)
        + articles_html)

    if last:
        n_would, n_posted, n_err = len(last["would_post"]), len(last["posted"]), len(last["errors"])
        err_html = "".join(f'<div class="err">失敗: {esc(e["id"])} ── {esc(e["error"])}</div>' for e in last["errors"])
        mode = "本番" if last["mode"] == "live" else "試運転"
        run_html = (f'<p class="ok">投稿の実行あり（{mode}）: 対象{last["eligible"]}件'
                    f'／出す予定 {n_would}件／投稿 {n_posted}件／失敗 {n_err}件（{esc(last["ts"][11:16])}）</p>{err_html}')
    else:
        run_html = '<p class="warn">当日の投稿の実行なし</p>'

    gen = now.strftime("%Y-%m-%d %H:%M")
    receipt_cls, receipt_text = receipt_line(today, load_jsonl(path("receipt")), gen)
    spend_cls = "err" if spend_red else "ok"
    article_legend = ('<li><span class="tag ok-tag">告知済み</span> <span class="tag warn">承認待ち</span> <span class="tag dup">未告知</span> 「記事」の区画の印。'
                      '告知済み＝その記事のURLを含む投稿がXに出た（台帳に投稿がある、または棚のカードが投稿済みで投稿URLがある）。'
                      '承認待ち＝棚に下書きのカードがある。未告知＝どちらも無い</li>'
                      '<li><span class="note">予定 2026-01-01（ab12）</span> 「記事」の区画で、承認済みのカードが予定に入っている記事。承認待ちには数えない（件数は「予定あり」）</li>'
                      ) if articles_html else ""

    out = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>X投稿ボード</title>
<style>
  :root {{ --yellow:#f5c94f; --ink:#1f1f1f; --sub:#5f5f59; --line:#e5e2d9; --bg:#faf9f5;
           --warn:#8a6d1a; --red:#a32c12; --ok:#2f5d46; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:"Helvetica Neue","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
         background:var(--bg); color:var(--ink); margin:0; padding:20px 16px 64px;
         max-width:640px; margin-inline:auto; line-height:1.7; }}
  .gen {{ font-size:26px; font-weight:800; margin:0 0 2px; }}
  .gen-note {{ font-size:12px; color:var(--sub); margin:0 0 20px; }}
  .run-line {{ font-size:13px; margin:-8px 0 20px; }}
  .legend {{ font-size:13px; padding-left:0; list-style:none; margin:0 0 8px; }}
  .legend li {{ margin:0 0 6px; }}
  .legend .tag {{ margin-right:6px; }}
  h2 {{ font-size:15px; font-weight:800; border-left:4px solid var(--yellow); padding-left:8px; margin:26px 0 10px; }}
  h2 .cnt {{ font-size:12px; background:#efece3; color:var(--sub); border-radius:10px; padding:1px 8px; font-weight:700; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:12px; }}
  .meta {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:6px; }}
  .date {{ font-weight:700; font-size:13px; }}
  .sid {{ font-family:ui-monospace,Menlo,monospace; font-weight:400; color:var(--sub); }}
  .tag {{ background:var(--yellow); font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; }}
  .tag.warn {{ background:#fdf3d0; color:var(--warn); }}
  .tag.dup {{ background:#f6ddd6; color:var(--red); font-weight:700; }}
  .tag.ok-tag {{ background:#e3ede7; color:var(--ok); }}
  .tag.ch-auto {{ background:#dbe6f3; color:#2b3a55; }}
  .tag.ch-manual {{ background:#efe6f5; color:#5f5090; }}
  .tag.st-draft {{ background:#efece3; color:var(--sub); }}
  .tag.st-approved {{ background:var(--yellow); }}
  .tag.st-posted {{ background:#e3ede7; color:var(--ok); }}
  .tag.st-skipped, .tag.st-superseded {{ background:#eee; color:var(--sub); text-decoration:line-through; }}
  .tag.st-held {{ background:#efece3; color:var(--sub); }}
  .tag.st-expired {{ background:#f6ddd6; color:var(--red); }}
  .card.art {{ padding:10px 14px; }}
  .card.art-wait {{ border:2px solid var(--yellow); background:#fffbea; }}
  .card.art-none {{ border:2px solid var(--red); }}
  .art-title {{ margin:2px 0 4px; font-size:14px; font-weight:700; }}
  .art-title a {{ color:var(--ink); text-decoration:none; }}
  .art-sum {{ font-size:13px; margin:0 0 10px; }}
  .empty {{ font-size:13px; color:var(--sub); margin:0 0 12px; }}
  details.sec > summary {{ list-style:none; cursor:pointer; }}
  details.sec > summary::-webkit-details-marker {{ display:none; }}
  details.sec > summary h2::after {{ content:"（開く）"; font-size:12px; color:var(--sub); font-weight:400; margin-left:8px; }}
  details.sec[open] > summary h2::after {{ content:"（閉じる）"; }}
  .body {{ white-space:pre-wrap; font-size:14px; margin:4px 0 8px; font-family:inherit; }}
  .note {{ font-size:12px; color:var(--sub); margin:0 0 8px; }}
  .ok {{ font-size:13px; color:var(--ok); }}
  .warn {{ font-size:13px; color:var(--warn); font-weight:700; }}
  .err {{ font-size:13px; color:var(--red); font-weight:700; }}
  button {{ font-size:13px; padding:8px 12px; border-radius:6px; border:1px solid var(--yellow);
           background:var(--yellow); font-weight:700; cursor:pointer; }}
  .toast {{ position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--ink);
           color:#fff; font-size:13px; padding:8px 16px; border-radius:20px; opacity:0; transition:opacity .2s; }}
  .toast.show {{ opacity:1; }}
</style>
</head>
<body>
<p class="gen">生成: {gen}</p>
<p class="gen-note">承認・見送りは shelf.py で棚に記帳します（このページで書き換える操作はありません。コピーだけ）。</p>
<p class="{receipt_cls} run-line"><b>今朝の実行</b>: {esc(receipt_text)}</p>

<h2>印の説明</h2>
<ul class="legend">
<li><span class="tag">記事短報</span> 投稿の種類。記事短報・数字・問い・実況のどれか</li>
<li><span class="tag ch-auto">自動</span> 予定日の定時（目安 {esc(post_time)}）に機械が投稿する</li>
<li><span class="tag ch-manual">手動</span> 予定日に自分で出す。機械は投稿も失効もしない。出したあと、次の取り込みで投稿済みに記帳される</li>
<li><span class="tag st-approved">承認済み</span> 承認した予定。「予定」の区画に並ぶ</li>
<li><span class="tag st-draft">下書き（承認待ち）</span> まだ承認していない。承認するまでは「見送り」の区画に置いておく</li>
<li><span class="tag st-posted">投稿済み</span> Xに出た。自動は機械が記帳、手動は次の取り込みの照合で付く</li>
<li><span class="tag st-skipped">見送り</span> <span class="tag st-expired">失効</span> <span class="tag st-superseded">差し替え済み</span> 出さなかった・出せなかった記録。消さずに残す</li>
<li><span class="tag warn">同じURLを前に投稿済み（注意）</span> このURLは前にも投稿したことがある、という注意の印。自動のカードにだけ出す</li>
<li><span class="tag dup">Xに同じ投稿あり（1/12）</span> 同じ本文かURLの投稿が台帳にある。自動のカードにだけ出す</li>
<li><span class="tag dup">予定重複（1日1本なので後ろへずれる）</span> 同じ日に自動が複数ある。自動のカードにだけ出す</li>
<li><span class="tag dup">文字数超過（300）</span> Xの上限（重み付き280）を超えている。本番では送らない</li>
{article_legend}
<li><b>今朝の実行</b> ページ上部の行。当日の受領票（実行の最後に書く1行）があれば、開始時刻と各工程（取り込み・投稿・ボード更新）の成否。全部成功なら緑、1つでも成功以外なら赤。受領票が無ければ「未実行」（黄）</li>
<li><b>このボードの生成</b> 「今朝の実行」行の末尾の時刻。今日でなければ、定時実行そのものが動いていない可能性がある</li>
</ul>

<h2>今朝の実行</h2>
{run_html}

<h2>支出（X API・月累計）</h2>
<p class="{spend_cls}">${used:.3f} / 上限 ${spend_limit:.0f}（{month}{'・80%超' if spend_red else ''}）</p>

{sections_html}

<div class="toast" id="toast"></div>
<script>
function cp(btn){{
  const s = btn.dataset.t;
  const done = () => {{ const t = document.getElementById("toast");
    t.textContent = "コピーしました"; t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 1500); }};
  if(navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(s).then(done);
  else {{ const ta = document.createElement("textarea"); ta.value = s; document.body.appendChild(ta);
        ta.select(); document.execCommand("copy"); ta.remove(); done(); }}
}}
</script>
</body>
</html>
"""
    out_path = path("board")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")
    print(f"生成: {out_path.relative_to(KIT_ROOT)}（{len(shelf['items'])}件・{gen}）"
          f"　区画: 予定{len(scheduled)}／投稿済み{len(posted_items)}／見送り{len(dismissed)}"
          + (f"／記事: 未告知{n_un}・承認待ち{n_wait}・予定あり{n_plan}" if articles_html else "／記事区画なし"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
