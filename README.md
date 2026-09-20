# haif-tools

A public set of tools that a non-engineer built with AI and uses daily; the build records are on hitori-ai-factory.com.

ひとりAIファクトリーで、ぼくが自分の運用に使っているツールを置いていく場所です。
ツールはサイトの記事と一体で公開します。記事には、そのツールを作った経緯と実測を書いています。

- サイト: https://hitori-ai-factory.com/
- ツールは `tools/<ツール名>/` に1つずつ。それぞれの README に使い方と、ぼくが詰まったところを書いています
- 記入例は架空のものです。実測は記事のほうにあります
- 動作や成果の保証はしません。自分の環境で確かめてから使ってください

## ツール一覧

| ツール | 何をするか | 一体の記事 |
|---|---|---|
| [neta-board](tools/neta-board/) | ネタ帳（Markdown 1ファイル）を読んで、ネタ帳ボード（HTML 1枚）を生成する | [AIに反対されたが、半日で作った](https://hitori-ai-factory.com/jitsuroku/built-despite-ai-objection/) |
| [code-brief](tools/code-brief/) | チャットのAI（決める役）とコードを書くAI（作る役）に、それぞれ1回貼るだけの決まり2本 | [決める役と作る役を、なぜ分けているか](https://hitori-ai-factory.com/tsukaikata/code-brief-01/) |
| [x-board-v1](tools/x-board-v1/) | X投稿の下書きをカードで並べ、本文をコピーしてXに貼り、投稿したら「投稿済みにする」で送る（HTML 1枚・保存はブラウザの中だけ） | [下書きの置き場──X投稿の管理を、HTML1枚で作った日](https://hitori-ai-factory.com/rensai/shitagaki-no-okiba/) |
| [x-autopost-board](tools/x-autopost-board/) | 承認したX投稿を予定日の朝に出し、前日までの投稿の記録・ボード（HTML 1枚）の更新・毎朝の実行の記録までを、GitHub の非公開リポジトリの定時実行で回す（X API を使う） | [X投稿を自動化した──HTML1枚から37日](https://hitori-ai-factory.com/rensai/x-autopost-37days/) |

## 共通の前提

- Python 3 の標準ライブラリだけ、または HTML 1枚で動くように作っています。追加のインストールは不要です
- ツールは自分のPCの中で動きます。入力したファイルをどこにも送信しません。例外は x-autopost-board で、GitHub Actions の上で動き、X API に接続します

## 問い合わせ

不具合や質問は Issue に書いてください。すべてに返せるとは限りませんが、読んでいます。

## ライセンス

MIT License（[LICENSE](LICENSE)）
