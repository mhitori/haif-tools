"""common ── 設定の読み込み・時刻・ファイルの置き場・支出カウンタ（X自動投稿ボード一式）。

設定は config.yaml 1ファイル（置き場は環境変数 X_BOARD_CONFIG で変えられる）。
アカウント名だけは環境変数 X_HANDLE でも渡せる（リポジトリに書きたくない場合）。
外部ライブラリは使わない（標準ライブラリのみ）。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("X_BOARD_CONFIG") or (KIT_ROOT / "config.yaml"))

DEFAULT_PATHS = {
    "shelf": "data/shelf.json",
    "shelf_registered": "data/shelf_registered.jsonl",
    "post_log": "data/post_log.jsonl",
    "own_posts": "data/own_posts.json",
    "profile": "data/profile_metrics.jsonl",
    "receipt": "data/run_receipt.jsonl",
    "spend": "data/spend.json",
    "work": "data/work",
    "board": "board/index.html",
}


def parse_yaml_min(text):
    """config.yaml が使う範囲だけの最小YAMLパーサ。

    対応: 2スペースインデントのマッピング／リスト、二重引用符の文字列、整数。
    全行コメント（# 始まり）と空行は無視。インラインコメントは非対応（コメントは行頭に置く）。
    """
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, stripped))

    pos = [0]

    def parse_scalar(token):
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            body = token[1:-1]
            return body.replace('\\"', '"').replace("\\\\", "\\")
        if re.fullmatch(r"-?[0-9]+", token):
            return int(token)
        return token

    def parse_block(indent):
        if pos[0] >= len(lines):
            return None
        _, content = lines[pos[0]]
        if content.startswith("- "):
            return parse_list(lines[pos[0]][0])
        return parse_map(lines[pos[0]][0])

    def parse_map(indent):
        result = {}
        while pos[0] < len(lines):
            i, content = lines[pos[0]]
            if i < indent or content.startswith("- "):
                break
            if i > indent:
                raise ValueError(f"不正なインデント: {content}")
            key, _, rest = content.partition(":")
            key, rest = key.strip(), rest.strip()
            pos[0] += 1
            if rest:
                result[key] = parse_scalar(rest)
            elif pos[0] < len(lines) and lines[pos[0]][0] > indent:
                result[key] = parse_block(lines[pos[0]][0])
            else:
                result[key] = None
        return result

    def parse_list(indent):
        result = []
        while pos[0] < len(lines):
            i, content = lines[pos[0]]
            if i != indent or not content.startswith("- "):
                break
            item = content[2:].strip()
            if not item.startswith('"') and re.match(r"^[\w-]+\s*:", item):
                lines[pos[0]] = (indent + 2, item)
                result.append(parse_map(indent + 2))
            else:
                pos[0] += 1
                result.append(parse_scalar(item))
        return result

    return parse_block(0) or {}


_config_cache = None


def load_config():
    global _config_cache
    if _config_cache is None:
        if not CONFIG_PATH.exists():
            sys.exit(f"エラー: 設定ファイルがありません（{CONFIG_PATH}）")
        _config_cache = parse_yaml_min(CONFIG_PATH.read_text(encoding="utf-8"))
    return _config_cache


def section(name):
    return load_config().get(name) or {}


def path(key):
    """ファイルの置き場（config.yaml の paths。無ければ既定値。相対パスはこのフォルダ基準）。"""
    p = Path(str(section("paths").get(key) or DEFAULT_PATHS[key]))
    return p if p.is_absolute() else KIT_ROOT / p


def handle():
    """X のアカウント名（@なし）。環境変数 X_HANDLE が優先。"""
    h = (os.environ.get("X_HANDLE") or str(section("account").get("handle") or "")).strip().lstrip("@")
    return h


# --- 時刻（config.yaml の schedule.utc_offset_hours。既定 +9） ---

TZ = timezone(timedelta(hours=int(section("schedule").get("utc_offset_hours", 9) or 0)))
JST = TZ   # 照合・取り込みの関数が使う名前（中身は設定の時間帯）


def now_jst():
    """設定の時間帯での現在時刻（関数名は照合の処理と共通のまま）。"""
    return datetime.now(TZ)


# --- 支出カウンタ（live のときだけ加算） ---

def _spend_cfg():
    return section("spend")


def spend_status(config=None):
    """(今月の使用額, 上限, 月キー) を返す。"""
    limit = float(_spend_cfg().get("monthly_limit_usd", 20) or 0)
    month = now_jst().strftime("%Y-%m")
    data = {}
    if path("spend").exists():
        data = json.loads(path("spend").read_text(encoding="utf-8"))
    return float(data.get(month, 0)), limit, month


def spend_check_or_exit(config, estimated_usd, what):
    """加算せず事前チェックのみ。上限超過の見込みなら止まる。"""
    used, limit, month = spend_status(config)
    if used + estimated_usd > limit:
        sys.exit(f"エラー: 月次支出上限 ${limit} に達するため停止 "
                 f"（{month} 使用済み ${used:.2f} + {what} 見込み ${estimated_usd:.2f}）")


def spend_add(config, usd):
    used, _, month = spend_status(config)
    data = {}
    if path("spend").exists():
        data = json.loads(path("spend").read_text(encoding="utf-8"))
    data[month] = round(used + usd, 4)
    path("spend").parent.mkdir(parents=True, exist_ok=True)
    path("spend").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def cost(key, default):
    return float(_spend_cfg().get(key, default) or default)


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
