"""Preview and journal photo renames without replacing existing destinations."""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
import errno
from functools import lru_cache
import json
import os
from pathlib import Path
from random import SystemRandom
import stat
import string
import sys
from typing import Callable, TextIO
from uuid import uuid4

EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALPHABET = string.ascii_lowercase + string.digits


@dataclass(frozen=True)
class Rename:
    source: str
    destination: str
    identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class Plan:
    folder: Path
    entries: tuple[Rename, ...]


def _identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Not a regular file: {path.name!r}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _new_stem() -> str:
    return "".join(SystemRandom().sample(ALPHABET, 20))


def build_plan(folder: str | Path) -> Plan:
    root = Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    children = sorted(root.iterdir(), key=lambda path: (path.name.casefold(), path.name))
    reserved = {path.name.casefold() for path in children}
    entries = []
    for source in children:
        if source.suffix.lower() not in EXTENSIONS or not stat.S_ISREG(source.lstat().st_mode):
            continue
        identity = _identity(source)
        for _ in range(100):
            name = _new_stem() + source.suffix
            if name.casefold() not in reserved:
                reserved.add(name.casefold())
                entries.append(Rename(source.name, name, identity))
                break
        else:
            raise FileExistsError("Could not reserve a unique photo name; no files were renamed")
    return Plan(root, tuple(entries))


def _validate(plan: Plan) -> None:
    if plan.folder.resolve(strict=True) != plan.folder or not plan.folder.is_dir():
        raise ValueError("The selected folder changed after planning")
    existing = {path.name.casefold() for path in plan.folder.iterdir()}
    sources: set[str] = set()
    targets: set[str] = set()
    for entry in plan.entries:
        for name in (entry.source, entry.destination):
            if Path(name).name != name or name in {"", ".", ".."} or "/" in name or "\\" in name:
                raise ValueError("Rename entries must stay directly inside the selected folder")
        if entry.source.casefold() in sources or entry.destination.casefold() in targets:
            raise ValueError("Duplicate entry in rename plan")
        if entry.destination.casefold() in existing:
            raise FileExistsError(f"Destination already exists: {entry.destination!r}")
        if _identity(plan.folder / entry.source) != entry.identity:
            raise ValueError(f"Source changed after planning: {entry.source!r}")
        sources.add(entry.source.casefold())
        targets.add(entry.destination.casefold())


@lru_cache(maxsize=1)
def _rename_operation() -> Callable[[Path, Path], None]:
    if os.name == "nt":
        # Python's Windows rename always refuses an existing destination.
        return os.rename
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int

        def invoke(source: bytes, destination: bytes) -> int:
            return function(-100, source, -100, destination, 1)  # AT_FDCWD, RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(library, "renamex_np"):
        function = library.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int

        def invoke(source: bytes, destination: bytes) -> int:
            return function(source, destination, 4)  # RENAME_EXCL
    else:
        raise OSError(errno.ENOTSUP, "Atomic rename without replacement is unavailable on this platform")

    def rename(source: Path, destination: Path) -> None:
        if invoke(os.fsencode(source), os.fsencode(destination)) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(destination))

    return rename


def _record(journal: TextIO, event: dict) -> None:
    journal.write(json.dumps(event) + "\n")
    journal.flush()
    os.fsync(journal.fileno())


def execute_plan(plan: Plan) -> Path | None:
    """Stop on the first failure, retaining a prewritten mapping for recovery."""
    _validate(plan)
    if not plan.entries:
        return None
    rename = _rename_operation()
    journal_path = plan.folder / f".renamephotos-{uuid4().hex}.jsonl"
    descriptor = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as journal:
        _record(journal, {"version": 1, "folder": str(plan.folder), "plan": [asdict(entry) for entry in plan.entries]})
        for entry in plan.entries:
            try:
                if _identity(plan.folder / entry.source) != entry.identity:
                    raise ValueError(f"Source changed after planning: {entry.source!r}")
                rename(plan.folder / entry.source, plan.folder / entry.destination)
                _record(journal, {"status": "renamed", "source": entry.source, "destination": entry.destination})
            except (OSError, ValueError, KeyboardInterrupt) as exc:
                try:
                    _record(journal, {"status": "stopped", "source": entry.source, "error": type(exc).__name__})
                except OSError:
                    pass  # The complete mapping was flushed before the first rename.
                raise
        _record(journal, {"status": "complete", "renamed": len(plan.entries)})
    return journal_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", help="Folder containing the photos (not recursive)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview without renaming or writing a journal")
    mode.add_argument("--yes", action="store_true", help="Apply the displayed plan without a confirmation prompt")
    args = parser.parse_args(argv)
    try:
        folder = args.folder if args.folder is not None else input("Where are the photos: ")
        if not folder.strip():
            raise ValueError("A folder path is required")
        plan = build_plan(folder)
        if not plan.entries:
            print("No supported regular images found.")
            return 0
        for entry in plan.entries:
            print(f"{entry.source!r} -> {entry.destination}")
        if args.dry_run:
            print(f"Preview only: {len(plan.entries)} files; nothing changed.")
            return 0
        if not args.yes and input(f"Rename {len(plan.entries)} files? [y/N] ").strip().lower() != "y":
            print("Cancelled; nothing changed.")
            return 0
        journal = execute_plan(plan)
        print(f"Renamed {len(plan.entries)} files. Keep the name mapping: {journal}")
        return 0
    except (OSError, ValueError, EOFError) as exc:
        print(f"Stopped: {exc}. If execution began, keep the .renamephotos-*.jsonl mapping in that folder.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Keep any .renamephotos-*.jsonl mapping before resuming.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
