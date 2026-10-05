#!/usr/bin/env python3
"""出したくない語スキャン（word_scan）── git のリポジトリを push する前に、出したくない語が入っていないかを検査する。

検査語は --words で渡すファイル（1行1語）から読む。対象は2つ:
  1. push する差分: --range の範囲のコミットごとに、見出しと本文・著者とコミッターの名前とアドレス・
     足した行（+ の行）・新しいファイルの名前・名前を変えた先
  2. 今の中身: git ls-files の全ファイルのうち、UTF-8 で読めるものの全部の行（--tree のとき）
差分の前後に写る前からある行と、消した行は数えない。
埋め込み画像のデータ（data:image で始まる文字列）は検査の対象から外す。
結果は「検査語／ヒット数／実物（最大5件・前後30字）」の表で出す。メールアドレスとホームフォルダ名は値を伏せる。

検査語のファイルの書き方（1行1つ。# で始まる行と空行は飛ばす）:
    語                       そのまま部分一致（大文字と小文字を区別する）
    i:語                     大文字と小文字を区別しない部分一致
    re:式                    正規表現（Python の re）
    @EMAIL                   メールアドレスの形（allow-email にあるもの以外）。値は伏せる
    @HOME                    実行した PC のホームフォルダ名。値は伏せる
    allow-email: アドレス    @EMAIL の検査から外すアドレス（公開してよい問い合わせ先など）
    allow-line: ファイル名の一部 | 行に含まれる文字列 | 理由
                             ファイル名と行の両方が合う行だけ、全部の検査語から外す

使い方:
    python3 word_scan.py --repo ~/projects/my-tools --words my_words.txt                # 差分（origin/main..HEAD）だけ
      origin/main が無いとき（まだ push したことのないリポジトリ）は、HEAD までの全部のコミットを差分として見る
    python3 word_scan.py --repo ~/projects/my-tools --words my_words.txt --tree         # 差分＋今の中身
    python3 word_scan.py --repo ~/projects/my-tools --words my_words.txt --known もぐら町
      --known 語: その語は件数だけ出す（直すまでの既知の件数として、合計と終了コードに数えない）
終了コード: ヒットが1件でもあれば 1、無ければ 0（--known の語は数えない）。検査できなかったときは 2
作: ひとりAIファクトリー hitori-ai-factory.com（MIT License）
"""

import argparse
import collections
import os
import re
import subprocess
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+\-\[\]]+@[\w-]+(?:\.[\w-]+)+")
# 埋め込み画像のデータ（data:image で始まる文字列）は検査の対象から外す。
# base64 の文字の並びが、たまたま検査語の形（英字1字＋数字など）に当たるため
DATA_IMAGE_RE = re.compile(r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/=]+")


def load_words(path):
    """[(表示名, 判定の式, 値を伏せるか)] と許可アドレスの集合、行の許可の一覧を返す。"""
    terms, allow, allow_lines = [], set(), []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("allow-email:"):
            allow.add(line.split(":", 1)[1].strip())
        elif line.startswith("allow-line:"):
            # allow-line: <ファイル名の一部> | <行に含まれる文字列> | <理由>
            parts = [x.strip() for x in line.split(":", 1)[1].split("|")]
            if len(parts) >= 2:
                allow_lines.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
        elif line == "@EMAIL":
            terms.append(("メールアドレス", None, True))
        elif line == "@HOME":
            terms.append(("ホームフォルダ名", re.compile(re.escape(Path.home().name)), True))
        elif line.startswith("re:"):
            terms.append((line, re.compile(line[3:]), False))
        elif line.startswith("i:"):
            terms.append((line[2:], re.compile(re.escape(line[2:]), re.I), False))
        else:
            terms.append((line, re.compile(re.escape(line)), False))
    return terms, allow, allow_lines


def is_allowed_line(loc, text, allow_lines):
    """行の許可に当たる行か（ファイル名の一部と行の文字列の両方が一致）。"""
    body = text[1:] if text[:1] in "+-" else text   # 差分の先頭記号は外して見る
    return any(path_part in loc and needle in body for path_part, needle, _ in allow_lines)


def scan(lines, terms, allow, allow_lines=()):
    """lines: [(場所, 行)] → {表示名: [(場所, 実物)]}"""
    out = collections.OrderedDict((name, []) for name, _, _ in terms)
    for loc, text in lines:
        if is_allowed_line(loc, text, allow_lines):
            continue
        text = DATA_IMAGE_RE.sub("data:image（埋め込み画像のデータ・検査の対象外）", text)
        for name, rx, masked in terms:
            matches = ([m for m in EMAIL_RE.finditer(text) if m.group(0) not in allow] if rx is None
                       else list(rx.finditer(text)))
            for m in matches:
                snip = "（値は伏せる）" if masked else text[max(0, m.start() - 30):m.end() + 30].strip()
                out[name].append((loc, snip))
    return out


def added_lines(patch):
    """git show -p の出力から、見出し・本文と、足した行・新しいファイルの名前だけを [(場所, 行)] で返す。"""
    cur, out, in_diff, new_file = "（ヘッダ・メッセージ）", [], False, False
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            cur, in_diff, new_file = line.split(" b/")[-1], True, False
            continue
        if not in_diff:
            out.append((cur, line))
        elif line.startswith("--- "):
            new_file = line == "--- /dev/null"
        elif line.startswith("+++ "):
            if new_file:
                out.append((cur, line[4:]))   # 新しいファイルの名前も見る
        elif line.startswith(("rename to ", "copy to ")):
            out.append((cur, line))
        elif line.startswith("+"):
            out.append((cur, line))
    return out


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
                          capture_output=True, text=True, check=True).stdout


def git_ok(repo, *args):
    """git が通るか（失敗しても落とさない）。範囲やブランチがあるかを確かめるのに使う。"""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).returncode == 0


def pick_range(repo, given, tree):
    """検査する差分の範囲を返す。差分を見ないときは None、検査できないときは 2 を返す。"""
    if given:
        # 指定された範囲が無いときは、全部の検査に切り替えずに止める
        if not git_ok(repo, "log", "-1", "--format=%h", given, "--"):
            print(f"--range の範囲「{given}」が見つからないので、検査できません。名前を確かめてください")
            return 2
        return given
    if not git_ok(repo, "rev-parse", "--verify", "-q", "HEAD"):
        if not tree:
            print("コミットが1つも無いので、push する差分は検査できません。今の中身を見るときは --tree を付けてください")
            return 2
        print("コミットが1つも無いので、push する差分の検査は飛ばして、今の中身だけを検査します")
        return None
    if git_ok(repo, "rev-parse", "--verify", "-q", "origin/main"):
        return "origin/main..HEAD"
    # まだ push したことのないリポジトリ。差分を飛ばすと著者のアドレスと見出しを見ないので、全部を差分として見る
    n = git(repo, "rev-list", "--count", "HEAD").strip()
    print(f"origin/main が無いので、全部のコミット（{n}個）を push する差分として検査します。範囲を決めるときは --range を使ってください")
    return "HEAD"


def print_table(title, result, known):
    print(f"\n## {title}\n")
    print("| 検査語 | ヒット数 | 実物（最大5件） |")
    print("|---|---|---|")
    total = 0
    for name, hits in result.items():
        label = name.replace("|", "／")   # 正規表現の | で表が崩れないように
        if name in known:
            print(f"| {label} | {len(hits)} | （既知・件数のみ） |")
            continue
        total += len(hits)
        shown = "<br>".join(f"`{loc}` {snip}" for loc, snip in list(dict.fromkeys(hits))[:5]) or "—"
        print(f"| {label} | {len(hits)} | {shown.replace('|', '／')} |")
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="検査するリポジトリのフォルダ")
    ap.add_argument("--words", required=True, help="検査語のファイル（書き方は上の説明）")
    ap.add_argument("--range", default=None,
                    help="push する差分の範囲（既定 origin/main..HEAD。origin/main が無いときは HEAD までの全部）")
    ap.add_argument("--tree", action="store_true", help="今の中身（git ls-files の全ファイル）も検査する")
    ap.add_argument("--known", action="append", default=[], help="件数だけ出す既知の語（複数可）")
    a = ap.parse_args()
    repo = Path(a.repo).expanduser()
    terms, allow, allow_lines = load_words(Path(a.words).expanduser())
    total = 0

    # 検査できないときは、Python のエラーを出さずに1行で知らせて終了コード 2
    try:
        inside = git_ok(repo, "rev-parse", "--git-dir") if os.path.isdir(repo) else False
    except FileNotFoundError:
        print("git が見つからないので、検査できません。git を入れてから走らせてください")
        return 2
    if not inside:
        print(f"{a.repo} は git のリポジトリではないので、検査できません。--repo を確かめてください")
        return 2
    rng = pick_range(repo, a.range, a.tree)
    if rng == 2:
        return 2

    commits = git(repo, "log", "--format=%h", rng, "--").split() if rng else []
    for c in commits:
        patch = git(repo, "show", "--format=commit %h%nAuthor: %an <%ae>%nCommitter: %cn <%ce>%n%n%B", "-p", c)
        lines = added_lines(patch)
        total += print_table(f"コミット {c}（見出し・本文と足した行・{len(lines)}行）",
                             scan(lines, terms, allow, allow_lines), a.known)
    if rng and not commits:
        print(f"\n## push する差分: {rng} にコミットなし")

    if a.tree:
        lines = []
        files = [f for f in git(repo, "ls-files").split("\n") if f]
        for f in files:
            try:
                text = (repo / f).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
                continue
            lines += [(f"{f}:{i}", t) for i, t in enumerate(text.splitlines(), 1)]
        total += print_table(f"今の中身（{len(files)}ファイル・{len(lines)}行）",
                             scan(lines, terms, allow, allow_lines), a.known)

    print(f"\n検査語 {len(terms)}語（{Path(a.words).name}）／ヒット合計 {total}（既知 {', '.join(a.known) or 'なし'} を除く）")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
