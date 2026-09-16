#!/usr/bin/env python3
"""make_sample ── 試運転用のサンプルデータを作る（すべて架空。URL は example.com）。

作るもの（既にあれば上書きする。自分のデータがある環境では実行しない）:
  - data/shelf.json            架空のカード5枚（自動の予定・手動の予定・投稿済み・見送り・下書き）
  - data/run_receipt.jsonl     受領票2行（成功1行・失敗1行）
  - data/own_posts.json        空の台帳
  - data/post_log.jsonl        空
  - data/shelf_registered.jsonl 空
  - data/spend.json            空
  - sample/articles/notes/     架空の記事3本（記事区画の見本）

使い方:
    python3 scripts/make_sample.py
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KIT_ROOT, now_jst, path, section   # noqa: E402
from shelf import stable_id, x_weight, X_LIMIT   # noqa: E402

BASE = "https://example.com"


def card(key, kind, channel, source, text, status, day, url="", note="", posted_at=None, x_url=None):
    t = str(section("schedule").get("post_time") or "07:00")
    item = {"id": stable_id(source, key), "kind": kind, "channel": channel, "source": source, "text": text,
            "slug": url.rstrip("/").split("/")[-1] if url else "", "scheduled_date": day,
            "created_at": (now_jst() - timedelta(days=3)).isoformat(timespec="seconds"),
            "note": note, "url": url, "status": status, "scheduled_time": t}
    item["x_length"] = x_weight(text, url)
    item["x_over"] = item["x_length"] > X_LIMIT
    if posted_at:
        item["posted_at"] = posted_at
    if x_url:
        item["x_url"] = x_url
    return item


def main():
    now = now_jst()
    today = now.date()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    a1 = f"{BASE}/notes/sample-article-1/"
    a2 = f"{BASE}/notes/sample-article-2/"

    items = [
        card("sample-auto", "記事短報", "auto", "article",
             "サンプルの記事2を公開しました。下書きをカードで並べて、承認したものだけを朝に出す、という話です。",
             "approved", d(0), url=a2, note="サンプル: 今日の自動の予定"),
        card("sample-manual", "実況", "manual", "other",
             "サンプルの実況です。画像を付けて自分で出す投稿は「手動」にしておきます。",
             "approved", d(1), note="サンプル: 明日の手動の予定"),
        card("sample-posted", "記事短報", "auto", "article",
             "サンプルの記事1を公開しました。",
             "posted", d(-1), url=a1, note="サンプル: 昨日出した投稿",
             posted_at=(now - timedelta(days=1)).isoformat(timespec="seconds"), x_url=f"{BASE}/x/status/1001"),
        card("sample-skipped", "問い", "auto", "other",
             "サンプルの問いです。予定から外したので、見送りの区画に残っています。",
             "skipped", "未定", note="サンプル: 見送り"),
        card("sample-draft", "数字", "auto", "other",
             "サンプルの数字の投稿です（下書き）。承認するまでは予定に入りません。",
             "draft", "未定", note="サンプル: 下書き"),
    ]
    p = path("shelf")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    rows = [
        {"ts": (now - timedelta(days=2)).isoformat(timespec="seconds"), "workflow": "x-board-daily", "run_id": "sample-1",
         "run_number": "1", "event": "schedule", "started_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
         "steps": {"own_posts": "failure", "post": "skipped", "board": "success"},
         "details": {"own_posts": {"reconcile": {"posted_count": None, "skipped_count": None, "note": "照合結果なし（取り込みが照合の前で止まった）"}}}},
        {"ts": (now - timedelta(days=1)).isoformat(timespec="seconds"), "workflow": "x-board-daily", "run_id": "sample-2",
         "run_number": "2", "event": "schedule", "started_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
         "steps": {"own_posts": "success", "post": "success", "board": "success"},
         "details": {"own_posts": {"reconcile": {"posted_count": 0, "posted": [], "skipped_count": 0, "skipped": [], "mode": "write"}}}},
    ]
    path("receipt").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    path("own_posts").write_text(json.dumps({"handle": "", "own_id": None, "since_id": None, "updated_at": None, "posts": []},
                                            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for key in ("post_log", "shelf_registered"):
        path(key).write_text("", encoding="utf-8")
    path("spend").write_text("{}\n", encoding="utf-8")

    art = KIT_ROOT / "sample" / "articles" / "notes"
    art.mkdir(parents=True, exist_ok=True)
    for n, (title, day) in enumerate((("サンプルの記事1（告知済みの見本）", d(-5)),
                                      ("サンプルの記事2（予定ありの見本）", d(-1)),
                                      ("サンプルの記事3（未告知の見本）", d(-10))), start=1):
        (art / f"sample-article-{n}.md").write_text(
            f"---\ntitle: {title}\ndate: {day}\n---\n\nこれは架空の記事です。\n", encoding="utf-8")
    print(f"サンプルを作りました: 棚{len(items)}枚・受領票{len(rows)}行・記事3本（{art.relative_to(KIT_ROOT)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
