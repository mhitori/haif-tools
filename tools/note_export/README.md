# note転載キット

サイトの記事の md を1本入れると、note に貼る直前までの5つを出します。貼るのは手です。

## 入れるもの
- 記事の md 1本（front matter 付き・title は必須。表・図・実物・引用を含んでよい）

## 出るもの（5つ）
1. note_body.txt  note に貼る本文。表と図の位置には札「[画像N: …]」、引用とコードの枠は「実物:」＋中身の文字
2. table_NN.png   本文の表を画像にしたもの（幅1200・列幅と折り返しを調整）
3. fig_NN.<ext>   本文の図・画面の写し（貼る順に番号）
4. header.png     note の見出し画像（1280×670・題名＋URL のカード型。ロゴは任意）
5. checklist.md   貼る手順書（札の位置と画像・リンクにする箇所・タグの候補・書く人が埋める欄）

## 手順（3つ）
1. md を渡す
   `python3 note_export.py 記事.md --font-dir ./fonts --site-url https://example.com --url https://example.com/posts/slug/`
2. 出た checklist.md の順に、本文と画像を note に貼る
3. 「書く人が埋める」欄（note 版の題名・言い換え）を埋める

## 用意するもの
- Python 3 と Pillow（`pip install pillow`）
- 書体 Noto Sans JP の Regular と Bold（SIL Open Font License）。Google Fonts などから入手し、NotoSansJP-Regular.otf・NotoSansJP-Bold.otf を1つのフォルダに置いて `--font-dir` で指定する
- 図が「/」で始まるパスで書かれている記事は、その基点のフォルダを `--assets-root` で指定する
- 任意: 検査語のファイル（1行1語・`re:` で始まる行は正規表現）を `--words` で渡すと、本文・表・見出し画像に当たったときに出力せずに止まる。外に出したくない語を入れておく
- 任意: 見出し画像に置くロゴの画像（`--logo`）

## できないこと
- note の表と引用の枠には貼れない（表は画像、引用は文字の写しになる）
- 題名と本文の言い換えはしない
- note への投稿はしない

## ファイル
- note_export.py          本体
- checklist_template.md   貼る手順書の雛形（本体が記事ごとに書き出すものと同じ形）
- README.md               この説明

## 一体の記事
https://hitori-ai-factory.com/jitsuroku/note-kit/

## 提供条件
MIT License。動作や成果を保証するものではありません。

作: ひとりAIファクトリー hitori-ai-factory.com
