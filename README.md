Repository to store PO Files

https://www.python.org/dev/peps/pep-0545/#repository-for-po-files

Please see [CONTRIBUTING.md](.github/CONTRIBUTING.md)

## AI Agentを使った翻訳作業

AI Agent に PO ファイルの翻訳と差分の作成を依頼し、人が Markdown でレビューします。
修正を繰り返して訳文が確定したら、Transifex に送信します。
例えば、次のように依頼して作業を始めます。

> tutorial からファイルを1つ選んで、既存訳の改善と未訳部分の翻訳をして。
> 関連する翻訳も確認して文体や用語を選び、差分は Markdown にして見せて。

1. **対象と関連する訳例を確認する。**
   対象の PO 全体と [AGENTS.md](AGENTS.md)、[用語集](scripts/python_global_japanese-ja.csv)
   を読みます。用語集は `translation_ja` を基準に、`pos` と `notes` で適用する文脈を確認します。
   関連するチュートリアルやライブラリの説明も読み、文体と訳語を選びます。
   訳例は `.tx/config` に登録された現行 PO から探し、未訳・fuzzy・obsolete のエントリーは採用しません。

2. **既存訳を改善し、未訳部分を翻訳する。**
   誤訳、訳抜け、不自然な語順や読点を見直します。
   原文、参照先、数式、コード例の計算式や出力を保持し、コード例では必要に応じてコメントを翻訳します。
   既存訳に揺れがある場合は、候補・採用した訳語・判断理由・参照した PO をレビュー資料に記載します。

3. **差分を Markdown にする。**
   `scripts/po_review.py` で、対象ファイルの原文・変更前・変更後を並べた資料を生成します。
   翻訳件数、主な修正理由、訳語の判断理由、検証結果も補足します。
   例えば `tutorial/floatingpoint.po` の差分は次のコマンドで確認できます。

   ```sh
   python scripts/po_review.py --base HEAD tutorial/floatingpoint.po -o translation-review-floatingpoint.md
   ```

4. **人がレビューし、修正を反映する。**
   Markdown の該当箇所を示して、訳語や文章の修正を依頼します。
   AI Agent は PO を修正し、その都度 Markdown を再生成します。
   再生成すると出力ファイルは上書きされるため、追記したレビュー補足は保持して戻します。
   今後も適用する訳語の決定は用語集に、語順や読点などの翻訳ルールは `AGENTS.md` に反映します。
   例えば、コマンドラインの文脈では「実引数」ではなく「引数」を使う、といった使い分けを残します。

5. **変更内容を検証する。**
   `git diff --check`、PO の構文・重複チェック、reStructuredText の検査を行います。
   参照、数式、コード、出力が保持されていることを確認し、必要に応じてコード例を実行します。
   実施した検証と、HTML ビルドなど未実施の検証をレビュー資料に記載します。
   `polib` と `sphinx-lint` は `python -m pip install polib sphinx-lint` でインストールできます。

   ```sh
   git diff --check -- tutorial/floatingpoint.po
   sphinx-lint --enable all --disable line-too-long tutorial/floatingpoint.po
   ```

6. **確認済みの日本語訳を Transifex に送信する。**
   レビュー後に「このファイルの日本語訳を tx push して」と依頼します。
   Transifex CLI と認証を設定した環境で、対象ファイルだけを送信します。
   このリポジトリの `.tx/config` は `<lang>/LC_MESSAGES/` 以下を参照するため、
   例えば `tutorial/floatingpoint.po` は一時ディレクトリの
   `ja/LC_MESSAGES/tutorial/floatingpoint.po` にコピーします。
   一時ディレクトリの `.tx/config` には、元の設定の `[main]` と対象リソースの節だけをコピーし、
   `file_filter` を `<lang>/LC_MESSAGES/tutorial/floatingpoint.po` にします。
   **その一時ディレクトリに移動して**次のコマンドを実行し、対象リソースの `[ja]` に対する
   `Uploading file` と `Done` を確認します。

   ```sh
   tx push --translation --languages ja
   ```

## ローカルの翻訳差分をレビューする

`scripts/po_review.py` は PO の差分を原文・変更前・変更後を並べた
Markdown に変換します。PO ファイルや Git のインデックスは変更しません。
各ファイルの見出しの下には、`docs.python.org` の公開日本語ドキュメントへのリンクも表示します。
リンク先の Python バージョンは比較対象の PO ヘッダーから取得し、判別できない場合は `3` を使います。
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
