# renamephotos

**Live:** https://hongyime.github.io/renamephotos/

![screenshot](./screenshot.png)
Rename photos directly inside a folder to random 20-character alphanumeric
filenames. JPG, JPEG and PNG extensions are matched case-insensitively, and each
file keeps its original extension spelling. Image contents and embedded metadata
are unchanged. Directories, symlinks and other file types are skipped.

## Run

Use Python 3.10 or newer on Windows, Linux or macOS. No third-party packages are
needed. Double-click `renameall.py`, or run:

```bash
python renameall.py
python renameall.py "/path/to/photos" --dry-run
python renameall.py "/path/to/photos" --yes
```

Without `--yes`, the program shows the proposed names and asks before applying
them. The default answer is no. `--dry-run` only previews: it does not rename
files or create a mapping journal. Importing the module never prompts or renames.

## Preserving files and names

The entire plan is checked before execution. Existing names, including names
that differ only in case, are reserved while new names are generated. Each move
uses a native operation that refuses to replace an existing destination, even
if it appears after the initial check. Unsupported platforms or filesystems
stop with an error; there is no overwriting fallback.

Before the first rename, the program creates and flushes a private
`.renamephotos-<id>.jsonl` mapping in the photo folder. Its first line contains
all original and proposed names. Later lines record completed moves and normal
completion. Keep this file if you need the original names.

A batch stops at its first failure or interruption. Earlier successful renames
remain in place; remaining sources retain their names. An interruption may occur
between a move and its result record, so inspect both names using the complete
first-line mapping before recovery. There is no automatic rollback or undo.
Keep other applications from editing or replacing files in the folder while the
batch runs. The journal is not a backup of image contents or a guarantee against
filesystem or power-loss corruption.

Atomic non-replacement uses Windows `os.rename`, Linux `renameat2` with
`RENAME_NOREPLACE`, or macOS `renamex_np` with `RENAME_EXCL`. See the
[Python rename documentation](https://docs.python.org/3/library/os.html#os.rename),
[Linux rename documentation](https://man7.org/linux/man-pages/man2/rename.2.html),
and [Apple interface definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h).

## Tests

```bash
python -m unittest discover -s tests -v
```

CI runs temporary-file tests on Windows, Linux and macOS. Tests cover import
behavior, previews, file selection, collisions, native non-replacement,
changed sources, partial execution and recovery mappings. They do not open or
rename an existing photo collection.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
