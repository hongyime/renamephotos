# PRD: renamephotos

## Overview

A standard-library Python CLI that renames photos within a selected folder to
random 20-character names. Names contain distinct lowercase letters/digits and
retain the source extension. Renaming changes filenames, not image contents or
embedded metadata.

## Goals

- Accept a folder argument or prompt, and show the complete proposed mapping.
- Support JPG, JPEG and PNG extensions with any capitalization.
- Select regular files only; skip symlinks and directories without recursion.
- Reserve names case-insensitively and bound collision retries.
- Require confirmation or `--yes`; provide a read-only `--dry-run`.
- Refuse existing destinations atomically at execution time.
- Flush the complete original/new mapping before the first rename.
- Stop on errors or interruption with a nonzero status and recoverable mappings.
- Keep imports free of interactive prompts and renaming.

## Non-goals

Image conversion, content-based duplicate detection, metadata removal, cloud
storage, recursive processing, a GUI and automatic undo/rollback are outside
this utility. A batch is not an all-or-nothing transaction.

## Execution

`build_plan` scans and reserves names without writing. `execute_plan` rechecks
the whole plan and source identities, creates an exclusive JSONL mapping, then
performs native no-replace renames and records their results. Unsupported native
operations fail without an unsafe fallback. `main` owns arguments, preview,
confirmation, success/error output and exit status.

The tool supports Python 3.10+ on Windows, Linux and macOS. Linux filesystems
must support `RENAME_NOREPLACE`; macOS uses `RENAME_EXCL`. Contents are never
copied, decoded or rewritten by the utility. Other applications should not
replace or edit files during a batch. The mapping supports manual recovery;
it is not a content backup or a filesystem crash-recovery guarantee.

## Validation

Use `python -m unittest discover -s tests -v`. Hosted checks exercise real native
rename behavior on all three supported operating systems with synthetic files.
