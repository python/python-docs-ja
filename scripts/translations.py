"""Sync and merge the PO catalogs listed in a generated Transifex config."""

import argparse
import configparser
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


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


def po_references(content):
    """Locate reference comments without reserializing the PO file."""
    import polib

    lines = content.splitlines(keepends=True)
    encoding = polib.detect_encoding(content)
    entries = polib.pofile(content.decode(encoding), encoding=encoding)
    references = {}
    for index, entry in enumerate(entries):
        if entry.obsolete:
            continue
        end = entries[index + 1].linenum - 1 if index + 1 < len(entries) else len(lines)
        positions = [
            pos for pos in range(entry.linenum - 1, end)
            if lines[pos].startswith(b"#:")
        ]
        key = (entry.msgctxt, entry.msgid, entry.msgid_plural)
        references[key] = (entry, positions)
    return lines, references


def normalize_po_references(original, incoming):
    """Drop references for changed messages or source paths; ignore line-number updates."""
    old_lines, old_references = po_references(original)
    lines, references = po_references(incoming)
    for key, (entry, positions) in references.items():
        if not positions:
            continue
        old_entry, old_positions = old_references.get(key, (None, []))
        if old_entry is None:
            changed = True
        else:
            changed = (
                (entry.msgstr, entry.msgstr_plural)
                != (old_entry.msgstr, old_entry.msgstr_plural)
                or [path for path, _ in entry.occurrences]
                != [path for path, _ in old_entry.occurrences]
            )
        if changed or (old_entry is not None and not old_positions):
            for pos in positions:
                lines[pos] = b''
            continue
        lines[positions[0]] = b"".join(old_lines[pos] for pos in old_positions)
        for pos in positions[1:]:
            lines[pos] = b""
    return b"".join(lines)


def restore_timestamp_only_changes(root, *, normalize_references=False):
    """Restore PO files whose unstaged changes only affect header dates.

    Optionally drop references for new/changed messages or source paths and restore
    other line numbers.
    Run after wrapping so formatting differences do not mask date-only changes.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "-z", "--", "*.po"],
        check=True, stdout=subprocess.PIPE,
    )
    names = result.stdout.split(b"\0")
    untracked = set()
    if normalize_references:
        untracked = set(subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard",
             "-z", "--", "*.po"], check=True, stdout=subprocess.PIPE,
        ).stdout.split(b"\0"))
        names.extend(sorted(untracked))
    for name in names:
        if not name:
            continue
        path = os.fsdecode(name)
        target = root / path
        if not target.is_file():
            continue
        original = b"" if name in untracked else subprocess.run(
            ["git", "-C", str(root), "show", f":{path}"],
            check=True, stdout=subprocess.PIPE,
        ).stdout
        incoming = target.read_bytes()
        restored = incoming
        if normalize_references:
            restored = normalize_po_references(original, restored)
            if restored != incoming:
                print(f"Normalized PO references: {path}")
        if without_po_timestamps(restored) == without_po_timestamps(original):
            restored = original
            print(f"Ignored timestamp-only change: {path}")
        if restored != incoming:
            target.write_bytes(restored)


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


def resource_exists(resource):
    """Only a resource-level 404 permits skipping an absent download."""
    request = Request(
        "https://rest.api.transifex.com/resources/" + quote(resource, safe=":"),
        headers={"Authorization": f"Bearer {os.environ['TX_TOKEN']}"},
    )
    try:
        with urlopen(request, timeout=30):
            return True
    except HTTPError as error:
        error.close()
        if error.code == 404:
            return False
        raise


def sync(source, destination, language, *, skip_missing_resources=False):
    config = source / ".tx/config"
    catalogs = active_catalogs(config)
    downloaded = source / language / "LC_MESSAGES"
    skipped = set()
    if skip_missing_resources:
        resources = configparser.ConfigParser(interpolation=None)
        resources.read(config, encoding="utf-8")
        # Check every missing download before modifying the repository. Missing
        # translations of existing resources (or API errors) must still fail.
        for section in resources.sections():
            if section == "main":
                continue
            path = Path(PurePosixPath(
                resources[section]["source_file"]
            ).relative_to("pot").with_suffix(".po"))
            if not (downloaded / path).is_file() and not resource_exists(section):
                skipped.add(path)
                print(f"Skipped unavailable Transifex resource: {section} ({path})")
    incoming = [path for path in catalogs if path not in skipped]
    require_catalogs(downloaded, incoming)
    if not incoming:
        raise ValueError("No PO catalogs downloaded; refusing to sync")
    # Keep existing translations of temporarily unavailable resources.
    obsolete = set(tracked_catalogs(destination)) - set(catalogs)

    for path in incoming:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(downloaded / path, target)
    for path in sorted(obsolete):
        (destination / path).unlink(missing_ok=True)
        print(f"Removed obsolete catalog: {path}")
    (destination / ".tx").mkdir(exist_ok=True)
    shutil.copyfile(config, destination / ".tx/config")


def merge(source, destination):
    # The config includes new resources whose translations are not available
    # yet. Merge only tracked catalogs, ignoring stale files outside the config.
    catalogs = sorted(
        set(active_catalogs(source / ".tx/config")) & set(tracked_catalogs(source))
    )
    if not catalogs:
        raise ValueError(f"No source catalogs in {source}")
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
    sync_parser.add_argument(
        "--skip-missing-resources", action="store_true",
        help="skip missing downloads only for resources returning 404",
    )
    merge_parser = commands.add_parser("merge")
    merge_parser.add_argument("source", type=Path)
    merge_parser.add_argument("destination", type=Path)
    restore_parser = commands.add_parser("restore-timestamp-only")
    restore_parser.add_argument("root", type=Path)
    restore_parser.add_argument(
        "--references", action="store_true",
        help="drop references for new/changed messages or source paths and ignore other line-number updates",
    )
    args = parser.parse_args()
    if args.command == "sync":
        sync(args.source, args.destination, args.language,
             skip_missing_resources=args.skip_missing_resources)
    elif args.command == "merge":
        merge(args.source, args.destination)
    else:
        restore_timestamp_only_changes(args.root, normalize_references=args.references)


if __name__ == "__main__":
    main()
