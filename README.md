Repository to store PO Files

https://www.python.org/dev/peps/pep-0545/#repository-for-po-files

Please see [CONTRIBUTING.md](.github/CONTRIBUTING.md)

## ローカルの翻訳差分をレビューする

`scripts/po_review.py` は PO の差分を原文・変更前・変更後を並べた
Markdown に変換します。PO ファイルや Git のインデックスは変更しません。
実行には Python と `polib` が必要です（`python -m pip install polib`、
または既存の `requirements.txt` でインストールできます）。

```sh
# git diff と同じ、未ステージの変更
python scripts/po_review.py -o translation-review.md

# ステージ済み・未ステージの変更をまとめて確認
python scripts/po_review.py --base HEAD -o translation-review.md

# git diff --cached と同じ、ステージ済みの変更
python scripts/po_review.py --cached -o translation-review.md

# 対象を絞る（パスはリポジトリルートから指定）
python scripts/po_review.py --base HEAD builtins/functions.po
```

`-o` を省略すると標準出力に書き出します。生成した Markdown を開くか、
PR の説明に貼り付けてレビューできます。PR に貼り付ける場合は、
リポジトリルートに出力した資料の相対 PO リンクを適切な GitHub URL に
置き換えてください。PO リンクの行番号は比較対象の版を指します。

複数形、`msgctxt`、`fuzzy` の変更、翻訳の削除も表示します。
PO の折り返し・ヘッダー・コメント・参照行番号だけの変更は省略します。
ファイル全体の削除は一覧にまとめます。未追跡ファイルは `git diff` と同様に
含めません。原文の変更は別エントリーの追加・削除として扱い、
`#~` の obsolete エントリーは翻訳対象から除外します。

レポートは生成物なのでコミットする必要はありません。
`-o` では既存の Git 管理対象ファイルへの上書きを拒否します。
Transifex への送信・取得は行いません。
