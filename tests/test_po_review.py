from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import polib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import po_review


SCRIPT = Path(po_review.__file__).resolve()


def catalog(*items, revision="before", wrapwidth=78):
    po = polib.POFile(wrapwidth=wrapwidth)
    po.metadata = {"Content-Type": "text/plain; charset=UTF-8", "PO-Revision-Date": revision}
    for item in items:
        po.append(polib.POEntry(**item))
    return str(po).encode("utf-8")


class EntryTests(unittest.TestCase):
    def test_rewrapping_headers_comments_and_locations_are_ignored(self):
        item = dict(msgid="English sentence. " * 10, msgstr="日本語の文章。" * 10)
        before = catalog(dict(item, occurrences=[("source.rst", "10")]))
        after = catalog(dict(item, occurrences=[("source.rst", "20")], tcomment="注釈"),
                        revision="after", wrapwidth=30)
        self.assertNotEqual(before, after)
        self.assertEqual([], list(po_review.changes(po_review.entries(before), po_review.entries(after))))

    def test_context_distinguishes_identical_sources(self):
        before = catalog(dict(msgid="Open", msgctxt="verb", msgstr="開く"),
                         dict(msgid="Open", msgctxt="adjective", msgstr="開く"))
        after = catalog(dict(msgid="Open", msgctxt="verb", msgstr="開く"),
                        dict(msgid="Open", msgctxt="adjective", msgstr="開いている"))
        changed = list(po_review.changes(po_review.entries(before), po_review.entries(after)))
        self.assertEqual(1, len(changed))
        self.assertEqual("adjective", changed[0][1].msgctxt)

    def test_plural_fuzzy_and_empty_translations(self):
        old = polib.POEntry(msgid="One file", msgid_plural="Many files",
                           msgstr_plural={0: "ファイル", 1: "複数のファイル"}, flags=["fuzzy"])
        new = polib.POEntry(msgid="One file", msgid_plural="Many files",
                           msgstr_plural={0: "ファイル", 1: ""})
        text = po_review.render_entry("test.po", old, new, 1, "test.po")
        self.assertIn("Many files", text)
        self.assertIn(r"msgstr\[1\]: 複数のファイル", text)
        self.assertIn(r"msgstr\[1\]: （未翻訳）", text)
        self.assertIn("fuzzy（要確認） → 未翻訳", text)
        new.msgstr_plural[1] = old.msgstr_plural[1]
        self.assertNotEqual(po_review.signature(old), po_review.signature(new))

    def test_new_removed_and_obsolete_entries(self):
        before = po_review.entries(catalog(dict(msgid="Old", msgstr="旧訳")))
        after = po_review.entries(catalog(dict(msgid="Old", msgstr="旧訳", obsolete=True),
                                         dict(msgid="New", msgstr="新訳")))
        changed = list(po_review.changes(before, after))
        self.assertEqual(2, len(changed))
        self.assertIsNone(changed[0][0])
        self.assertIsNone(changed[1][1])

    def test_markdown_and_html_are_literal(self):
        text = ':func:`open` <tag> [link](url) **bold**\n\n```\nnext'
        result = po_review.paragraph(text)
        self.assertIn(r"`` :func:`open` `` \<tag\> \[link\](url) \*\*bold\*\*", result)
        self.assertIn("> \n> \\`\\`\\`", result)
        self.assertEqual("> &amp;copy;  ", po_review.paragraph("&copy;"))

    def test_rst_roles_and_literals_do_not_need_backslash_escapes(self):
        text = ':ref:`tut-object` と :py:class:`表示名 <module.Class>`、``a_b``。'
        result = po_review.paragraph(text)
        self.assertEqual(
            '> `` :ref:`tut-object` `` と `` :py:class:`表示名 <module.Class>` ``、'
            '``` ``a_b`` ```。  ', result,
        )
        self.assertNotIn("\\", result)
        self.assertEqual("../../tutorial/classes.rst:422 (source)",
                         po_review.escape("../../tutorial/classes.rst:422 (source)"))

    def test_code_examples_keep_indentation_and_cannot_close_fence(self):
        code = '>>> if True:\n...     print("````")\n````'
        result = po_review.field("原文", code)
        self.assertIn("`````text\n" + code + "\n`````", result)


class GitReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.path = self.root / "a file.po"
        self.write("元の訳")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "initial")

    def git(self, *args):
        return po_review.git(self.root, *args)

    def write(self, text):
        self.path.write_bytes(catalog(dict(msgid="Example", msgstr=text)))

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_worktree_index_and_base_are_different_snapshots(self):
        self.write("ステージの訳")
        self.git("add", ".")
        self.write("作業中の訳")
        default = po_review.report(self.root)
        staged = po_review.report(self.root, cached=True)
        combined = po_review.report(self.root, base="HEAD")
        self.assertIn("ステージの訳", default)
        self.assertIn("作業中の訳", default)
        self.assertNotIn("元の訳", default)
        self.assertIn("元の訳", staged)
        self.assertIn("ステージの訳", staged)
        self.assertNotIn("作業中の訳", staged)
        self.assertIn("元の訳", combined)
        self.assertIn("作業中の訳", combined)
        self.assertNotIn("ステージの訳", combined)
        self.assertIn("a%20file.po#L", default)

    def test_added_deleted_untracked_and_path_selection(self):
        self.path.unlink()
        (self.root / "new.po").write_bytes(catalog(dict(msgid="New", msgstr="追加した訳")))
        self.git("add", ".")
        (self.root / "scratch.po").write_bytes(catalog(dict(msgid="Scratch", msgstr="未追跡の訳")))
        text = po_review.report(self.root, cached=True)
        self.assertIn("追加した訳", text)
        self.assertIn("削除された PO ファイル", text)
        self.assertIn("a file", text)
        self.assertNotIn("元の訳", text)
        self.assertNotIn("未追跡の訳", text)
        selected = po_review.report(self.root, cached=True, paths=("new.po",))
        self.assertIn("追加した訳", selected)
        self.assertNotIn("a file", selected)

    def test_no_changes_and_fuzzy_only_change(self):
        self.assertIn("変更はありません", po_review.report(self.root))
        self.path.write_bytes(catalog(dict(msgid="Example", msgstr="元の訳", flags=["fuzzy"])))
        self.assertIn("翻訳済み → fuzzy（要確認）", po_review.report(self.root))

    def test_cli_writes_report_without_changing_po_or_index(self):
        self.write("変更した訳")
        before = self.path.read_bytes()
        index = self.git("ls-files", "--stage")
        result = self.cli("--base", "HEAD", "-o", "review.md")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("変更した訳", (self.root / "review.md").read_text())
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(index, self.git("ls-files", "--stage"))

    def test_cli_failure_does_not_overwrite_output(self):
        output = self.root / "review.md"
        output.write_text("Keep this")
        result = self.cli("--base", "not-a-revision", "-o", "review.md")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("Keep this", output.read_text())
        self.git("add", "review.md")
        result = self.cli("-o", "review.md")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("tracked file", result.stderr)
        self.assertEqual("Keep this", output.read_text())
        before = self.path.read_bytes()
        result = self.cli("-o", "a file.po")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
