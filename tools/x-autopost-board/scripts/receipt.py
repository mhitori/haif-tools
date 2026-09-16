#!/usr/bin/env python3
"""receipt ── 実行の受領票を data/run_receipt.jsonl に1行追記する（定時実行の最後の工程。失敗しても必ず書く）。

1行に残すもの: 実行の日時・起動のされ方（定時／手動起動／手元）・各工程の成否・取り込みの照合結果。
ボードの「今朝の実行」行は、この受領票から作る。

使い方（工程の成否は --step 名前=結果 で渡す。結果は success／failure／cancelled／skipped）:
    python3 scripts/receipt.py --event schedule --run-number 12 --started-at 2026-01-01T07:00:00+0900 \
        --step own_posts=success --step post=success --step board=success
GitHub Actions では、環境変数 RUN_ID・RUN_NUMBER・EVENT・STARTED でも渡せる。
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import now_jst, path   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="実行の受領票を1行追記する")
    ap.add_argument("--event", default=os.environ.get("EVENT", "local"))
    ap.add_argument("--run-id", default=os.environ.get("RUN_ID"))
    ap.add_argument("--run-number", default=os.environ.get("RUN_NUMBER"))
    ap.add_argument("--started-at", default=os.environ.get("STARTED"))
    ap.add_argument("--step", action="append", default=[], help="工程名=結果（複数可）")
    a = ap.parse_args()

    steps = {}
    for s in a.step:
        k, _, v = s.partition("=")
        steps[k.strip()] = v.strip() or None
    rec_path = path("work") / "own_posts_reconcile.json"
    if rec_path.exists():
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
    else:
        rec = {"posted_count": None, "skipped_count": None, "note": "照合結果なし（取り込みが照合の前で止まった）"}
    row = {"ts": now_jst().isoformat(timespec="seconds"), "workflow": "x-board-daily",
           "run_id": a.run_id, "run_number": a.run_number, "event": a.event,
           "started_at": a.started_at or now_jst().isoformat(timespec="seconds"),
           "steps": steps, "details": {"own_posts": {"reconcile": rec}}}
    p = path("receipt")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[receipt] {row['event']}・工程 {steps} → {p.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
