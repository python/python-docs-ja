import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import translations


def write_config(root, catalogs):
    path = root / ".tx/config"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "[main]\nhost = https://www.transifex.com\n"
    for index, catalog in enumerate(catalogs):
        template = Path(catalog).with_suffix(".pot").as_posix()
        text += f"\n[resource{index}]\nsource_file = pot/{template}\n"
    path.write_text(text, encoding="utf-8")


def write_po(root, name, translation):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
        'msgid "example"\nmsgstr ' + json.dumps(translation, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


DATED_PO = (
    '# Catalog\n'
    'msgid ""\n'
    'msgstr ""\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"\n'
    '"POT-Creation-Date: 2026-09-29 18:58+0000\\n"\n'
    '"PO-Revision-Date: 2025-09-16 00:01+0000\\n"\n'
    '"Last-Translator: Translator\\n"\n'
    '\n'
    '#: example.rst:10\n'
    'msgid "example"\n'
    'msgstr "翻訳"\n'
).encode('utf-8')


class TranslationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        self.source.mkdir()
        self.destination.mkdir()
        subprocess.run(
            ["git", "init", "--quiet", str(self.destination)], check=True
        )

    def track(self):
        subprocess.run(
            ["git", "-C", str(self.destination), "add", "."], check=True
        )

    def restore_catalog(self, before, incoming):
        target = self.destination / "example.po"
        target.write_bytes(before)
        self.track()
        target.write_bytes(incoming)
        translations.restore_timestamp_only_changes(self.destination)
        return target

    def test_restore_timestamp_only_changes(self):
        for newline in (b'\n', b'\r\n'):
            before = DATED_PO.replace(b'\n', newline)
            changes = [
                before,
                before.replace(b'2026-09-29', b'2026-10-19'),
                before.replace(b'2025-09-16', b'2026-10-20'),
                before.replace(b'2026-09-29', b'2026-10-19').replace(
                    b'2025-09-16', b'2026-10-20'
                ),
            ]
            for incoming in changes:
                with self.subTest(newline=newline, incoming=incoming):
                    target = self.restore_catalog(before, incoming)
                    self.assertEqual(target.read_bytes(), before)

    def test_restore_keeps_other_changes_and_their_new_timestamps(self):
        updated = DATED_PO.replace(b'2026-09-29', b'2026-10-19')
        replacements = [
            ('msgstr "翻訳"', 'msgstr "新しい訳"'),
            ('msgid "example"', 'msgid "changed"'),
            ('#: example.rst:10', '#: example.rst:20'),
            ('# Catalog', '# Updated comment'),
            ('msgid "example"', '#, fuzzy\nmsgid "example"'),
            ('Last-Translator: Translator', 'Last-Translator: New Translator'),
            ('msgstr "翻訳"', 'msgstr ""\n"翻訳"'),
        ]
        for old, new in replacements:
            with self.subTest(change=new):
                incoming = updated.replace(old.encode(), new.encode())
                target = self.restore_catalog(DATED_PO, incoming)
                self.assertEqual(target.read_bytes(), incoming)

    def test_restore_does_not_ignore_timestamp_text_in_translation(self):
        before = DATED_PO.replace(
            'msgstr "翻訳"\n'.encode(),
            b'msgstr ""\n"POT-Creation-Date: 2026-09-29 18:58+0000\\n"\n',
        )
        incoming = before.replace(b'2026-09-29', b'2026-10-19')
        target = self.restore_catalog(before, incoming)
        self.assertEqual(target.read_bytes(), incoming)

    def test_restore_preserves_new_files_and_deletions(self):
        deleted = self.destination / "deleted.po"
        deleted.write_bytes(DATED_PO)
        self.track()
        deleted.unlink()
        new = self.destination / "new.po"
        new.write_bytes(DATED_PO)
        translations.restore_timestamp_only_changes(self.destination)
        self.assertFalse(deleted.exists())
        self.assertEqual(new.read_bytes(), DATED_PO)

    def test_restore_command_handles_multiple_files_and_explicit_root(self):
        catalogs = ["unchanged.po", "translated.po", "library/with space.po"]
        for path in catalogs:
            target = self.destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(DATED_PO)
        self.track()
        updated = DATED_PO.replace(b'2026-09-29', b'2026-10-19')
        translated = updated.replace('翻訳'.encode(), '新しい訳'.encode())
        (self.destination / "unchanged.po").write_bytes(updated)
        (self.destination / "translated.po").write_bytes(translated)
        (self.destination / "library/with space.po").write_bytes(updated)
        subprocess.run(
            [sys.executable, translations.__file__, "restore-timestamp-only",
             str(self.destination)],
            cwd=self.source, check=True, stdout=subprocess.PIPE,
        )

        self.assertEqual((self.destination / "unchanged.po").read_bytes(), DATED_PO)
        self.assertEqual((self.destination / "translated.po").read_bytes(), translated)
        self.assertEqual((self.destination / "library/with space.po").read_bytes(), DATED_PO)

    def test_normalize_references_and_dates_before_staging(self):
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                before = DATED_PO.replace(b"\n", newline)
                changed = before.replace(b"example.rst:10", b"example.rst:200")
                changed = changed.replace(b"2026-09-29", b"2026-10-24")
                for name in ("unchanged.po", "translated.po", "locations.po", "deleted.po"):
                    (self.destination / name).write_bytes(before)
                self.track()
                (self.destination / "unchanged.po").write_bytes(changed)
                (self.destination / "translated.po").write_bytes(
                    changed.replace('翻訳'.encode(), '新しい訳'.encode())
                )
                locations = changed.replace(
                    b"#: example.rst:200" + newline,
                    b"#: example.rst:200 example.rst:300" + newline,
                )
                (self.destination / "locations.po").write_bytes(locations)
                (self.destination / "deleted.po").unlink()
                new = self.destination / ("new-crlf.po" if newline == b"\r\n" else "new-lf.po")
                new.write_bytes(changed)
                subprocess.run(
                    [sys.executable, translations.__file__, "restore-timestamp-only",
                     "--references", str(self.destination)],
                    check=True, stdout=subprocess.PIPE, cwd=self.source,
                )
                self.assertEqual((self.destination / "unchanged.po").read_bytes(), before)
                expected = before.replace('翻訳'.encode(), '新しい訳'.encode())
                expected = expected.replace(b"2026-09-29", b"2026-10-24")
                expected = expected.replace(b"#: example.rst:10" + newline, b"")
                self.assertEqual((self.destination / "translated.po").read_bytes(), expected)
                self.assertEqual(
                    (self.destination / "locations.po").read_bytes(),
                    locations.replace(b"#: example.rst:200 example.rst:300" + newline, b""),
                )
                self.assertEqual(new.read_bytes(), changed.replace(b"#: example.rst:200" + newline, b""))
                self.assertFalse((self.destination / "deleted.po").exists())
                self.track()
                staged = subprocess.check_output(
                    ["git", "-C", str(self.destination), "show", ":translated.po"]
                )
                self.assertEqual(staged, expected)

    def test_normalize_references_preserves_other_entry_changes(self):
        changed = DATED_PO.replace(b"example.rst:10", b"example.rst:200")
        for old, new, action in [
            (b'msgid "example"', b'msgid "new source"', "drop"),
            (b'msgid "example"', b'msgctxt "new context"\nmsgid "example"', "drop"),
            (b"example.rst:200", b"renamed.rst:200", "drop"),
            (b"example.rst:200", b"example.rst:200 other.rst:30", "drop"),
            (b'#: example.rst:200\n', b'', "keep"),
            (b'msgid "example"', b'#, fuzzy\nmsgid "example"', "restore"),
            (b'msgid "example"', b'#. new comment\nmsgid "example"', "restore"),
            ('msgstr "翻訳"'.encode(), 'msgstr "新しい訳"'.encode(), "drop"),
        ]:
            with self.subTest(change=new):
                incoming = changed.replace(old, new)
                expected = incoming
                if action == "drop":
                    expected = b"".join(
                        line for line in incoming.splitlines(keepends=True)
                        if not line.startswith(b"#:")
                    )
                elif action == "restore":
                    expected = incoming.replace(b"example.rst:200", b"example.rst:10")
                self.assertEqual(translations.normalize_po_references(DATED_PO, incoming),
                                 expected)

    def test_changed_source_occurrence_counts_drop_all_reference_lines(self):
        header = DATED_PO.split(b"#: example.rst:10")[0]
        message = b'msgid "yes"\nmsgstr "yes"\n'
        old_references = b"#: ../../c-api/buffer.rst:292 ../../c-api/buffer.rst:294\n"
        for new_references in [
            b"#: ../../c-api/buffer.rst:304\n",
            (b"#: ../../c-api/buffer.rst:304 ../../c-api/buffer.rst:305\n"
             b"#: ../../c-api/buffer.rst:308 ../../c-api/buffer.rst:309\n"),
        ]:
            for newline in (b"\n", b"\r\n"):
                with self.subTest(references=new_references, newline=newline):
                    original = (header + old_references + message).replace(b"\n", newline)
                    incoming = (header + new_references + message).replace(b"\n", newline)
                    expected = (header + message).replace(b"\n", newline)
                    normalized = translations.normalize_po_references(original, incoming)
                    self.assertEqual(normalized, expected)
                    self.assertEqual(
                        translations.normalize_po_references(normalized, incoming), expected
                    )

    def test_restore_line_numbers_matches_context_plural_and_reordered_entries(self):
        header = DATED_PO.split(b"#: example.rst:10")[0]
        first = (b'#: one.rst:10 two.rst:20\nmsgctxt "first"\n'
                 b'msgid "same"\nmsgstr "first translation"\n\n')
        second = (b'#: one.rst:30\nmsgctxt "second"\n'
                  b'msgid "same"\nmsgid_plural "others"\nmsgstr[0] "plural"\n\n')
        added = b'#: new.rst:100\nmsgid "new"\nmsgstr ""\n\n'
        obsolete = b'#~ msgid "old"\n#~ msgstr "old translation"\n'
        updated_first = first.replace(b"one.rst:10 two.rst:20", b"one.rst:100\n#: two.rst:200")
        updated_first = updated_first.replace(b'msgid "same"', b'msgid ""\n"sa"\n"me"')
        updated_second = second.replace(b"one.rst:30", b"one.rst:300")
        incoming = header + added + updated_second + updated_first + obsolete
        expected_first = updated_first.replace(b"one.rst:100\n#: two.rst:200", b"one.rst:10 two.rst:20")
        self.assertEqual(
            translations.normalize_po_references(header + first + second + obsolete, incoming),
            header + added.replace(b"#: new.rst:100\n", b"") + second + expected_first + obsolete,
        )
        # A new plural message with a translation has its references removed.
        updated_second = updated_second.replace(b'"others"', b'"new plural"')
        self.assertEqual(
            translations.normalize_po_references(header + second, header + updated_second),
            header + updated_second.replace(b"#: one.rst:300\n", b""),
        )

    def test_untranslated_source_changes_drop_references(self):
        before = DATED_PO.replace('msgstr "翻訳"'.encode(), b'msgstr ""')
        for original, incoming in [
            (b"", before),
            (before, before.replace(b'msgid "example"', b'msgid "new source"')),
            (before, before.replace(b'msgid "example"',
                                    b'msgctxt "new context"\nmsgid "example"')),
            (before, before.replace(b'msgid "example"\nmsgstr ""\n',
                                    b'msgid "example"\nmsgid_plural "examples"\nmsgstr[0] ""\n')),
        ]:
            with self.subTest(incoming=incoming):
                expected = incoming.replace(b"#: example.rst:10\n", b"")
                normalized = translations.normalize_po_references(original, incoming)
                self.assertEqual(normalized, expected)
                self.assertEqual(translations.normalize_po_references(normalized, incoming), expected)

    def test_removed_references_do_not_return_on_next_download(self):
        updated = DATED_PO.replace('翻訳'.encode(), '新しい訳'.encode())
        updated = updated.replace(b"#: example.rst:10\n", b"#: example.rst:200\n#: other.rst:300\n")
        expected = updated.replace(b"#: example.rst:200\n#: other.rst:300\n", b"")
        normalized = translations.normalize_po_references(DATED_PO, updated)
        self.assertEqual(normalized, expected)
        self.assertEqual(translations.normalize_po_references(normalized, updated), expected)
        # Translation text resembling a reference is not a comment.
        literal = updated.replace('新しい訳'.encode(), b"#: example.rst:200")
        self.assertIn(b'msgstr "#: example.rst:200"',
                      translations.normalize_po_references(normalized, literal))

    def test_sync_removes_old_path_and_preserves_untracked_files(self):
        catalogs = ["builtins/functions.po", "library/builtins.po", "bugs.po"]
        write_config(self.source, catalogs)
        download = self.source / "ja/LC_MESSAGES"
        for path in catalogs:
            write_po(download, path, "新しい訳")
        # A stale downloaded file must not be copied back into the repository.
        write_po(download, "library/functions.po", "古い訳")
        old = write_po(self.destination, "library/functions.po", "古い訳")
        write_po(self.destination, "library/builtins.po", "モジュール")
        self.track()
        scratch = write_po(self.destination, "scratch.po", "作業中")
        scratch_before = scratch.read_bytes()

        translations.sync(self.source, self.destination, "ja")

        self.assertFalse(old.exists())
        for path in catalogs:
            self.assertEqual(
                (download / path).read_bytes(),
                (self.destination / path).read_bytes(),
            )
        self.assertEqual(scratch_before, scratch.read_bytes())
        self.assertEqual(
            (self.source / ".tx/config").read_bytes(),
            (self.destination / ".tx/config").read_bytes(),
        )

    def test_incomplete_download_does_not_change_repository(self):
        write_config(self.source, ["builtins/functions.po", "bugs.po"])
        write_po(self.source / "ja/LC_MESSAGES", "builtins/functions.po", "新しい訳")
        write_config(self.destination, ["library/functions.po"])
        old = write_po(self.destination, "library/functions.po", "古い訳")
        self.track()
        before = old.read_bytes()
        config_before = (self.destination / ".tx/config").read_bytes()

        with self.assertRaises(FileNotFoundError):
            translations.sync(self.source, self.destination, "ja")

        self.assertEqual(before, old.read_bytes())
        self.assertEqual(config_before, (self.destination / ".tx/config").read_bytes())
        self.assertFalse((self.destination / "builtins/functions.po").exists())

    def test_sync_skips_unregistered_resource_and_picks_it_up_later(self):
        catalogs = ["bugs.po", "c-api/pyexpat.po"]
        write_config(self.source, catalogs)
        config = self.source / ".tx/config"
        original = config.read_bytes().replace(b"host =", b"host        =")
        original = b"# Preserve tx formatting\n" + original
        config.write_bytes(original)
        download = self.source / "ja/LC_MESSAGES"
        write_po(download, "bugs.po", "新しい訳")
        obsolete = write_po(self.destination, "removed.po", "古い訳")
        self.track()

        with mock.patch.object(translations, "resource_exists", return_value=False) as exists:
            translations.sync(self.source, self.destination, "ja",
                              skip_missing_resources=True)
        exists.assert_called_once_with("resource1")
        self.assertFalse(obsolete.exists())
        self.assertFalse((self.destination / "c-api/pyexpat.po").exists())
        self.assertEqual(translations.active_catalogs(self.destination / ".tx/config"),
                         [Path(path) for path in catalogs])
        self.assertEqual((self.destination / ".tx/config").read_bytes(), original)
        # Both configs remain complete for subsequent runs.
        self.assertEqual(translations.active_catalogs(self.source / ".tx/config"),
                         [Path(path) for path in catalogs])
        write_po(download, "c-api/pyexpat.po", "追加された訳")
        with mock.patch.object(translations, "resource_exists") as exists:
            translations.sync(self.source, self.destination, "ja",
                              skip_missing_resources=True)
        exists.assert_not_called()
        self.assertEqual((download / "c-api/pyexpat.po").read_bytes(),
                         (self.destination / "c-api/pyexpat.po").read_bytes())
        self.assertEqual((self.destination / ".tx/config").read_bytes(), original)

    def test_sync_preserves_existing_po_for_unavailable_resource(self):
        catalogs = ["bugs.po", "c-api/pyexpat.po"]
        write_config(self.source, catalogs)
        write_po(self.source / "ja/LC_MESSAGES", "bugs.po", "新しい訳")
        old = write_po(self.destination, "c-api/pyexpat.po", "既存の訳")
        self.track()
        before = old.read_bytes()
        with mock.patch.object(translations, "resource_exists", return_value=False):
            translations.sync(self.source, self.destination, "ja",
                              skip_missing_resources=True)
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(translations.active_catalogs(self.destination / ".tx/config"),
                         [Path(path) for path in catalogs])
        self.assertEqual((self.destination / ".tx/config").read_bytes(),
                         (self.source / ".tx/config").read_bytes())

    def test_skip_does_not_hide_incomplete_download_or_api_failure(self):
        write_config(self.source, ["bugs.po", "new.po", "missing.po"])
        write_po(self.source / "ja/LC_MESSAGES", "bugs.po", "新しい訳")
        write_config(self.destination, ["old.po"])
        old = write_po(self.destination, "old.po", "既存の訳")
        self.track()
        before = old.read_bytes()
        config_before = (self.destination / ".tx/config").read_bytes()
        for outcome, error in [(True, FileNotFoundError),
                               (URLError("offline"), URLError)]:
            with self.subTest(outcome=outcome):
                with mock.patch.object(translations, "resource_exists",
                                       side_effect=[False, outcome]):
                    with self.assertRaises(error):
                        translations.sync(self.source, self.destination, "ja",
                                          skip_missing_resources=True)
                self.assertEqual(old.read_bytes(), before)
                self.assertEqual((self.destination / ".tx/config").read_bytes(),
                                 config_before)
                self.assertFalse((self.destination / "bugs.po").exists())

    def test_skip_refuses_empty_download(self):
        write_config(self.source, ["new.po"])
        old = write_po(self.destination, "old.po", "既存の訳")
        self.track()
        with mock.patch.object(translations, "resource_exists", return_value=False):
            with self.assertRaisesRegex(ValueError, "No PO catalogs downloaded"):
                translations.sync(self.source, self.destination, "ja",
                                  skip_missing_resources=True)
        self.assertTrue(old.exists())
        self.assertFalse((self.destination / ".tx/config").exists())

    def test_resource_exists_only_skips_404(self):
        resource = "o:python-doc:p:python-newest:r:c-api--pyexpat"
        with mock.patch.dict(translations.os.environ, {"TX_TOKEN": "test-token"}):
            with mock.patch.object(translations, "urlopen") as open_url:
                self.assertTrue(translations.resource_exists(resource))
                request = open_url.call_args.args[0]
                self.assertEqual(request.full_url,
                                 "https://rest.api.transifex.com/resources/" + resource)
                self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
                self.assertEqual(open_url.call_args.kwargs, {"timeout": 30})
            for code in [404, 401, 403, 429, 500]:
                with self.subTest(code=code):
                    error = HTTPError("https://rest.api.transifex.com/", code, "error", {}, None)
                    with mock.patch.object(translations, "urlopen", side_effect=error):
                        if code == 404:
                            self.assertFalse(translations.resource_exists(resource))
                        else:
                            with self.assertRaises(HTTPError):
                                translations.resource_exists(resource)
            with mock.patch.object(translations, "urlopen", side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):
                    translations.resource_exists(resource)

    def test_empty_config_does_not_delete_catalogs(self):
        write_config(self.source, [])
        old = write_po(self.destination, "library/functions.po", "古い訳")
        self.track()
        with self.assertRaises(ValueError):
            translations.sync(self.source, self.destination, "ja")
        self.assertTrue(old.exists())

    def test_config_cannot_escape_catalog_directory(self):
        write_config(self.source, ["../outside.po"])
        with self.assertRaises(ValueError):
            translations.active_catalogs(self.source / ".tx/config")

    def test_update_validates_after_pull_failure(self):
        scripts = self.source / "scripts"
        scripts.mkdir()
        update = scripts / "update.sh"
        shutil.copyfile(Path(translations.__file__).with_name("update.sh"), update)
        doc = self.source / "cpython/Doc"
        doc.mkdir(parents=True)
        (doc / "conf.py").touch()
        executables = self.root / "bin"
        executables.mkdir()
        validation_log = self.root / "validation.log"
        commands = {
            "sphinx-build": "exit 0",
            "sphinx-intl": "exit 0",
            "tx": "exit 1",
            "python": 'printf "%s\\n" "$@" > "$VALIDATION_LOG"\n'
                      'exit "$VALIDATION_STATUS"',
        }
        for name, body in commands.items():
            executable = executables / name
            executable.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
            executable.chmod(0o755)
        for status in (0, 42):
            with self.subTest(validation_status=status):
                validation_log.unlink(missing_ok=True)
                result = subprocess.run(
                    ["sh", str(update)], capture_output=True, text=True,
                    env={**os.environ, "PATH": f"{executables}:{os.environ['PATH']}",
                         "VALIDATION_LOG": str(validation_log),
                         "VALIDATION_STATUS": str(status)},
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn("tx pull failed", result.stderr)
                arguments = validation_log.read_text().splitlines()
                self.assertEqual(arguments[1], "sync")
                self.assertIn("--skip-missing-resources", arguments)

    def test_merge_refuses_empty_source_and_missing_tracked_po(self):
        subprocess.run(["git", "init", "--quiet", str(self.source)], check=True)
        write_config(self.source, ["new.po", "bugs.po"])
        write_po(self.destination, "bugs.po", "既存の訳")
        self.track()
        with mock.patch.object(translations.subprocess, "run",
                               wraps=subprocess.run) as run:
            with self.assertRaisesRegex(ValueError, "No source catalogs"):
                translations.merge(self.source, self.destination)
            missing = write_po(self.source, "bugs.po", "新しい訳")
            subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
            missing.unlink()
            with self.assertRaises(FileNotFoundError):
                translations.merge(self.source, self.destination)
        self.assertFalse(any(call.args[0][0] == "pomerge" for call in run.call_args_list))

    @unittest.skipUnless(shutil.which("pomerge"), "pomerge is required")
    def test_merge_uses_current_translation_across_renamed_paths(self):
        subprocess.run(["git", "init", "--quiet", str(self.source)], check=True)
        write_config(self.source, ["builtins/functions.po", "c-api/pyexpat.po"])
        write_po(self.source, "builtins/functions.po", "新しい訳")
        write_po(self.source, "library/functions.po", "古い訳")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        old = write_po(self.destination, "library/functions.po", "以前の訳")
        self.track()

        translations.merge(self.source, self.destination)

        text = old.read_text(encoding="utf-8")
        self.assertIn('msgstr "新しい訳"', text)
        self.assertNotIn("古い訳", text)
        self.assertFalse((self.destination / "builtins/functions.po").exists())


if __name__ == "__main__":
    unittest.main()
