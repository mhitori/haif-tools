#!/usr/bin/env python3
"""run_local ── 定時実行の1周を、手元で試運転する（X API を呼ばない・投稿しない）。

工程は定時実行（.github/workflows/x_board_daily.yml）と同じ順番:
  1. 取り込み  own_posts.py --offline（API を呼ばず、手元の台帳で照合だけ行う）
  2. 投稿      post.py --dry-run（出す予定を記録するだけ）
  3. ボード更新 board.py
  4. 受領票    receipt.py（前の工程が失敗しても書く）
  5. ボード更新 board.py（受領票を「今朝の実行」行に出すため）

使い方:
    python3 scripts/run_local.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import now_jst   # noqa: E402


def run(name, args):
    print(f"--- {name}: {' '.join(args)}")
    r = subprocess.run([sys.executable, str(HERE / args[0])] + args[1:], text=True)
    return "success" if r.returncode == 0 else "failure"


def main():
    started = now_jst().strftime("%Y-%m-%dT%H:%M:%S%z")
    steps = {}
    steps["own_posts"] = run("取り込み", ["own_posts.py", "--offline"])
    steps["post"] = run("投稿", ["post.py", "--dry-run"]) if steps["own_posts"] == "success" else "skipped"
    steps["board"] = run("ボード更新", ["board.py"])
    run("受領票", ["receipt.py", "--event", "local", "--run-number", "local", "--started-at", started]
        + [f"--step={k}={v}" for k, v in steps.items()])
    run("ボード更新（受領票のあと）", ["board.py"])
    ok = all(v == "success" for v in steps.values())
    print(f"=== 試運転 {'成功' if ok else '失敗あり'}: {steps}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
