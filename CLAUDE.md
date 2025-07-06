# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

# GEMINI.md: python-docs-ja プロジェクト ガイドライン

### 1. プロジェクト概要

このプロジェクトは、プログラミング言語Pythonの公式ドキュメントを日本語に翻訳する、Pythonプロジェクト公式の翻訳チームです。

### 2. 基本的なワークフロー

翻訳作業は、ユーザーから指定された単一の `.po` ファイルに対して行います。一度に複数のファイルを扱ったり、まとめて翻訳したりはしません。

### 3. 翻訳作業のルール

作業を行う際には、以下のルールを厳守してください。

#### 3.1. poファイルのフォーマットを維持する

-   翻訳は gettext を利用した `.po` ファイル形式で行われます。
-   `msgid` (原文) と `msgstr` (訳文) のペアで構成されています。
-   **絶対に `.po` ファイルの構造を壊さないでください。** 翻訳対象は `msgstr` の中身だけです。

#### 3.2. reStructuredTextの構文を維持する

-   ドキュメントは reStructuredText で記述されています。
-   ``:mod:`` のようなロールや、`.. note::` のようなディレクティブ、リンクなどの構文を壊さないように、細心の注意を払って翻訳してください。

#### 3.3. 翻訳の進め方

-   **既存翻訳の確認:** すでに翻訳されている箇所 (`msgstr` に記述がある箇所) は、原文 (`msgid`) の内容が正しく反映されているかを確認します。必要であれば、より適切で自然な表現に修正します。
-   **未翻訳部分の翻訳:** `msgstr` が空になっている未翻訳の部分は、他の部分の翻訳スタイルやトーンと違和感がないように、自然な日本語訳を作成・追加します。

#### 3.4. 翻訳品質の自動改善

翻訳作業時は、特別な指示がなくても以下の点を自動的にチェックし、読みにくい訳文を改善してください：

-   **不自然な表現の修正:** 「だったり」「させる」などの不自然な語尾や接続表現を自然な日本語に修正
-   **用語の統一:** 同じ概念を表す用語は一貫して使用（例：「並行処理」「並列処理」の使い分け）
-   **技術用語の日本語化:** 一般的に日本語化されている用語は日本語で記述（例：「Transport」→「トランスポート」、「subprocesses」→「サブプロセス」）
-   **語尾の統一:** 箇条書きなどでは語尾をですます調に統一
-   **読みやすさの向上:** 冗長な表現を簡潔にし、より自然で読みやすい日本語に改善
-   **文脈に適した表現:** 技術文書として適切な表現を選択

これらの改善は、翻訳の正確性を保ちながら、より自然で読みやすい日本語文書にするために行います。

### 4. 具体的な作業例

「`library/asyncio.po` を翻訳してください」という指示があった場合、以下の手順で作業を進めます。

1.  `read_file` ツールで `library/asyncio.po` の内容を読み込みます。
2.  未翻訳の箇所 (`msgstr ""`) を見つけます。
3.  reStructuredTextの構文に注意しながら、対応する `msgid` を翻訳し、`msgstr` に記述します。
4.  既存の翻訳もレビューし、必要に応じて修正案を考えます。
5.  `replace` または `write_file` ツールを使い、変更を適用します。

## Repository Structure

The repository is organized as follows:
- Root level: Core documentation files (about.po, bugs.po, copyright.po, etc.)
- `c-api/`: C API documentation translations
- `library/`: Standard library documentation translations  
- `tutorial/`: Tutorial documentation translations
- `reference/`: Language reference translations
- `whatsnew/`: "What's New" documentation for different Python versions
- `deprecations/`: Deprecation notices
- `extending/`, `distributing/`, `installing/`: Advanced topics
- `faq/`, `howto/`: FAQ and how-to guides
- `using/`: Platform-specific usage guides

## Common Development Commands

### Build Documentation
```bash
make                    # Build HTML documentation locally
make htmlview          # Build and open documentation in browser
```

### Translation Management
```bash
make todo              # List remaining translation tasks and show progress
make fuzzy             # Find fuzzy translation strings that need review
make wrap              # Rewrap modified .po files to fix line lengths
```

### Quality Assurance
```bash
make verifs            # Run all verification checks (spell, line-length, sphinx-lint)
make spell             # Check spelling in translation files
make line-length       # Check for lines exceeding 80 characters
make sphinx-lint       # Run Sphinx linting on .po files
```

### Maintenance
```bash
make clean             # Remove build artifacts and temporary files
scripts/update.sh      # Pull latest translations from Transifex (requires setup)
```

## Prerequisites

Before working with this repository, ensure you have the required dependencies:

```bash
# Install CPython documentation build dependencies
python -m pip install -r venv/cpython/Doc/requirements.txt

# Required tools (installed via pip or system package manager)
pip install powrap pospell pomerge potodo
```

## Translation Workflow

1. **Translation Source**: Translations are managed via Transifex, not directly in this repository
2. **File Generation**: .po files are generated from Transifex translations
3. **Local Building**: Use `make` commands to build and verify translations locally
4. **Issue Reporting**: Report translation issues to [python-doc-ja repository](https://github.com/python-doc-ja/python-doc-ja/issues)

## Architecture Notes

- **CPython Integration**: The build system clones CPython repository into `venv/cpython/` and builds documentation using CPython's Sphinx configuration
- **Commit Tracking**: `CPYTHON_CURRENT_COMMIT` in Makefile tracks the specific CPython commit used for generating .po files
- **Excluded Files**: Older Python version documentation (2.x, 3.0-3.10) are excluded from translation
- **Language Configuration**: Target language is Japanese (`ja`), branch is `3.14`

## File Format

All translation files are in gettext .po format containing:
- Original English text (`msgid`)
- Japanese translation (`msgstr`)
- Translation metadata and comments
- Fuzzy markers for translations needing review

## Pull Request Policy

This repository does not accept pull requests. Translation changes must be made through the Transifex platform and will be automatically synchronized to this repository.


