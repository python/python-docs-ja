"""Sync and merge the PO catalogs listed in a generated Transifex config."""

import argparse
import configparser
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess


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
    args = parser.parse_args()
    if args.command == "sync":
        sync(args.source, args.destination, args.language)
    else:
        merge(args.source, args.destination)


if __name__ == "__main__":
    main()
