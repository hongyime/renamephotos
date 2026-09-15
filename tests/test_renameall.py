import contextlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import renameall


class RenameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="renamephotos-test-")
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))

    def tearDown(self) -> None:
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.temporary.cleanup()

    def photo(self, name: str = "photo.jpg", content: bytes = b"synthetic-photo") -> Path:
        path = self.root / name
        path.write_bytes(content)
        return path

    def journal(self) -> list[dict]:
        paths = list(self.root.glob(".renamephotos-*.jsonl"))
        self.assertEqual(len(paths), 1)
        return [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]

    def test_import_does_not_prompt_or_touch_folder(self) -> None:
        self.photo()
        environment = dict(os.environ, PYTHONPATH=str(Path(renameall.__file__).parent))
        result = subprocess.run([sys.executable, "-c", "import renameall"], cwd=self.root,
                                env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual([p.name for p in self.root.iterdir()], ["photo.jpg"])

    def test_plan_accepts_mixed_case_extensions_and_skips_directories(self) -> None:
        names = ["z.JPG", "a.jpeg", "b.PNG", "c.pNg", "d.JPEG", "e.jpg"]
        for name in names:
            self.photo(name)
        self.photo("notes.txt")
        (self.root / "album.jpg").mkdir()
        before = sorted(p.name for p in self.root.iterdir())
        plan = renameall.build_plan(self.root)
        self.assertEqual([entry.source for entry in plan.entries], sorted(names, key=str.casefold))
        for entry in plan.entries:
            self.assertEqual(Path(entry.source).suffix, Path(entry.destination).suffix)
            stem = Path(entry.destination).stem
            self.assertEqual(len(stem), 20)
            self.assertEqual(len(set(stem)), 20)
            self.assertLessEqual(set(stem), set(renameall.ALPHABET))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_symlinks_are_excluded(self) -> None:
        target = self.photo("target.txt")
        link = self.root / "linked.jpg"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        self.assertEqual(renameall.build_plan(self.root).entries, ())
        self.assertTrue(link.is_symlink())

    def test_names_are_reserved_case_insensitively_and_across_the_plan(self) -> None:
        existing = "abcdefghijklmnopqrst"
        first = "bcdefghijklmnopqrstu"
        second = "cdefghijklmnopqrstuv"
        (self.root / (existing.upper() + ".JPG")).mkdir()
        self.photo("a.jpg")
        self.photo("b.jpg")
        with patch.object(renameall, "_new_stem", side_effect=[existing, first, first, second]):
            plan = renameall.build_plan(self.root)
        self.assertEqual([entry.destination for entry in plan.entries], [first + ".jpg", second + ".jpg"])

    def test_exhausted_name_generation_changes_nothing(self) -> None:
        stem = "abcdefghijklmnopqrst"
        self.photo(stem + ".jpg")
        with patch.object(renameall, "_new_stem", return_value=stem) as generator:
            with self.assertRaises(FileExistsError):
                renameall.build_plan(self.root)
        self.assertEqual(generator.call_count, 100)
        self.assertEqual([p.name for p in self.root.iterdir()], [stem + ".jpg"])

    def test_execution_preserves_bytes_extensions_and_permissions(self) -> None:
        photo = self.photo("family_日本.PNG", b"\x00\xfforiginal-photo-bytes")
        mode = stat.S_IMODE(photo.stat().st_mode)
        plan = renameall.build_plan(self.root)
        journal_path = renameall.execute_plan(plan)
        destination = self.root / plan.entries[0].destination
        self.assertFalse(photo.exists())
        self.assertEqual(destination.read_bytes(), b"\x00\xfforiginal-photo-bytes")
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), mode)
        records = self.journal()
        self.assertEqual(records[0]["plan"][0]["source"], photo.name)
        self.assertEqual(records[0]["plan"][0]["destination"], destination.name)
        self.assertEqual(records[-1], {"status": "complete", "renamed": 1})
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(journal_path.stat().st_mode), 0o600)

    def test_preexisting_destination_aborts_before_any_rename(self) -> None:
        first = self.photo("a.jpg", b"first")
        second = self.photo("b.jpg", b"second")
        plan = renameall.build_plan(self.root)
        occupied = self.root / plan.entries[1].destination
        occupied.write_bytes(b"retained-destination")
        with self.assertRaises(FileExistsError):
            renameall.execute_plan(plan)
        self.assertEqual(first.read_bytes(), b"first")
        self.assertEqual(second.read_bytes(), b"second")
        self.assertEqual(occupied.read_bytes(), b"retained-destination")
        self.assertFalse(list(self.root.glob(".renamephotos-*.jsonl")))

    def test_destination_created_after_preflight_is_not_overwritten(self) -> None:
        source = self.photo()
        plan = renameall.build_plan(self.root)
        operation = renameall._rename_operation()

        def racing_rename(src: Path, dst: Path) -> None:
            dst.write_bytes(b"concurrent-destination")
            operation(src, dst)

        with patch.object(renameall, "_rename_operation", return_value=racing_rename):
            with self.assertRaises(FileExistsError):
                renameall.execute_plan(plan)
        self.assertEqual(source.read_bytes(), b"synthetic-photo")
        self.assertEqual((self.root / plan.entries[0].destination).read_bytes(), b"concurrent-destination")
        self.assertEqual(self.journal()[-1]["status"], "stopped")

    def test_changed_source_aborts_whole_plan_before_rename(self) -> None:
        first = self.photo("a.jpg")
        second = self.photo("b.jpg")
        plan = renameall.build_plan(self.root)
        second.write_bytes(b"changed-content")
        with self.assertRaisesRegex(ValueError, "changed"):
            renameall.execute_plan(plan)
        self.assertTrue(first.exists())
        self.assertEqual(second.read_bytes(), b"changed-content")
        self.assertFalse(list(self.root.glob(".renamephotos-*.jsonl")))

    def test_missing_source_aborts_before_rename(self) -> None:
        source = self.photo()
        plan = renameall.build_plan(self.root)
        source.rename(self.root / "moved-by-someone-else.jpg")
        with self.assertRaises(FileNotFoundError):
            renameall.execute_plan(plan)
        self.assertEqual((self.root / "moved-by-someone-else.jpg").read_bytes(), b"synthetic-photo")

    def test_plan_cannot_escape_folder_or_repeat_entries(self) -> None:
        self.photo()
        plan = renameall.build_plan(self.root)
        for target in ["../outside.jpg", "..\\outside.jpg", str(self.root.parent / "outside.jpg")]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                renameall.execute_plan(replace(plan, entries=(replace(plan.entries[0], destination=target),)))
        with self.assertRaises(ValueError):
            renameall.execute_plan(replace(plan, entries=plan.entries * 2))
        self.assertTrue((self.root / "photo.jpg").exists())

    def test_mapping_is_flushed_before_any_rename(self) -> None:
        self.photo()
        plan = renameall.build_plan(self.root)
        operation = renameall._rename_operation()

        def inspect_mapping(src: Path, dst: Path) -> None:
            self.assertEqual(self.journal()[0]["plan"][0]["destination"], dst.name)
            operation(src, dst)

        with patch.object(renameall, "_rename_operation", return_value=inspect_mapping):
            renameall.execute_plan(plan)

    def test_journal_sync_failure_prevents_first_rename(self) -> None:
        source = self.photo()
        plan = renameall.build_plan(self.root)
        with patch.object(renameall.os, "fsync", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                renameall.execute_plan(plan)
        self.assertEqual(source.read_bytes(), b"synthetic-photo")

    def test_partial_failure_preserves_completed_mapping_and_remaining_sources(self) -> None:
        self.photo("a.jpg", b"a")
        self.photo("b.jpg", b"b")
        self.photo("c.jpg", b"c")
        plan = renameall.build_plan(self.root)
        operation = renameall._rename_operation()

        def fail_second(src: Path, dst: Path) -> None:
            if src.name == "b.jpg":
                raise PermissionError("fixture lock")
            operation(src, dst)

        with patch.object(renameall, "_rename_operation", return_value=fail_second):
            with self.assertRaises(PermissionError):
                renameall.execute_plan(plan)
        self.assertEqual((self.root / plan.entries[0].destination).read_bytes(), b"a")
        self.assertEqual((self.root / "b.jpg").read_bytes(), b"b")
        self.assertEqual((self.root / "c.jpg").read_bytes(), b"c")
        records = self.journal()
        self.assertEqual(len(records[0]["plan"]), 3)
        self.assertEqual([r.get("status") for r in records[1:]], ["renamed", "stopped"])

    def test_result_sync_failure_stops_later_renames(self) -> None:
        self.photo("a.jpg", b"a")
        self.photo("b.jpg", b"b")
        plan = renameall.build_plan(self.root)
        with patch.object(renameall.os, "fsync", side_effect=[None, OSError("disk unavailable"), OSError("disk unavailable")]):
            with self.assertRaises(OSError):
                renameall.execute_plan(plan)
        self.assertEqual((self.root / plan.entries[0].destination).read_bytes(), b"a")
        self.assertEqual((self.root / "b.jpg").read_bytes(), b"b")
        self.assertEqual(len(self.journal()[0]["plan"]), 2)

    def test_interruption_after_native_rename_keeps_recovery_mapping(self) -> None:
        self.photo()
        plan = renameall.build_plan(self.root)
        operation = renameall._rename_operation()

        def interrupted(src: Path, dst: Path) -> None:
            operation(src, dst)
            raise KeyboardInterrupt

        with patch.object(renameall, "_rename_operation", return_value=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                renameall.execute_plan(plan)
        self.assertEqual((self.root / plan.entries[0].destination).read_bytes(), b"synthetic-photo")
        self.assertEqual(self.journal()[0]["plan"][0]["destination"], plan.entries[0].destination)

    def test_cli_preview_and_decline_write_nothing(self) -> None:
        self.photo()
        for args in [[str(self.root), "--dry-run"], [str(self.root)]]:
            with patch("builtins.input", return_value="n"), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(renameall.main(args), 0)
            self.assertEqual([p.name for p in self.root.iterdir()], ["photo.jpg"])

    def test_cli_yes_executes_and_empty_folder_is_noop(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(renameall.main([str(self.root), "--yes"]), 0)
            self.assertEqual(list(self.root.iterdir()), [])
            self.photo()
            self.assertEqual(renameall.main([str(self.root), "--yes"]), 0)
        self.assertEqual(len(list(self.root.glob("*.jpg"))), 1)
        self.assertEqual(self.journal()[-1]["status"], "complete")

    def test_cli_invalid_input_and_filesystem_failure_return_nonzero(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), patch("builtins.input", return_value=""):
            self.assertEqual(renameall.main([]), 1)
            self.assertEqual(renameall.main([str(self.root / "missing")]), 1)
        self.photo()
        with patch.object(renameall, "_rename_operation", side_effect=OSError("unsupported filesystem")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(renameall.main([str(self.root), "--yes"]), 1)
        self.assertTrue((self.root / "photo.jpg").exists())


if __name__ == "__main__":
    unittest.main()
