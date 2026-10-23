import json
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
                         [Path("bugs.po")])
        translations.require_catalogs(
            self.destination, translations.active_catalogs(self.destination / ".tx/config")
        )
        # The generated source config remains complete for subsequent runs.
        self.assertEqual(translations.active_catalogs(self.source / ".tx/config"),
                         [Path(path) for path in catalogs])
        write_po(download, "c-api/pyexpat.po", "追加された訳")
        with mock.patch.object(translations, "resource_exists") as exists:
            translations.sync(self.source, self.destination, "ja",
                              skip_missing_resources=True)
        exists.assert_not_called()
        self.assertEqual((download / "c-api/pyexpat.po").read_bytes(),
                         (self.destination / "c-api/pyexpat.po").read_bytes())

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

    @unittest.skipUnless(shutil.which("pomerge"), "pomerge is required")
    def test_merge_uses_current_translation_across_renamed_paths(self):
        write_config(self.source, ["builtins/functions.po"])
        write_po(self.source, "builtins/functions.po", "新しい訳")
        write_po(self.source, "library/functions.po", "古い訳")
        old = write_po(self.destination, "library/functions.po", "以前の訳")
        self.track()

        translations.merge(self.source, self.destination)

        text = old.read_text(encoding="utf-8")
        self.assertIn('msgstr "新しい訳"', text)
        self.assertNotIn("古い訳", text)
        self.assertFalse((self.destination / "builtins/functions.po").exists())


if __name__ == "__main__":
    unittest.main()
