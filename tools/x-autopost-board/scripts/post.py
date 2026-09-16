#!/usr/bin/env python3
"""post ── 棚（data/shelf.json）の承認済みの投稿を、予定日の朝に X へ出す（既定は投稿しない試運転）。

原則:
  - 対象は status=approved・投稿のしかた auto・予定日が当日のものだけ。予定日を過ぎた承認済み（自動）は失効（expired）
  - 1回の実行で最大1件。失敗しても自動で再送しない（再送も課金され、二重投稿の原因になる）。失敗は投稿ログに残す
  - --dry-run（既定）: 外に一切出ない。「would post」を記録し、棚の状態は変えない
  - --live: OAuth 1.0a（環境変数 X_API_KEY・X_API_SECRET・X_ACCESS_TOKEN・X_ACCESS_TOKEN_SECRET）で POST /2/tweets。
    送る前に文字数を再検査。成功で status=posted・posted_at・投稿URL を記帳
  - 安全装置: 記事URLが自分の投稿の台帳に既にあれば、投稿せず見送り（skipped）
  - 支出: 単価は config.yaml の spend（URL入り／テキストのみ）。月の上限を超える見込みなら送らず記録
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets as pysecrets
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import cost, handle, load_config, now_jst, path, spend_add, spend_status   # noqa: E402
from shelf import load_shelf, save_shelf, set_x_length   # noqa: E402
from own_posts import LEDGER as OWN_LEDGER, _norm_url   # noqa: E402

LOG_PATH = path("post_log")
TWEET_URL = "https://api.x.com/2/tweets"
ENVS = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]


def url_already_posted(item):
    """安全装置: 本文に含む記事URLが自分の投稿の台帳に既にあれば、その投稿を返す（無ければ None）。"""
    url = _norm_url(item.get("url"))
    if not url or not OWN_LEDGER.exists():
        return None
    try:
        posts = json.loads(OWN_LEDGER.read_text(encoding="utf-8")).get("posts") or []
    except (ValueError, OSError):
        return None
    hit = [p for p in posts if any(_norm_url(u) == url for u in p.get("urls") or [])]
    return sorted(hit, key=lambda p: p.get("created_at", ""), reverse=True)[0] if hit else None


def eligible_items(shelf, today):
    """対象＝予定日が当日の承認済み（自動）だけ。予定日を過ぎた承認済み（自動）は投稿せず expired（失効）へ移す。
    手動のカードは投稿も失効もしない（翌朝の照合で記帳される）。"""
    lo = today.isoformat()
    hi = today.isoformat()
    out, expired = [], []
    for i in shelf["items"]:
        if i.get("status") != "approved":
            continue
        if i.get("channel", "auto") == "manual":   # 手動分は投稿しない（失効もさせない。翌朝の台帳で posted 記帳）
            continue
        d = i.get("scheduled_date")
        if not d or d == "未定":
            continue
        if d < lo:
            i["status"] = "expired"
            expired.append(i)
        elif d <= hi:
            out.append(i)
    return sorted(out, key=lambda i: i["scheduled_date"]), expired


def compose(item):
    return item["text"] + ("\n" + item["url"] if item.get("url") else "")


def log_run(record):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _pct(s):
    return urllib.parse.quote(str(s), safe="~")


def oauth1_header(method, url, creds):
    p = {
        "oauth_consumer_key": creds["X_API_KEY"],
        "oauth_nonce": pysecrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    # JSONボディは署名対象に含めない（OAuth 1.0a仕様: application/json のため）
    param_str = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(p.items()))
    base = "&".join([method.upper(), _pct(url), _pct(param_str)])
    key = f"{_pct(creds['X_API_SECRET'])}&{_pct(creds['X_ACCESS_TOKEN_SECRET'])}"
    sig = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    p["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(p.items()))


def post_tweet(text, creds):
    """POST /2/tweets。成功で投稿id、失敗で例外。リトライしない。"""
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(TWEET_URL, data=payload, method="POST", headers={
        "Authorization": oauth1_header("POST", TWEET_URL, creds),
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as res:
        body = json.loads(res.read().decode("utf-8"))
    return body["data"]["id"]


def main():
    ap = argparse.ArgumentParser(description="棚の承認済みの投稿を出す（既定は試運転・最大1件/回）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--live", action="store_true")
    a = ap.parse_args()
    live = bool(a.live)

    now = now_jst()
    config = load_config()
    shelf = load_shelf()
    items, expired = eligible_items(shelf, now.date())
    if expired:
        save_shelf(shelf)
        for i in expired:
            print(f"[expired] 予定日を過ぎたため失効: {i['id']}（{i['scheduled_date']}）")

    record = {"ts": now.isoformat(timespec="seconds"), "mode": "live" if live else "dryrun",
              "eligible": len(items), "would_post": [], "posted": [], "errors": [],
              "expired": [{"id": i["id"], "scheduled_date": i["scheduled_date"]} for i in expired]}

    creds = {e: os.environ.get(e, "").strip() for e in ENVS}
    if live and not all(creds.values()):
        missing = [e for e in ENVS if not creds[e]]
        sys.exit(f"エラー: 投稿には OAuth のユーザートークンが要ります（未設定: {', '.join(missing)}）。値はリポジトリに書かない")
    if live and not handle():
        sys.exit("エラー: アカウント名が未設定です（config.yaml の account.handle か環境変数 X_HANDLE）")

    target = items[0] if items else None
    if target is not None and len(items) > 1:
        print(f"[post] 対象{len(items)}件のうち先頭1件のみ処理（最大1件/回）")

    if target is not None:
        dup = url_already_posted(target)
        if dup:
            md = dup.get("created_at", "")[5:10].replace("-", "/")
            record["skipped_dup"] = [{"id": target["id"], "url": target.get("url"), "seen": dup.get("url"), "seen_at": dup.get("created_at", "")}]
            print(f"[post] 見送り: 台帳に同じURLの投稿あり（{md}・{dup.get('url')}）→ skipped: {target['id']}")
            if live:
                target["status"] = "skipped"
                target["note"] = (target.get("note", "") + " ／ " if target.get("note") else "") + f"台帳に同じURLの投稿あり（{md}）・自動で見送り"
                save_shelf(shelf)
            target = None

    if target is not None:
        text = compose(target)
        if not live:
            print(f"[dry-run] would post（{target['scheduled_date']}・{target['kind']}）: {text.splitlines()[0][:40]}…")
            record["would_post"].append({"id": target["id"], "chars": len(text)})
        else:
            set_x_length(target)
            price = cost("cost_per_post_with_url_usd", 0.20) if target.get("url") else cost("cost_per_post_usd", 0.015)
            used, limit, month = spend_status(config)
            if target.get("x_over"):
                record["errors"].append({"id": target["id"], "error": f"文字数超過のため送らず（重み付き {target['x_length']}）"})
            elif used + price > limit:
                record["errors"].append({"id": target["id"],
                                         "error": f"支出上限のため送らず（{month} ${used:.2f}+${price} > ${limit}）"})
            else:
                try:
                    tweet_id = post_tweet(text, creds)
                    spend_add(config, price)
                    target["status"] = "posted"
                    target["posted_at"] = now.isoformat(timespec="seconds")
                    target["x_url"] = f"https://x.com/{handle()}/status/{tweet_id}"
                    save_shelf(shelf)
                    record["posted"].append({"id": target["id"], "x_url": target["x_url"], "cost_usd": price})
                    print(f"[live] posted: {target['x_url']}")
                except Exception as e:   # 再送しない（課金・二重投稿の防止）
                    record["errors"].append({"id": target["id"], "error": f"送信失敗: {e}"})
                    print(f"[live] 送信失敗（再送しない）: {e}", file=sys.stderr)

    log_run(record)
    print(f"[post] mode={record['mode']} 対象{len(items)}件 → {LOG_PATH.name} に記録")
    return 0


if __name__ == "__main__":
    sys.exit(main())
