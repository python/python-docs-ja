"""Sync and merge the PO catalogs listed in a generated Transifex config."""

import argparse
import configparser
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess


def without_po_timestamps(content):
    """Ignore date fields in the PO header, preserving every other byte."""
    header = re.search(
        rb'^msgid ""\r?\nmsgstr "[^\r\n]*"\r?\n(?:"[^\r\n]*"\r?\n)*',
        content, re.MULTILINE,
    )
    if header is None:
        return content
    normalized = re.sub(
        rb'^"(?:POT-Creation-Date|PO-Revision-Date):[^"\r\n]*\\n"\r?\n',
        b'', header.group(), flags=re.MULTILINE,
    )
    return content[:header.start()] + normalized + content[header.end():]


def restore_timestamp_only_changes(root):
    """Restore PO files whose unstaged changes only affect header dates.

    Run after wrapping, so formatting differences in downloaded or merged files
    do not prevent timestamp-only changes from being recognized.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "-z", "--", "*.po"],
        check=True, stdout=subprocess.PIPE,
    )
    for name in result.stdout.split(b"\0"):
        if not name:
            continue
        path = os.fsdecode(name)
        target = root / path
        if not target.is_file():
            continue
        original = subprocess.run(
            ["git", "-C", str(root), "show", f":{path}"],
            check=True, stdout=subprocess.PIPE,
        ).stdout
        if (
            without_po_timestamps(target.read_bytes())
            == without_po_timestamps(original)
        ):
            target.write_bytes(original)
            print(f"Ignored timestamp-only change: {path}")


def active_catalogs(config_path):
    config = configparser.ConfigParser(interpolation=None)
    with config_path.open(encoding="utf-8") as stream:
        config.read_file(stream)
    catalogs = set()
    for section in config.sections():
        if section == "main":
            continue
        source = PurePosixPath(config[section]["source_file"])
        relative = source.relative_to("pot")
        if ".." in relative.parts or relative.suffix != ".pot":
            raise ValueError(f"Invalid catalog path: {source}")
        catalogs.add(Path(relative.with_suffix(".po")))
    if not catalogs:
        raise ValueError(f"No catalogs listed in {config_path}")
    return sorted(catalogs)


def tracked_catalogs(root):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.po"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [Path(os.fsdecode(name)) for name in result.stdout.split(b"\0") if name]


def require_catalogs(root, catalogs):
    missing = [str(path) for path in catalogs if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing PO catalogs in {root}: {', '.join(missing)}")


def sync(source, destination, language):
    config = source / ".tx/config"
    catalogs = active_catalogs(config)
    downloaded = source / language / "LC_MESSAGES"
    require_catalogs(downloaded, catalogs)
    obsolete = set(tracked_catalogs(destination)) - set(catalogs)

    for path in catalogs:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(downloaded / path, target)
    for path in sorted(obsolete):
        (destination / path).unlink(missing_ok=True)
        print(f"Removed obsolete catalog: {path}")
    (destination / ".tx").mkdir(exist_ok=True)
    shutil.copyfile(config, destination / ".tx/config")


def merge(source, destination):
    # Ignore stale PO files even if a source checkout still contains them.
    catalogs = active_catalogs(source / ".tx/config")
    targets = tracked_catalogs(destination)
    if not targets:
        raise ValueError(f"No target catalogs in {destination}")
    require_catalogs(source, catalogs)
    require_catalogs(destination, targets)
    subprocess.run(
        [
            "pomerge",
            "--from",
            *(str(source / path) for path in catalogs),
            "--to",
            *(str(destination / path) for path in targets),
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser("sync")
    sync_parser.add_argument("source", type=Path)
    sync_parser.add_argument("destination", type=Path)
    sync_parser.add_argument("--language", default="ja")
    merge_parser = commands.add_parser("merge")
    merge_parser.add_argument("source", type=Path)
    merge_parser.add_argument("destination", type=Path)
    restore_parser = commands.add_parser("restore-timestamp-only")
    restore_parser.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.command == "sync":
        sync(args.source, args.destination, args.language)
    elif args.command == "merge":
        merge(args.source, args.destination)
    else:
        restore_timestamp_only_changes(args.root)


if __name__ == "__main__":
    main()
