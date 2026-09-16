# X自動投稿ボード一式 v1.0

承認したX投稿を予定日の朝に出し、その記録を毎朝ボード（HTML 1枚）にまとめる仕組み一式です。
GitHub の非公開リポジトリに置き、Actions の定時実行で毎朝1周します。ぼくが自分の運用で毎朝動かしているものから、公開できる範囲を切り出しました。

## 何をするか

毎朝の定時実行で、次の4工程を順に回します。

1. **前日までの投稿を台帳に記録する**（`scripts/own_posts.py`）。自分の投稿を X から取り込み、手で出した投稿を棚のカードと照合して「投稿済み」と記帳します
2. **承認済みの投稿を定時に出す**（`scripts/post.py`）。棚で承認済み・投稿のしかたが自動・予定日が当日のカードを、1回に1件まで X へ投稿します
3. **ボードを更新する**（`scripts/board.py`）。棚と記録から `board/index.html` を作り直します
4. **受領票を書く**（`scripts/receipt.py`）。毎朝の実行の記録を1行、各工程の成否つきで `data/run_receipt.jsonl` に足します。前の工程が失敗しても書きます。ボードの最上部の「今朝の実行」行は、この受領票から作ります

投稿の候補を探す機能（検索・返信先の判定など）は含みません。何を出すかは自分で書いて、棚に登録します。

## 3本目「X投稿ボード v1」との違い

| | X投稿ボード v1（3本目） | X自動投稿ボード一式（4本目・この道具） |
|---|---|---|
| 置き場 | HTML 1枚。手元のファイルとして開く | 自分の GitHub 非公開リポジトリ。棚・台帳・ボードをファイルで持つ |
| 更新 | ボードの画面で書き換える | 棚は `shelf.py` で書き換え、ボードは毎朝の定時実行が作り直す（画面は表示専用） |
| 投稿 | 本文をコピーして、自分で X に貼る | 自動のカードは定時に API で投稿。手動のカードは自分で出し、翌朝の取り込みで記帳 |
| 記録 | ブラウザの中（localStorage）だけ | 投稿ログ・自分の投稿の台帳・受領票をリポジトリに残す |

3本目: [tools/x-board-v1](../x-board-v1/)

## 前提

- **X API**
  - 投稿: OAuth 1.0a の鍵4つ（API Key・API Secret・Access Token・Access Token Secret）。アプリの権限に書き込みを含めます
  - 取り込み: Bearer Token
  - **料金と必要なプランは要確認です。作者は、このコードでの請求実測を持っていません。** `config.yaml` の単価は見積もり用の値です。X の料金表を確認して書き換えてください
- **GitHub**: 非公開リポジトリと Actions・Secrets（Settings → Secrets and variables → Actions）
- **Python**: 標準ライブラリだけで動きます。手元では Python 3.9 で確認しました。それより古い版は未確認です。定時実行のワークフローは 3.12 を指定しています

## 中身

| ファイル | 役割 |
|---|---|
| `config.yaml` | 設定（このファイル1つ） |
| `scripts/shelf.py` | 棚（`data/shelf.json`）への登録・承認・見送り・一覧 |
| `scripts/own_posts.py` | 取り込みと棚の照合 |
| `scripts/post.py` | 投稿（既定は投稿しない試運転） |
| `scripts/board.py` | ボードの生成 |
| `scripts/receipt.py` | 受領票の1行 |
| `scripts/run_local.py` | 定時実行の1周を手元で試運転（X API を呼ばない・投稿しない） |
| `scripts/make_sample.py` | 試運転用の架空のデータ |
| `scripts/common.py` | 設定の読み込みなど共通部分 |
| `.github/workflows/x_board_daily.yml` | 毎朝の定時実行 |
| `sample/articles/` | 記事区画の見本（架空の記事3本） |
| `docs/rename_table.md` | 内部版から公開版にしたときの置換表 |

`data/` と `board/` は、最初の実行で作られます。

## 導入手順

### 1. 置く

1. 非公開リポジトリの直下に、このフォルダを `x-autopost-board/` という名前で置きます
2. `x-autopost-board/.github/workflows/x_board_daily.yml` を、リポジトリ直下の `.github/workflows/` に移します。フォルダを別の名前・場所にした場合は、ワークフローの `KIT_DIR` を書き換えます

### 2. config.yaml を埋める

- `account.handle`: X のアカウント名（@ なし）。リポジトリに書きたくなければ空欄のままにして、Variables に `X_HANDLE` を登録します
- `schedule.utc_offset_hours`: 日本時間なら 9
- `post.live`: 最初は `"false"` のまま（投稿せず、出す予定を記録するだけ）
- `spend`: 月の上限と単価（米ドル）。上限を超える見込みの読み取りと投稿は、実行しないで止まります
- `articles`: 記事区画を使わないなら、2つとも空欄にします。見本のままだと、架空の記事3本が区画に出ます

### 3. Secrets を5つ登録する

| 名前 | 使う工程 |
|---|---|
| `X_BEARER_TOKEN` | 取り込み |
| `X_API_KEY` | 投稿 |
| `X_API_SECRET` | 投稿 |
| `X_ACCESS_TOKEN` | 投稿 |
| `X_ACCESS_TOKEN_SECRET` | 投稿 |

鍵の値は、リポジトリのファイルに書かないでください。

### 4. 起動時刻（cron）を決める

ワークフローの `cron: "47 21 * * *"` は UTC で、日本時間の 06:47 です。毎時0分ちょうどは混みやすいので、端数の分にしています。GitHub の定時実行は、混雑時に遅れることがあります。

### 5. 最初の1周

1. Secrets を登録する前に、Actions タブから手動起動（Run workflow）で `offline` を `true` にして1周させます。X API は呼びません。`data/run_receipt.jsonl` に1行、`board/index.html` にボードができ、リポジトリにコミットされます
2. Secrets を登録したら、`offline` を `false`・`dry_run` を `true` のまま、もう1周させます。これが最初の取り込みです。初回は過去の投稿を最大1000件まで取りに行き、読み取り件数×単価を支出に足します。2回目からは前回以降の差分だけです

### 6. 投稿を始める

手元でリポジトリを最新にしてから、棚に登録して承認し、push します。

```bash
python3 x-autopost-board/scripts/shelf.py add --kind 実況 --source other --key 識別子 --text-file 本文.txt --scheduled-date 2026-01-01
python3 x-autopost-board/scripts/shelf.py approve カードのid
```

- `--channel auto`（既定）は定時実行が投稿します。`--channel manual` は予定日に自分で出し、翌朝の取り込みで「投稿済み」と記帳されます
- 予定日を過ぎた自動のカードは、投稿せず「失効」になります。失敗した投稿は自動で再送しません
- 定時実行も棚をコミットするので、登録の前に必ず pull します
- 実際に投稿を始めるときに、`post.live` を `"true"` にして push します

### 手元だけで試す

```bash
python3 scripts/make_sample.py   # 架空のデータを作る（data/ を上書きする。自分のデータがあるところでは実行しない）
python3 scripts/run_local.py     # 取り込み（API なし）→投稿（試運転）→ボード→受領票
```

できた `board/index.html` をブラウザで開きます。

## ボードを非公開で見る

ボードには、承認前の下書きも載ります。

- **手元でファイルを開く**: pull して、`x-autopost-board/board/index.html` をブラウザで開きます
- **ログインつきの置き場に出す**: ログインしないと開けない場所に、HTML 1枚として置きます。置く仕組みは、この一式に含みません

誰にも教えていないURLは、誰にも見えないURLではありません（3本目の欠陥2）。ログインなしの場所には置かないでください。リポジトリを公開にすると、棚・台帳・ボードもすべて公開されます。

## できないこと・確認していないこと

- **公開版そのものでの本番投稿は、確認していません。** 確認したのは、手元の試運転（API を呼ばない1周）です。GitHub Actions の手動起動1回（offline・dry-run）で、受領票とボードの生成とコミットまで確認しました。取り込み・照合・投稿対象の判定・送信の関数は、作者の内部版と同じコードで、内部版は毎朝動いています
- **候補探しは含みません。** 何を出すかは自分で書きます
- **Xで消した投稿は、台帳から消えません。** 取り込みは追記だけで、消したことを検知しません。消した投稿に記事のURLが入っていると、同じURLの投稿は安全装置で見送りになり、記事区画でも告知済みのままです
- **数字の投稿（フォロワー数などを入れた定型文）の生成は含みません**
- 時刻の判定は config.yaml の utc_offset_hours に従う。受領票の時刻が UTC で書かれていても、この値で当日を判定する

## 記事

- 連載第2弾 第6話（この一式の話）: [X投稿を自動化した──HTML1枚から37日](https://hitori-ai-factory.com/rensai/x-autopost-37days/)
- 連載第2弾 第1話: [下書きの置き場──X投稿の管理を、HTML1枚で作った日](https://hitori-ai-factory.com/rensai/shitagaki-no-okiba/)

## 提供条件

MIT License（リポジトリ直下の LICENSE）。このフォルダは、そのままの状態で提供します。動作や成果を保証するものではありません。
