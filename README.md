# 愛玩動物飼養管理士2級 問題演習

愛玩動物飼養管理士 2 級の 141 問を、スマホで 5 択を解きながら学ぶための個人用アプリです。

- **勉強モード**: 1 問ずつ解き、解答のたびに 5 つの選択肢すべての解説を読む
- **テストモード**: 10 問をまとめて解き、最後に採点して 10 問分の解説を読む
- 解答の記録はブラウザの中にだけ保存します（サーバーには送りません）。記録を使って「間違えた問だけ」を出題できます
- 公開ページ: https://okome53.github.io/pet-exam-quiz/ （検索エンジンには載せない設定です）

## 出典

問題文と選択肢は、ankimaker の問題集（作成者: 柚姫w）に由来します。

- https://ankimaker.com/workbooks/f3582e60-ded2-4fc7-a14a-547711df6c85

不正解の選択肢の解説と、正解の選択肢の根拠は、このアプリのために別に作成したものです。内容の正確さは保証しません。試験の公式の情報は、日本愛玩動物協会の案内で確かめてください。

## 構成

```
docs/        公開するページ（GitHub Pages が main ブランチの /docs から配信する。ビルドの手順なし）
  index.html  app.js  app.css
  core.js     画面・保存・時刻・乱数に触れない関数（テストで直接動かす）
  questions.js  問題データ（scripts/convert.py が作る）
scripts/     元の md 3 本からデータを作る変換スクリプト
data/        変換結果（questions.json）・検査の結果（convert-report.md）・確認済みの例外（order-exceptions.json）
tests/       pytest（変換と、core.js の関数を node で動かす確認）
```

外部のライブラリは使っていません（Python 標準ライブラリと素の HTML / JavaScript / CSS だけ）。

## データの作り直し方

元の md 3 本はリポジトリに入れていません。作り直すときは、手元の `source/` に次の 3 本を置いてから変換します。

- `愛玩動物飼養管理士2級_2026_不正解の解説.md`
- `愛玩動物飼養管理士2級_2026_全141問.md`
- `愛玩動物飼養管理士2級_2026_正解の裏取り結果.md`

```sh
python3 scripts/convert.py   # data/questions.json と docs/questions.js を作る
python3 -m pytest            # 変換と画面の関数を確かめる（node が必要）
```

変換は 141 問すべての形（選択肢が 5 つ・正解が 1 つ・解説が 4 つ など）を検査し、1 問でも崩れていれば何も書き出しません。結果は `data/convert-report.md` に出ます。

## 手元で開く

`file://` で開くと、ページの安全設定（CSP）でスクリプトが止まるブラウザがあります。手元では簡易サーバーで開いてください。

```sh
python3 -m http.server -d docs
```
