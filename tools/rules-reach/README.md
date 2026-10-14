# 決まりの届き方の実測キット

A Markdown kit for checking which rules actually reach an AI coding assistant: ask it to list the rules it follows without opening any file, then compare that list line by line with your rules file. No program is included; the line-by-line comparison is done by hand (in the example, an AI agent compared the lines using only the kit files, and another AI agent reviewed it).

AI に届いている決まりを、ファイルを開かずに書き出してもらい、元の決まりのファイル（AGENTS.md や CLAUDE.md）と1行ずつ照らすための型です。Markdown のファイル4つと記入例だけで、動くプログラムはありません。照らしは1行ずつ手で行います（記入例の照らしは、2つの版と行の一覧、型の元の案、答えの全文だけを渡した AI の係に行わせ、別の AI の係が見直したものです）。

## 何を測るか

- 決まりのファイルの行が、書き出しにどう出たか（そのまま／言い換え／欠け／取り違え）
- 決まりのファイルの外から届いたもの（実行環境の指示・個人設定・自動のメモなど）の数と要点
- 場面（手元・クラウド側・サブエージェント）ごとに、何が届いて何が届かなかったか

## ファイル

- question.md          セッションの最初に貼る問い（2問と、任意の3問目）
- record_template.md   1回の書き出しにつき1枚書く記録の型
- counting_rules.md    分母の数え方と、行ごとの判定の線（11項目）
- example/kakeibo-a_AGENTS.md   架空の AGENTS.md（12行の版）
- example/kakeibo-b_AGENTS.md   架空の AGENTS.md（40行の版。12行の版の12行を一字も変えずに含む）
- example/record_2026-10-14.md  上の2つの版で1回ずつ聞いた答えの全文と、その照らしの記入例
- README.md            この説明

## 手順

1. 新しいセッションの最初の発言として、question.md の問いを貼る。前に挨拶や説明を打たない
2. 答えを、決まりのファイルを開く前に写して固定する。あとから直さない・要約しない
3. counting_rules.md で分母を数える（照らしの前に、長い行を句に分けておく）
4. 1行ずつ照らし、record_template.md の型に書く。型の線で決められなかった行は「迷った所」に書く

## できないこと

- 届いた決まりを守ったかどうか。書き出しで分かるのは、届いたかどうかまで
- 書き出しに出ない届き方。書き出しに無い行が、届いていないのか、書き出しで省かれたのかは見分けられない
- 言い換えの線。「言い回しの違い」と「要素を省いた」の境目は人が決める。counting_rules.md の線は、配布元が決めた線
- Claude Code の InstructionsLoaded のフック（決まりのファイルを読み込んだときに知らせる仕組み）は、AGENTS.md を直接読ませる形では動かないと、公式の説明の表に書いてある（2026年10月7日に読んだ範囲）。このキットはフックを使わない
- 照らすプログラムは入っていない
- 確かめたのは Claude のアプリの Code タブの手元・新しいセッションだけ。クラウド側とサブエージェントは、前の回に形の違う問いで測った記録だけで、このキットの形では確かめていない
- Claude Code 以外の AI ツールでは試していない

## 用意するもの

- 決まりのファイルを読み込む AI ツール（このキットを確かめたのは Claude Code）
- 答えを写して置くファイル

## 確かめた結果（2026-10-14）

架空の AGENTS.md の12行の版と40行の版（example/）を空のフォルダに1つずつ置き、Claude のアプリの Code タブの新しいセッションで、question.md の2問を1回ずつ聞きました。照らしは、AI の係に、2つの版の全文と行の一覧、キットの数え方と記録の型の元の案、答えの全文だけを渡して行わせ、別の AI の係が見直しました。

- 12行の版は そのまま11・言い換え0・欠け1、40行の版は そのまま36・言い換え4・欠け0。共通の12行で判定が変わったのはプロジェクトの説明の1行だけ
- 照らした行は52行（12行の版12・40行の版40）。案の線だけでは決められなかった所が9つありました。行の判定の線が5つ（説明の行が指示の形で出た・行の中身が見出しにしか無い・句の述語が消えた・修飾の語だけが消えた・句は残って条件か句の中の語が消えた）、数え方が4つ（問いから来た項目・答えの最後の注・自動のメモの名前だけが出た・決まりの行に近い外の項目）です
- 9つとも、counting_rules.md と record_template.md に入れました。counting_rules.md の8つには「（2026-10-14 に足した）」の印を付け、record_template.md は合計の行と注の欄を直しました
- 言い換えの数は、この線で変わりました。40行の版の言い換えは、counting_rules.md の線では4行です。説明の行が指示の形で出たのを言い回しの違いと見ると3行、修飾の語だけが消えた2行も言い換えに数えると6行になります
- 迷った所は example/ の照らしの記入例の最後にあります
- 版ごとに1回だけの実測です。ほかの環境・ほかの AI では確かめていません

## 一体の記事

https://hitori-ai-factory.com/jitsuroku/rules-reach-12-40/

## 提供条件

MIT License。動作や成果を保証するものではありません。

作: ひとりAIファクトリー hitori-ai-factory.com
