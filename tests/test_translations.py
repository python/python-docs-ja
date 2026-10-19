import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

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
