# 本番確認

Checks each published page after a push: it opens, its main content matches your local build, it has OG tags, its largest image is small enough, and six phone-width (390px) checks pass. Uses Python 3 and Playwright.

push のあとに、公開中のページを1ページずつ確かめます。見るのは、ページが開けるか（手元の出力を渡せば、本文が同じになったかも）・カードに使う3つの値（題名・説明・画像）があるか・いちばん大きい画像の大きさ・スマホの幅（390px）での6項目です。1つでも外れたら、終了コード 1 で止まります。直すのは人です。

## 入れるもの
- サイトの URL（`--site`・例 `https://example.com`）
- 任意: 確かめるページ（`--urls`・パスか、`--site` と同じドメインの完全な URL）。渡さないときは、サイトの `sitemap.xml` に書かれた全部のページ（sitemap の索引なら1段だけたどる）
- 任意: 手元の出力（`--dist`・build したフォルダ）。渡すと、本文が手元と同じになったかも見る
- 任意: 画像1枚の上限（`--img-limit-kb`・既定 300）
- 任意: 上に固定したヘッダーのセレクタ（`--header`・例 `.site-header`）。渡したときだけ、見出しへの重なりを見る
- 任意: 結果を1行追記するファイル（`--log`・JSON の行）

## 見るもの（ページごと）

| 列 | 見るもの | ○ の条件 |
|---|---|---|
| a 開けるか | ページの応答。`--dist` を渡したときは `<main>` の中も | 200 で開ける。`--dist` のときは、`<main>` の中が手元の同じページと同じ。そろわなければ 30秒おきに最大3分待ち、それでもそろわなければ「未」 |
| b OG | `og:title`・`og:description`・`og:image` の3つの meta と、`og:image` の URL | 3つがあり、`og:image` が 200 で開ける。meta の属性の順は問わない |
| c 画像 | スマホの幅でページを最後までスクロールして、ブラウザが img から読んだ画像 | いちばん大きい1枚が上限以下。合計は値だけ出す |
| e 390px | スマホの幅（390px）での6項目（下の表） | 6項目が全部 0 |

a が「未」のページは、b・c・e を見ずに「未」と出します。

390px の6項目（判定は同じフォルダの `check_390.js`）:

| 項目 | 数えるもの |
|---|---|
| 横スクロール | 文書の幅が画面の幅より広い |
| 16px 未満の文字 | `<main>` の中で、文字の大きさが 16px 未満の要素 |
| 幅より広い要素 | 表・図・画像・コードの枠が画面の右端を越える（横スクロールの枠の中は除く） |
| ヘッダーが見出しに重なる | 見出しや id の付いた要素へ飛んだとき、ヘッダーの下端が要素の上端より下に来る（`--header` を渡したときだけ） |
| 押す部分が 44px 未満 | リンク・ボタンの高さか幅が 44px 未満（文の流れの中のリンクは除く） |
| 明度差 4.5 未満 | 文字の色と、その下の背景の色のコントラスト比が 4.5 未満 |

## 出るもの
1. 表: ページごとに「a 開けるか／b OG／c 画像／e 390px」を ○・×・未で
2. 390px の6項目の数の表（ページごと）
3. 詳細: × と未の中身（未なら、応答の番号か、本文の違いの最初の場所）と、c の値（枚数・合計・最大の1枚）
4. 最後の1行: 「Nページ 全部 ○」か「Nページのうち Nページで止まった（未 N・× N）」と、確かめた時刻と Chromium の版
5. 終了コード: 全部 ○ なら 0、× か未が1つでもあれば 1。確かめられなかったとき（Playwright か Chromium が無い・sitemap.xml を読めない・`--site` と違うドメインの URL を渡した・`--dist` のフォルダが無いなど）は、1行で知らせて 2

## 手順（3つ）
1. Playwright と Chromium を入れる（下の「用意するもの」）
2. push して、公開の仕組み（Cloudflare Pages など）が build を終えるころに走らせる
   `python3 prod_check.py --site https://example.com --dist ./public --header .site-header`
   （確かめるページを絞るときは `--urls /posts/hello/ /about/`）
3. 止まったら、詳細を見て直す。直して push したら、止まったページだけをもう一度確かめる
   `python3 prod_check.py --site https://example.com --urls /posts/hello/ --dist ./public --header .site-header`

本番のページは、URL の後ろにキャッシュよけの問い合わせ文字列（`?pc=<時刻>`）を付けて読みます。

## 架空のサイトで試す

`example_site/` は、2ページだけの架空のサイト「まめ工房の記録」です。手元で配って、通る回と止まる回を試せます。

```
cd example_site
python3 -m http.server 8000 --bind 127.0.0.1
# 別の端末で（prod_check.py のあるフォルダから）
python3 prod_check.py --site http://127.0.0.1:8000 --dist example_site --header .site-header   # 通る（終了コード 0）
python3 prod_check.py --site http://127.0.0.1:8000 --img-limit-kb 0                          # c で止まる（終了コード 1）
```

## AI に守らせる決まりの1行

AI に公開物を push させるときは、AI への指示（CLAUDE.md など）に次の1行を入れておきます。

```
サイトに push したら、prod_check.py で公開中のページを確かめる。終了コードが 0 でなければ（1 も 2 も）、出力を見せて止まる（直すかどうかは人が決める）。
```

## 用意するもの
- Python 3 と Playwright（`pip install playwright`）
- Chromium（`playwright install chromium`）
- ネットにつながっていること（確かめるサイトのページを読む。読むだけで、手元のファイルは送らない）

## できないこと
- 「未」は、build の失敗と遅れを見分けない。待つのは 30秒おきに最大3分
- 見るのは、渡した URL か sitemap.xml のページだけ
- 手元の出力と比べるのは `<main>` の中だけ。`<main>` の無いページは、開けるか（200）だけを見る
- 比べる前に、@ を含む語とメール保護のリンクを外すので、そこの違いは見ない
- 画像は img から読んだものだけ。CSS の背景画像は数えない。見た目と、OG のカードの出方は見ない
- スマホの幅は 390px だけ。6項目の値（16px・44px・4.5）は決まっていて変えられない。ヘッダーの重なりは、ヘッダーを指定したときだけ見る
- 出したくない語は見ない（push の前に、[出したくない語スキャン](../word-scan/) を使う）
- 外れた所を直さない。push を止める設定は無い（手で走らせる）
- 公開中のサイトで確かめたのは、Cloudflare Pages で出しているぼくのサイト（hitori-ai-factory.com）だけ。ログインが要るページと、JS で本文を作るページは確かめていない
- 確かめた環境は macOS（Python 3.9.6・Playwright 1.60.0・Chromium 148）だけ
- ネットにつながっている必要がある

## 内部版から外したもの

ぼくが自分のサイトで使っている内部版から、次を外しました。

- 出したくない語の確かめ（内部版の d。検査語のファイルを公開すると、隠している語の一覧そのものになるため）
- 原稿のファイルから公開の URL を導く対応と、直前の push の範囲から確かめるページを決める動き（ぼくのサイトの作りに固定していたため。公開版は URL の一覧か sitemap.xml）
- 朝の自動実行に結果を渡す仕組み（記録の書き先と取り込み）
- ドメイン・画像の上限・ヘッダーとロゴの名前の固定（公開版は引数で受ける。ロゴを数えない扱いは外した）

## ファイル
- prod_check.py     本体
- check_390.js      スマホの幅（390px）の6項目の判定
- example_site/     架空のサイト（2ページ・試す用）
- README.md         この説明

## 一体の記事
https://hitori-ai-factory.com/jitsuroku/prod-check-seven-pages/

## 提供条件
MIT License。動作や成果を保証するものではありません。

作: ひとりAIファクトリー hitori-ai-factory.com
