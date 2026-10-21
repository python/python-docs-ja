"""Render local PO translation changes as a Markdown review report."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

import polib


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def entries(data):
    if data is None:
        return {}
    encoding = polib.detect_encoding(data)
    catalog = polib.pofile(data.decode(encoding), encoding=encoding)
    result = {}
    for entry in catalog:
        if entry.obsolete or not entry.msgid:
            continue
        key = (entry.msgctxt, entry.msgid)
        if key in result:
            raise ValueError(f"Duplicate PO entry: {key!r}")
        result[key] = entry
    return result


def signature(entry):
    if entry is None:
        return None
    return (
        entry.msgid_plural, entry.msgstr, entry.msgstr_plural,
        "fuzzy" in entry.flags,
    )


def changes(before, after):
    # Keep document order; entries removed from a catalog follow surviving ones.
    for key in dict.fromkeys([*after, *before]):
        old, new = before.get(key), after.get(key)
        if signature(old) != signature(new):
            yield old, new


def escape(text):
    # Ordinary punctuation such as dots, hyphens and parentheses needs no escape.
    return re.sub(r"([\\`*_\[\]<>#|~])", r"\\\1", text.replace("&", "&amp;"))


INLINE_RST = re.compile(
    r"(?<![\\`])(?::[\w.-]+(?::[\w.-]+)*:)?"
    r"(?P<ticks>`{1,2})(?!`)(?:\\.|[^`\\\n])+(?P=ticks)(?!`)"
)


def inline_text(text):
    # Preserve the whole reST token in a Markdown code span, including its
    # role and backticks. This avoids backslash noise in the Markdown source.
    parts = []
    start = 0
    for match in INLINE_RST.finditer(text):
        parts.append(escape(text[start:match.start()]))
        token = match.group()
        fence = "`" * (1 + max(len(run) for run in re.findall(r"`+", token)))
        parts.append(f"{fence} {token} {fence}")
        start = match.end()
    parts.append(escape(text[start:]))
    result = "".join(parts)
    # Prevent prose lines from becoming Markdown lists or thematic breaks.
    return re.sub(r"^(\s*)([-+]|\d+[.)])(?=\s|$)",
                  lambda match: match[1] + match[2][:-1] + "\\" + match[2][-1], result)


def paragraph(text):
    return "\n".join(
        "> " + inline_text(line) + ("  " if line else "")
        for line in text.split("\n")
    )


def field(label, text):
    # Keep indentation and alignment in code examples, while allowing prose
    # to wrap naturally in the Markdown viewer.
    if text.startswith((">>> ", ".. code-block::", ".. code::")):
        fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
        return f"**{label}**\n\n{fence}text\n{text}\n{fence}\n"
    return f"**{label}**\n\n{paragraph(text)}\n"


def translation(entry):
    if entry is None:
        return "（エントリーなし）"
    if entry.msgid_plural:
        return "\n\n".join(
            f"msgstr[{index}]: {text or '（未翻訳）'}"
            for index, text in sorted(entry.msgstr_plural.items())
        ) or "（未翻訳）"
    return entry.msgstr or "（未翻訳）"


def status(entry):
    if entry is None:
        return "なし"
    if "fuzzy" in entry.flags:
        return "fuzzy（要確認）"
    return "翻訳済み" if entry.translated() else "未翻訳"


def documentation_url(path, data):
    encoding = polib.detect_encoding(data)
    catalog = polib.pofile(data.decode(encoding), encoding=encoding)
    project = catalog.metadata.get("Project-Id-Version", "")
    match = re.search(r"\bPython\s+(\d+\.\d+)\b", project)
    version = match[1] if match else "3"
    page = quote(Path(path).with_suffix(".html").as_posix(), safe="/")
    return f"https://docs.python.org/ja/{version}/{page}"


def render_entry(path, old, new, number, link):
    entry = new if new is not None else old
    identity = json.dumps([path, entry.msgctxt, entry.msgid], ensure_ascii=False)
    identifier = hashlib.sha256(identity.encode()).hexdigest()[:12]
    kind = "追加" if old is None else "削除" if new is None else "変更"
    lines = [f"### {number}. {kind} · {identifier}", ""]
    if new is not None:
        lines.extend([f"[PO の該当箇所]({link}#L{new.linenum})", ""])
    if entry.occurrences:
        locations = ", ".join(
            f"{name}:{line}" if line else name for name, line in entry.occurrences
        )
        lines.extend(["原文の位置: " + escape(locations), ""])
    if entry.msgctxt is not None:
        lines.append(field("文脈（msgctxt）", entry.msgctxt))
    lines.append(field("原文", entry.msgid))
    if entry.msgid_plural:
        lines.append(field("原文（複数形）", entry.msgid_plural))
    if old is not None and old.msgid_plural != entry.msgid_plural:
        lines.append(field("変更前の原文（複数形）", old.msgid_plural or "（なし）"))
    lines.append(field("変更前", translation(old)))
    lines.append(field("変更後", translation(new)))
    lines.extend([f"状態: {status(old)} → {status(new)}", ""])
    if entry.tcomment:
        lines.append(field("翻訳者コメント", entry.tcomment))
    if entry.comment:
        lines.append(field("抽出コメント", entry.comment))
    return "\n".join(lines)


def report(root, *, cached=False, base=None, paths=(), output_dir=None):
    diff_args = ["diff", "--no-ext-diff", "--no-renames", "--name-status", "-z"]
    revision = None
    if cached:
        diff_args.append("--cached")
        comparison = "HEAD → ステージ済み（git diff --cached）"
    elif base:
        revision = git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
        diff_args.append(revision)
        comparison = f"{base} ({revision[:12]}) → 作業ツリー"
    else:
        comparison = "インデックス → 作業ツリー（git diff）"
    diff_args.extend(["--", *(paths or ("*.po",))])
    records = git(root, *diff_args).split(b"\0")
    sections, deleted = [], []
    count = 0
    for offset in range(0, len(records) - 1, 2):
        change = records[offset].decode()
        path = os.fsdecode(records[offset + 1])
        if not path.endswith(".po"):
            continue
        if change == "D":
            deleted.append(path)
            continue
        if change not in ("A", "M"):
            raise ValueError(f"Unsupported file change {change}: {path}")
        old_ref = "HEAD" if cached else revision or ""
        before = entries(None if change == "A" else git(root, "show", f"{old_ref}:{path}"))
        after_data = git(root, "show", f":{path}") if cached else (root / path).read_bytes()
        after = entries(after_data)
        modified = list(changes(before, after))
        if not modified:
            continue
        link = quote(Path(os.path.relpath(root / path, output_dir or root)).as_posix(), safe="/")
        section = [
            "## " + escape(path), "",
            f"[日本語ドキュメント（公開版）]({documentation_url(path, after_data)})", "",
        ]
        for old, new in modified:
            count += 1
            section.append(render_entry(path, old, new, count, link))
        sections.append("\n".join(section))
    header = [
        "# 翻訳レビュー", "", "比較: " + escape(comparison), "",
        f"翻訳・状態の変更: {count} エントリー / {len(sections)} ファイル。"
        f"ファイル全体の削除: {len(deleted)} 件。", "",
        "PO ヘッダー、折り返し、参照行番号だけの変更は省略しています。"
        "原文が変わったエントリーは追加・削除として表示します。", "",
    ]
    if not count:
        header.extend(["翻訳・状態の変更はありません。", ""])
    if deleted:
        sections.append("## 削除された PO ファイル\n\n" + "\n".join(
            "- " + escape(path) for path in deleted
        ) + "\n")
    return "\n".join([*header, *sections]).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--cached", action="store_true", help="compare HEAD to the index")
    selection.add_argument("--base", metavar="REV", help="compare REV to the working tree, including staged changes")
    parser.add_argument("-o", "--output", type=Path, help="write UTF-8 Markdown to this file (default: stdout)")
    parser.add_argument("paths", nargs="*", help="Git pathspecs relative to the repository root (default: all PO files)")
    args = parser.parse_args()
    try:
        root = Path(os.fsdecode(git(Path.cwd(), "rev-parse", "--show-toplevel")).rstrip("\n"))
        output = args.output.resolve() if args.output else None
        # A report must never overwrite a translation or another tracked file.
        if output:
            if output.suffix.lower() != ".md":
                raise ValueError("Output must have a .md extension")
            tracked = git(root, "ls-files", "-z").split(b"\0")
            if any((root / os.fsdecode(path)).resolve() == output for path in tracked if path):
                raise ValueError(f"Output is a tracked file: {output}")
        markdown = report(root, cached=args.cached, base=args.base, paths=args.paths,
                          output_dir=output.parent if output else root)
        if output:
            output.write_text(markdown, encoding="utf-8")
        else:
            sys.stdout.write(markdown)
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr.decode(errors="replace"))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
