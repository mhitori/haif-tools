#!/usr/bin/env python3
"""own_posts ── 自分の投稿を X から取り込んで台帳（data/own_posts.json）に貯め、手で出した投稿を棚と照合して記帳する。

定時実行の最初の工程。手で出した投稿を棚に posted と記帳して、同じ投稿を機械がもう一度出すのを防ぐ。
  - X API v2 GET /2/users/:id/tweets（Bearer・読み取りのみ）。前回以降（since_id）の差分。初回は取れる過去分を全件
    （ページング・上限 MAX_INITIAL 件）。読み取り数×cost_per_read_usd を支出カウンタへ加算
  - 台帳の中身: id・日時・本文・投稿URL・展開済みURL・返信先・指標。追記のみ・id で重複を除く
  - 照合: 棚の approved／draft のうち、同じURL（展開済みURLが一致）または本文の先頭60字が一致する投稿が台帳にあれば
    status=posted・posted_at・x_url・note を記帳（棚の保存の後にボードを作り直す）
  - 照合の成立条件: 投稿日時がそのカードの登録時刻（登録台帳）より後であること。URL一致・本文先頭60字一致のどちらにもかける。
    登録時刻が見つからないカードは照合しない（posted にしない）。前に出したURLを再掲する投稿が、出す前に posted になるのを防ぐ
  - 照合の結果は data/work/own_posts_reconcile.json に書き、受領票（receipt.py）が1行に残す（0件の日も0件と書く）
  - held は自動では記帳しない

使い方:
    export X_BEARER_TOKEN=...
    python3 scripts/own_posts.py            # 取り込み（差分）→ 照合・記帳
    python3 scripts/own_posts.py --offline  # 取り込まず（API を呼ばず）、手元の台帳で照合・記帳する（試運転用）
    python3 scripts/own_posts.py --check    # 取り込まず、手元の台帳で照合結果を表示するだけ（書かない）
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import JST, cost, handle, load_config, now_jst, path, section, spend_add, spend_check_or_exit, spend_status   # noqa: E402
import shelf as shelf_mod   # noqa: E402

API = "https://api.x.com/2"
OWN_HANDLE = handle()
LEDGER = path("own_posts")
PROFILE_PATH = path("profile")
REGISTERED = path("shelf_registered")
RECONCILE_OUT = path("work") / "own_posts_reconcile.json"
SKIP_NO_REG = "登録時刻なしのため照合せず"
SKIP_BEFORE_REG = "一致した投稿がすべて登録時刻より前のため照合せず"
# 棚の種類 → 台帳の種類欄（同じ名前をそのまま使う）
OPS_KIND_MAP = {"記事短報": "記事短報", "数字": "数字", "問い": "問い", "実況": "実況"}
HEAD_LEN = 60
# public_metrics の対応表（台帳のキー: APIのキー）。impression_count は Bearer（アプリ認証）では返らないことがある
METRIC_KEYS = {"like": "like_count", "reply": "reply_count", "quote": "quote_count",
               "repost": "retweet_count", "impression": "impression_count"}
METRIC_JA = {"like": "いいね", "reply": "返信", "quote": "引用", "repost": "リポスト", "impression": "インプレッション"}
MAX_INITIAL = 1000
PAGE = 100


def load_ledger():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"handle": OWN_HANDLE, "own_id": None, "since_id": None, "updated_at": None, "posts": []}


def save_ledger(ledger):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def published_articles():
    """公開記事の一覧 [(公開日, サブフォルダ名, 題, URL)]。config.yaml の articles.articles_dir の Markdown（front matter の
    title・date。draft: true は除く）から作る。URL は articles.article_url の {dir}・{slug} を埋めて組み立てる。
    articles_dir が空なら空の一覧（記事区画は出さない）。"""
    cfg = section("articles")
    d = str(cfg.get("articles_dir") or "").strip()
    pattern = str(cfg.get("article_url") or "").strip()
    if not d or not pattern:
        return [], "記事の設定なし"
    from common import KIT_ROOT
    root = __import__("pathlib").Path(d)
    root = root if root.is_absolute() else KIT_ROOT / root
    rows = []
    for md in sorted(list(root.glob("*.md")) + list(root.glob("*/*.md"))):
        head = md.read_text(encoding="utf-8")[:800]
        if "draft: true" in head:
            continue
        dm = re.search(r"^date:\s*(\S+)", head, re.M)
        tm = re.search(r"^title:\s*(.+)$", head, re.M)
        if dm and tm:
            sub = md.parent.name if md.parent != root else ""
            url = pattern.replace("{dir}", sub).replace("{slug}", md.stem).replace("//{", "/{")
            url = re.sub(r"(?<!:)//+", "/", url)
            rows.append((dm.group(1), sub or "—", tm.group(1).strip(), url))
    return sorted(rows), d


def get(url, params, token):
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def _jst(iso_utc):
    try:
        return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(JST).isoformat(timespec="seconds")
    except ValueError:
        return iso_utc


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def _head(text):
    """照合用の本文先頭60字（空白除去・t.co のURLを除く）。"""
    return _norm(re.sub(r"https?://t\.co/\S+", "", text or ""))[:HEAD_LEN]


def slug_of_url(u):
    path = re.sub(r"^https?://[^/]+", "", u or "").strip("/")
    return path.split("/")[-1] if path else ""


def _norm_url(u):
    return (u or "").strip().rstrip("/").replace("http://", "https://")


def to_row(t):
    refs = t.get("referenced_tweets") or []
    kind = "投稿"
    reply_to = None
    for r in refs:
        if r.get("type") == "replied_to":
            kind, reply_to = "返信", r.get("id")
        elif r.get("type") == "retweeted":
            kind = "RT"
        elif r.get("type") == "quoted":
            kind = "引用"
    urls = [u.get("unwound_url") or u.get("expanded_url") or u.get("url")
            for u in ((t.get("entities") or {}).get("urls") or [])]
    pm = t.get("public_metrics") or {}
    # 指標: いいね・返信・引用・リポスト・インプレッション。返ってこない指標は None＝「取得不可」
    metrics = {k: pm.get(src) for k, src in METRIC_KEYS.items()}
    row = {"id": t["id"], "created_at": _jst(t.get("created_at", "")), "text": t.get("text", ""),
           "url": f"https://x.com/{OWN_HANDLE}/status/{t['id']}", "kind": kind,
           "urls": [u for u in urls if u], "metrics": metrics}
    if reply_to:
        row["in_reply_to"] = reply_to
    return row


def fetch(ledger, token, config, initial_all):
    """(取得した行, 読み取り数)。since_id があれば差分、無ければ（初回）ページングで過去分を全件。"""
    rate = float((config.get("spend") or {}).get("cost_per_read_usd", 0.005))
    reads = 0
    if not ledger.get("own_id"):
        ledger["own_id"] = get(f"{API}/users/by/username/{OWN_HANDLE}", {}, token)["data"]["id"]
        reads += 1
    est = (MAX_INITIAL if initial_all else PAGE) + 1
    spend_check_or_exit(config, est * rate, f"own_posts（最大{est}件の読み取り）")
    params = {"max_results": PAGE, "tweet.fields": "created_at,referenced_tweets,entities,public_metrics"}
    if ledger.get("since_id") and not initial_all:
        params["since_id"] = ledger["since_id"]
    rows, token_next = [], None
    while True:
        if token_next:
            params["pagination_token"] = token_next
        body = get(f"{API}/users/{ledger['own_id']}/tweets", params, token)
        got = body.get("data") or []
        reads += len(got)
        rows += [to_row(t) for t in got]
        token_next = (body.get("meta") or {}).get("next_token")
        if not token_next or not initial_all or len(rows) >= MAX_INITIAL:
            break
    return rows, reads


def matches(item, posts):
    """棚の1件に一致する投稿（同じURL または 本文先頭60字一致）を新しい順で返す。"""
    url = _norm_url(item.get("url"))
    head = _head(item.get("text", ""))
    hit = []
    for p in posts:
        if p.get("kind") in ("RT",):
            continue
        by_url = bool(url) and any(_norm_url(u) == url for u in p.get("urls") or [])
        by_head = bool(head) and len(head) >= 20 and _head(p.get("text", "")) == head
        if by_url or by_head:
            hit.append((p, "URL一致" if by_url else "本文先頭60字一致"))
    return sorted(hit, key=lambda x: x[0]["created_at"], reverse=True)


def article_status(ledger, shelf=None):
    """公開記事ごとの告知状態。戻り値: ([dict], 出所)。
    告知済みの根拠は2つ（どちらか一方で告知済み）: ①台帳に、その記事のURLを含む投稿がある
    ②棚に status=posted かつ x_url があり、そのカードの url がその記事のURL（同じ朝に出した告知は②でしか分からない）。
    承認待ち＝棚に draft のカード／予定あり＝棚に approved のカード／未告知＝どれも無い。"""
    from datetime import date as _date
    posts = ledger.get("posts") or []
    if shelf is None:
        shelf = shelf_mod.load_shelf()
    rows, src = published_articles()
    out = []
    for d, pillar, title, url in rows:
        nu = _norm_url(url)
        hits = sorted((p for p in posts if any(_norm_url(x) == nu for x in p.get("urls") or [])), key=lambda p: p["created_at"])
        shelf_posted = sorted((i for i in shelf["items"]
                               if i.get("status") == "posted" and i.get("x_url") and _norm_url(i.get("url")) == nu),
                              key=lambda i: i.get("posted_at") or "")
        drafts = [i for i in shelf["items"] if i.get("status") == "draft" and _norm_url(i.get("url")) == nu]
        approved = [i for i in shelf["items"] if i.get("status") == "approved" and _norm_url(i.get("url")) == nu]
        # 告知投稿の集合（台帳の投稿と棚の x_url を、投稿URLで重ねて数える）
        seen = {}
        for p in hits:
            seen.setdefault(p["url"], {"at": p["created_at"], "url": p["url"], "kind": p.get("kind", "投稿"), "by": "台帳"})
        for i in shelf_posted:
            seen.setdefault(i["x_url"], {"at": i.get("posted_at") or "", "url": i["x_url"], "kind": "投稿", "by": "棚"})
        announced = sorted(seen.values(), key=lambda a: a["at"] or "9999")
        rec = {"date": d, "pillar": pillar, "title": title, "url": url, "n_posts": len(announced), "shelf_note": ""}
        if announced:
            first = announced[0]
            rec["status"] = "告知済み"; rec["announced_at"] = (first["at"] or "")[:10]; rec["announced_url"] = first["url"]
            rec["announced_kind"] = first["kind"]; rec["announced_by"] = first["by"]
            try:
                rec["days"] = (_date.fromisoformat(rec["announced_at"]) - _date.fromisoformat(d)).days
            except ValueError:
                rec["days"] = None
        elif drafts:
            c = drafts[0]
            rec["status"] = "承認待ち"; rec["announced_at"] = ""; rec["announced_url"] = ""; rec["days"] = None
            rec["shelf_note"] = f"棚に承認待ち（{c['id'][:4]}）"
        elif approved:
            c = approved[0]
            rec["status"] = "予定あり"; rec["announced_at"] = ""; rec["announced_url"] = ""; rec["days"] = None
            rec["shelf_note"] = f"予定 {c.get('scheduled_date')}（{c['id'][:4]}）"
        else:
            rec["status"] = "未告知"; rec["announced_at"] = ""; rec["announced_url"] = ""; rec["days"] = None
        out.append(rec)
    return out, src


def record_profile(token, own_id, config):
    """自アカウントのフォロワー数など（followers_count・following_count・tweet_count）を1行追記（読み取り1件）。"""
    body = get(f"{API}/users/{own_id}", {"user.fields": "public_metrics"}, token)
    pm = (body.get("data") or {}).get("public_metrics") or {}
    row = {"ts": now_jst().isoformat(timespec="seconds"), "followers": pm.get("followers_count"),
           "following": pm.get("following_count"), "tweet_count": pm.get("tweet_count"), "source": "api"}
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROFILE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def backfill_kinds(ledger):
    """棚の x_url と台帳の投稿を突き合わせ、台帳の投稿に種類欄 ops_kind を付ける（無い投稿は付けない）。"""
    posts = {p["id"]: p for p in ledger.get("posts") or []}
    n = 0
    for i in shelf_mod.load_shelf()["items"]:
        xid = (i.get("x_url") or "").rstrip("/").split("/")[-1]
        k = OPS_KIND_MAP.get(i.get("kind", ""))
        if xid in posts and k and posts[xid].get("ops_kind") != k:
            posts[xid]["ops_kind"] = k; n += 1
    return n


def registered_times():
    """棚の登録時刻 {id: datetime}（登録台帳 shelf_registered.jsonl）。読めない行は飛ばす。"""
    out = {}
    if not REGISTERED.exists():
        return out
    for line in REGISTERED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out[r["id"]] = datetime.fromisoformat(r["registered_at"])
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _post_time(p):
    try:
        return datetime.fromisoformat(p.get("created_at", ""))
    except ValueError:
        return None


def reconcile(ledger, write=True, shelf=None, registered=None):
    """承認済み・下書きのカードを台帳と照合し、posted と記帳する。held は表示のみ。
    成立条件: 一致した投稿の日時 > そのカードの登録時刻（URL一致・本文先頭60字一致の両方）。
    登録時刻が無いカードは照合しない。戻り値: (表示用の行, posted 記帳数, 結果dict)。
    結果dict は受領票用: posted（id・根拠 url/head60・投稿の日時とURL）／skipped（件数と理由別のid）。"""
    if shelf is None:
        shelf = shelf_mod.load_shelf()
    if registered is None:
        registered = registered_times()
    posts = ledger.get("posts") or []
    lines, changed = [], 0
    posted, skipped = [], {}
    for i in shelf["items"]:
        st = i.get("status", "draft")
        if st not in ("approved", "draft", "held"):
            continue
        hit = matches(i, posts)
        if not hit:
            continue
        reg = registered.get(i["id"])
        if reg is None:
            skipped.setdefault(SKIP_NO_REG, []).append(i["id"])
            lines.append(f"  {i['id'][:6]} {st} 予定{i.get('scheduled_date')} ── {SKIP_NO_REG}")
            continue
        after = [(p, why) for p, why in hit if (_post_time(p) or reg) > reg]
        if not after:
            skipped.setdefault(SKIP_BEFORE_REG, []).append(i["id"])
            p0 = hit[0][0]
            lines.append(f"  {i['id'][:6]} {st} 予定{i.get('scheduled_date')} ── {SKIP_BEFORE_REG}"
                         f"（登録 {reg.isoformat(timespec='minutes')}・最新の一致 {p0['created_at'][:16]} {p0['url']}）")
            continue
        p, why = after[0]
        basis = "url" if why == "URL一致" else "head60"
        lines.append(f"  {i['id'][:6]} {st} 予定{i.get('scheduled_date')} ← X {p['created_at'][:16]} {p['url']}（{why}）")
        if st in ("approved", "draft"):
            posted.append({"id": i["id"], "basis": basis, "post_at": p["created_at"], "post_url": p["url"]})
            if write:
                i["status"] = "posted"
                i["posted_at"] = p["created_at"]
                i["x_url"] = p["url"]
                i["note"] = (i.get("note", "") + " ／ " if i.get("note") else "") + \
                            f"手動投稿を自動照合（own_posts・{why}・{now_jst().date().isoformat()}）"
                changed += 1
    if changed and write:
        shelf_mod.save_shelf(shelf)   # ボードも再生成される
    result = {"posted_count": len(posted), "posted": posted,
              "skipped_count": sum(len(v) for v in skipped.values()),
              "skipped": [{"reason": k, "count": len(v), "ids": v} for k, v in skipped.items()],
              "mode": "write" if write else "dryrun"}
    return lines, changed, result


def write_reconcile_result(result):
    RECONCILE_OUT.parent.mkdir(parents=True, exist_ok=True)
    RECONCILE_OUT.write_text(json.dumps({"at": now_jst().isoformat(timespec="seconds"), **result},
                                        ensure_ascii=False, indent=1), encoding="utf-8")



def main():
    ap = argparse.ArgumentParser(description="自分の投稿の取り込みと棚の照合")
    ap.add_argument("--offline", action="store_true", help="取り込まず（API を呼ばず）、手元の台帳で照合・記帳する（試運転用）")
    ap.add_argument("--check", action="store_true", help="取り込まず、手元の台帳で照合結果を表示するだけ（書かない）")
    ap.add_argument("--refetch", action="store_true", help="since_id を無視して過去分を全件取り直す")
    a = ap.parse_args()
    ledger = load_ledger()
    config = load_config()

    if a.check:
        lines, _, res = reconcile(ledger, write=False)
        print(f"[own_posts --check] 台帳{len(ledger.get('posts') or [])}件（最終更新 {ledger.get('updated_at') or '未取得'}）")
        print("\n".join(lines) if lines else "  一致なし")
        print(f"  posted にする: {res['posted_count']}件／照合せず: {res['skipped_count']}件（書き込まない）")
        return 0

    if RECONCILE_OUT.exists():   # 前回の結果を受領票に持ち越さない
        RECONCILE_OUT.unlink()

    if not a.offline:
        token = os.environ.get("X_BEARER_TOKEN", "").strip()
        if not token:
            sys.exit("エラー: X_BEARER_TOKEN が未設定です（試運転なら --offline）")
        if not OWN_HANDLE:
            sys.exit("エラー: アカウント名が未設定です（config.yaml の account.handle か環境変数 X_HANDLE）")
        initial_all = a.refetch or not ledger.get("since_id")
        now = now_jst()
        try:
            rows, reads = fetch(ledger, token, config, initial_all)
        except urllib.error.HTTPError as e:
            sys.exit(f"取得失敗: HTTP {e.code} ── {e.read().decode('utf-8', 'replace')[:200]}")
        rate = cost("cost_per_read_usd", 0.005)
        try:   # フォロワー数を1日1回記帳。失敗しても取り込みは続ける
            record_profile(token, ledger["own_id"], config); reads += 1
        except Exception as e:
            print(f"警告: プロフィールの取得に失敗（{type(e).__name__}）。記帳しない", file=sys.stderr)
        spend_add(config, round(reads * rate, 4))
        used, limit, month = spend_status(config)
        known = {p["id"] for p in ledger.get("posts") or []}
        new = [r for r in rows if r["id"] not in known]
        print(f"[own_posts] 取得{len(rows)}件（{'初回・全件' if initial_all else '差分'}）・新規{len(new)}件・"
              f"読み取り{reads}件・概算${reads * rate:.3f}（今月累計 ${used} / 上限 ${limit}・{month}）")
        by_id = {r["id"]: r for r in rows}
        for p in ledger.get("posts") or []:
            if p["id"] in by_id:
                p["metrics"] = by_id[p["id"]].get("metrics", p.get("metrics"))
        ledger["posts"] = sorted((ledger.get("posts") or []) + new, key=lambda p: p["created_at"])
        if rows:
            ledger["since_id"] = str(max(int(r["id"]) for r in rows + [{"id": ledger.get("since_id") or "0"}]))
        ledger["updated_at"] = now.isoformat(timespec="seconds")
        save_ledger(ledger)
    else:
        print(f"[own_posts --offline] 取り込みなし（API を呼ばない）。手元の台帳 {len(ledger.get('posts') or [])}件で照合する")

    lines, changed, res = reconcile(ledger, write=True)
    write_reconcile_result(res)
    n_kind = backfill_kinds(ledger)
    if LEDGER.exists() or ledger.get("posts"):
        save_ledger(ledger)
    print(f"[own_posts] 台帳{len(ledger.get('posts') or [])}件。棚の照合: 一致{len(lines)}件・posted記帳{changed}件・"
          f"照合せず{res['skipped_count']}件・種類欄の付与{n_kind}件")
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
