#!/usr/bin/env python3
"""shelf ── 棚（data/shelf.json）への投稿の登録・承認・記帳・一覧。

棚は「承認した投稿を予定日つきで置いておく場所」。状態の正はこのファイル1つで、ボードは棚から作る表示専用のページ。
  - shelf.json への書き込みは、このスクリプト（と投稿・照合の処理）だけ。手で編集しない
  - 登録時に X の文字数（重み付き）を数え、上限を超えていれば警告してボードに印を出す
  - 登録台帳 shelf_registered.jsonl で同じ id の二重登録を止める。登録時刻は手動投稿の照合に使う
  - 同じ記事（slug）の未投稿が棚にあれば、新しく登録しない（--allow-dup で上書き）

使い方:
    python3 scripts/shelf.py add --kind 記事短報 --source article --key 記事の識別子 --text-file 本文.txt \
        --url https://example.com/記事/ [--channel manual] [--scheduled-date 2026-01-01]
    python3 scripts/shelf.py approve <id>      # 承認（予定に入る）
    python3 scripts/shelf.py update <id> --scheduled-date 2026-01-02
    python3 scripts/shelf.py skip <id>         # 見送り（消さずに残す）
    python3 scripts/shelf.py posted <id> --x-url https://x.com/...   # 手で出した投稿の記帳（ふだんは翌朝の照合が記帳する）
    python3 scripts/shelf.py plan              # 予定日が未定のものに日付を割り当てる（1日1本・7日先まで）
    python3 scripts/shelf.py list
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KIT_ROOT, now_jst, path, section   # noqa: E402

KINDS = ["記事短報", "数字", "問い", "実況"]
CHANNELS = ["auto", "manual"]   # auto=定時実行が投稿する／manual=予定日に自分で出し、翌朝の照合で記帳される
SOURCES = ["article", "other"]
PLAN_PRIORITY = {"article": 0, "other": 1}
PLAN_HORIZON_DAYS = 7
PENDING = ("draft", "approved", "held")
X_LIMIT = 280   # X の重み付き上限（半角1・全角2・URLは1本23）


def stable_id(source, key):
    return hashlib.sha1(f"{source}:{key}".encode("utf-8")).hexdigest()[:12]


def load_shelf():
    p = path("shelf")
    if not p.exists():
        return {"items": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_shelf(shelf):
    p = path("shelf")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(shelf, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    regen_board()


def regen_board():
    """棚を書いた直後にボードを作り直す。失敗しても記帳は成立させる（警告のみ）。"""
    try:
        r = subprocess.run([sys.executable, str(KIT_ROOT / "scripts" / "board.py")],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            print("  " + (r.stdout.strip().splitlines() or ["ボードを作り直しました"])[-1])
        else:
            print(f"警告: ボードの作り直しに失敗（記帳は保存済み）: {(r.stderr or r.stdout).strip().splitlines()[-1:]}", file=sys.stderr)
    except Exception as e:
        print(f"警告: ボードの作り直しをスキップ（記帳は保存済み）: {e}", file=sys.stderr)


def ledger_ids():
    p = path("shelf_registered")
    if not p.exists():
        return set()
    return {json.loads(l)["id"] for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}


def ledger_append(item_id):
    p = path("shelf_registered")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": item_id, "registered_at": now_jst().isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")


def x_weight(text, url=""):
    """X の重み付き文字数。半角1・全角（East Asian Width が W/F/A）2・URLは1本23。本文中のURLも23で数える。"""
    body = re.sub(r"https?://\S+", "", text or "")
    n_urls = len(re.findall(r"https?://\S+", text or "")) + (1 if url else 0)
    w = sum(2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1 for ch in body)
    return w + 23 * n_urls


def set_x_length(item):
    """item に x_length（重み付き文字数）と x_over（上限超過）を記帳し、超過なら警告を出す。"""
    item["x_length"] = x_weight(item.get("text", ""), item.get("url", ""))
    item["x_over"] = item["x_length"] > X_LIMIT
    if item["x_over"]:
        print(f"警告: 文字数超過 ── 重み付き {item['x_length']}（上限 {X_LIMIT}）。ボードに「文字数超過」の印が出ます", file=sys.stderr)
    return item["x_length"]


def slug_of(url):
    """記事URL → slug（末尾のパス要素）。URLなしは空。"""
    p = re.sub(r"^https?://[^/]+", "", url or "").strip("/")
    return p.split("/")[-1] if p else ""


def item_slug(item):
    return item.get("slug") or slug_of(item.get("url", ""))


def posted_index(shelf):
    """投稿済み（投稿ログの自動投稿＋記帳済みの posted）を slug → [item] で返す。"""
    logged = set()
    if path("post_log").exists():
        for line in path("post_log").read_text(encoding="utf-8").splitlines():
            if line.strip():
                for p in json.loads(line).get("posted", []) or []:
                    logged.add(p.get("id"))
    idx = {}
    for i in shelf["items"]:
        if i.get("status") == "posted" or i["id"] in logged:
            s = item_slug(i)
            if s:
                idx.setdefault(s, []).append(i)
    return idx


def check_duplicates(shelf, item):
    """(投稿済みの同slugのリスト, 棚に残る同slugの未投稿リスト)。item自身は除く。"""
    s = item_slug(item)
    if not s:
        return [], []
    posted = [p for p in posted_index(shelf).get(s, []) if p["id"] != item["id"]]
    pending = [i for i in shelf["items"]
               if i["id"] != item["id"] and i.get("status") in PENDING and item_slug(i) == s]
    return posted, pending


def warn_posted_duplicate(shelf, item):
    posted, _ = check_duplicates(shelf, item)
    for p in posted:
        print(f"警告: 投稿済みの記事と同じslug「{item_slug(item)}」── {p['id'][:6]}（"
              f"{p.get('posted_at', '—')[:10]}・{p.get('x_url') or 'URLなし'}）", file=sys.stderr)


def warn_x_ledger(item):
    """自分の投稿の台帳と照合し、同じURLか本文先頭60字が一致する投稿があれば警告（止めない）。"""
    p = path("own_posts")
    if not p.exists():
        return []
    try:
        import own_posts
        posts = json.loads(p.read_text(encoding="utf-8")).get("posts") or []
        hit = own_posts.matches(item, posts)
    except Exception as e:
        print(f"警告: 投稿台帳の照合をスキップ: {e}", file=sys.stderr)
        return []
    for post, why in hit[:3]:
        print(f"警告: 同じ投稿がXにあります（{post['created_at'][5:10].replace('-', '/')}）── {post['url']}（{why}）", file=sys.stderr)
    return hit


def warn_schedule_conflict(shelf, item):
    """同じ日に自動の承認済み・下書きが2件以上なら警告（止めない。1日1本なので次の日へずれる）。"""
    d, t = item.get("scheduled_date"), item.get("scheduled_time")
    if not d or d == "未定" or item.get("channel", "auto") == "manual":
        return
    dup = [i for i in shelf["items"]
           if i.get("scheduled_date") == d and i.get("scheduled_time") == t
           and i.get("status") in ("approved", "draft") and i.get("channel", "auto") != "manual"]
    if len(dup) >= 2:
        print(f"警告: 予定重複 ── {d} {t} に自動が{len(dup)}件（{' / '.join(i['id'][:6] for i in dup)}）", file=sys.stderr)


def read_text_arg(text_file):
    return (sys.stdin.read() if text_file == "-" else Path(text_file).read_text(encoding="utf-8")).strip()


def split_trailing_url(text, url):
    """本文の最後の行がURLだけなら url 欄へ移す（ボードのコピーは「本文＋改行＋URL」）。"""
    lines = text.splitlines()
    if not url and lines and re.fullmatch(r"https?://\S+", lines[-1].strip()):
        return "\n".join(lines[:-1]).rstrip(), lines[-1].strip()
    return text, url


def cmd_add(a):
    text = read_text_arg(a.text_file)
    if not text:
        sys.exit("エラー: 本文が空です")
    text, url = split_trailing_url(text, a.url or "")
    item_id = stable_id(a.source, a.key)
    if item_id in ledger_ids():
        sys.exit(f"エラー: id={item_id}（{a.source}:{a.key}）は登録済み（二重登録はしない）")
    shelf = load_shelf()
    probe = {"id": item_id, "url": url, "slug": a.slug or slug_of(url)}
    _posted_dup, pending_dup = check_duplicates(shelf, probe)
    if pending_dup and not a.allow_dup:
        ids = " / ".join(f"{i['id'][:6]}（{i.get('status')}・予定{i.get('scheduled_date')}）" for i in pending_dup)
        sys.exit(f"同じ記事「{probe['slug']}」の投稿が棚にあるため登録しません: {ids}（重ねるなら --allow-dup）")
    item = {
        "id": item_id, "kind": a.kind, "channel": a.channel or "auto", "source": a.source,
        "text": text, "slug": probe["slug"], "scheduled_date": a.scheduled_date or "未定",
        "created_at": now_jst().isoformat(timespec="seconds"), "note": a.note or "", "url": url,
        "status": "draft", "scheduled_time": str(section("schedule").get("post_time") or "07:00"),
    }
    set_x_length(item)
    shelf["items"].append(item)
    save_shelf(shelf)
    ledger_append(item_id)
    warn_schedule_conflict(shelf, item)
    warn_posted_duplicate(shelf, item)
    warn_x_ledger(item)
    print(f"登録: id={item_id} {a.kind}/{a.source} 予定={item['scheduled_date']}（下書き。approve で予定に入る）")
    return 0


def cmd_plan(_a):
    """予定日の割当。記事の告知を先に・1日1本・今日から7日先まで。以降は「未定」。"""
    shelf = load_shelf()
    today = now_jst().date()
    horizon = today + timedelta(days=PLAN_HORIZON_DAYS)
    occupied = {i["scheduled_date"] for i in shelf["items"]
                if i.get("scheduled_date") and i["scheduled_date"] != "未定"}
    pending = sorted((i for i in shelf["items"] if i.get("scheduled_date") in (None, "", "未定")),
                     key=lambda i: (PLAN_PRIORITY.get(i["source"], 9), i["created_at"]))
    d, assigned = today, 0
    for item in pending:
        while d.isoformat() in occupied and d <= horizon:
            d += timedelta(days=1)
        if d > horizon:
            break
        item["scheduled_date"] = d.isoformat()
        occupied.add(d.isoformat())
        assigned += 1
    save_shelf(shelf)
    rest = sum(1 for i in shelf["items"] if i.get("scheduled_date") == "未定")
    print(f"割当 {assigned}件（未定のまま {rest}件・対象期間 {today}〜{horizon}）")
    return 0


def _find(shelf, id_prefix):
    hits = [i for i in shelf["items"] if i["id"].startswith(id_prefix)]
    if len(hits) != 1:
        sys.exit(f"エラー: id '{id_prefix}' の該当が{len(hits)}件（一意になるまで指定）")
    return hits[0]


def _set_status(a, status, msg):
    shelf = load_shelf()
    item = _find(shelf, a.id)
    item["status"] = status
    if status == "approved":
        warn_x_ledger(item)
    if getattr(a, "note", None) is not None:
        item["note"] = a.note
    save_shelf(shelf)
    print(f"{msg}: {item['id']} {item['text'].splitlines()[0][:40]}")
    return 0


def cmd_approve(a):
    return _set_status(a, "approved", "approved")


def cmd_unapprove(a):
    return _set_status(a, "draft", "draft（承認を取り消し）")


def cmd_skip(a):
    return _set_status(a, "skipped", "skipped")


def cmd_supersede(a):
    return _set_status(a, "superseded", "superseded")


def cmd_posted(a):
    """手で出した投稿の記帳。ふだんは翌朝の照合（own_posts.py）が記帳するので、急ぐときだけ使う。"""
    shelf = load_shelf()
    item = _find(shelf, a.id)
    item["status"] = "posted"
    item["posted_at"] = a.posted_at or now_jst().isoformat(timespec="seconds")
    if a.x_url is not None:
        item["x_url"] = a.x_url
    if "（手動投稿）" not in item.get("note", ""):
        item["note"] = (item.get("note", "") + " （手動投稿）").strip()
    save_shelf(shelf)
    print(f"posted（手動）: {item['id']} posted_at={item['posted_at']} x_url={item.get('x_url') or '未記入'}")
    return 0


def cmd_update(a):
    """本文・予定日・note・URL の差し替え（本文は文字数を数え直す）。"""
    shelf = load_shelf()
    item = _find(shelf, a.id)
    if a.text_file:
        text, url = split_trailing_url(read_text_arg(a.text_file), "")
        item["text"] = text
        if url:
            item["url"] = url
        set_x_length(item)
    if a.scheduled_date:
        item["scheduled_date"] = a.scheduled_date
    if a.note is not None:
        item["note"] = a.note
    if a.url is not None:
        item["url"] = a.url
        if a.url:
            item["slug"] = slug_of(a.url)
        set_x_length(item)
    if a.slug is not None:
        item["slug"] = a.slug
    save_shelf(shelf)
    warn_schedule_conflict(shelf, item)
    warn_posted_duplicate(shelf, item)
    warn_x_ledger(item)
    print(f"updated: {item['id']}")
    return 0


def cmd_list(_a):
    shelf = load_shelf()
    for i in sorted(shelf["items"], key=lambda x: (x.get("scheduled_date") or "未定")):
        over = " 文字数超過" if i.get("x_over") else ""
        print(f"{i.get('scheduled_date', '未定'):>10}  [{i.get('status', 'draft'):>9}]  "
              f"{i['kind']}/{i.get('channel', 'auto')}  id={i['id']}{over}")
        print(f"            {i['text'].splitlines()[0][:50]}")
    print(f"\n計 {len(shelf['items'])}件")
    return 0


def main():
    ap = argparse.ArgumentParser(description="棚（data/shelf.json）の管理")
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("add", help="投稿を1件登録（下書き）")
    c.add_argument("--kind", required=True, choices=KINDS)
    c.add_argument("--channel", choices=CHANNELS, default="auto", help="auto=定時実行が投稿／manual=自分で出す")
    c.add_argument("--source", required=True, choices=SOURCES)
    c.add_argument("--key", required=True, help="id の元になる安定キー（source の中で一意）")
    c.add_argument("--text-file", required=True, help="本文ファイル（- で標準入力）")
    c.add_argument("--note", help="メモ")
    c.add_argument("--url", help="投稿に添付するURL（コピー時に本文＋改行＋URLになる）")
    c.add_argument("--scheduled-date", help="YYYY-MM-DD。省略時は「未定」（plan で割当）")
    c.add_argument("--slug", help="記事の識別子（URLなしでも記事との対応を保つ）")
    c.add_argument("--allow-dup", action="store_true", help="同じ記事の未投稿が棚にあっても登録する")
    c.set_defaults(func=cmd_add)

    sub.add_parser("plan", help="予定日の割当（1日1本・7日先まで）").set_defaults(func=cmd_plan)
    sub.add_parser("list", help="棚の一覧").set_defaults(func=cmd_list)

    for name, func, help_ in (("approve", cmd_approve, "承認（予定に入る）"),
                              ("unapprove", cmd_unapprove, "承認の取り消し（下書きへ戻す）"),
                              ("skip", cmd_skip, "見送り（消さずに残す）"),
                              ("supersede", cmd_supersede, "差し替えで不要になった枠の記帳（消さずに残す）")):
        c = sub.add_parser(name, help=help_)
        c.add_argument("id", help="id（前方一致可）")
        c.add_argument("--note", help="メモ（上書き）")
        c.set_defaults(func=func)

    c = sub.add_parser("posted", help="手で出した投稿の記帳")
    c.add_argument("id")
    c.add_argument("--x-url")
    c.add_argument("--posted-at", help="投稿日時（ISO形式。省略時は現在時刻）")
    c.set_defaults(func=cmd_posted)

    c = sub.add_parser("update", help="本文・予定日・note・URL の差し替え")
    c.add_argument("id")
    c.add_argument("--text-file")
    c.add_argument("--scheduled-date")
    c.add_argument("--note")
    c.add_argument("--url")
    c.add_argument("--slug")
    c.set_defaults(func=cmd_update)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
