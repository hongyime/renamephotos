# PRD: renamephotos

## Overview
A Python CLI script that renames all photos in a specified folder to random 20-character alphanumeric filenames while preserving the original extension. Useful for anonymizing photo collections before sharing or for breaking sequential filenames from camera exports.

## Goals
- Accept a folder path as user input
- Rename all `.jpg`, `.jpeg`, `.png`, `.JPG` files to random 20-char names
- Preserve file extensions
- Print old and new filename for each rename

## Non-Goals
- Recursive subdirectory processing
- Undo/rollback functionality
- Support for video files (`.mov`, `.mp4`, `.mp3` — commented out)
- Duplicate detection or collision handling
- GUI

## User Stories
- As a photographer, I want to strip sequential camera filenames (DSC_0001.jpg) before sharing a folder.
- As a developer, I want to anonymize a test dataset of images with unpredictable names.

## Tech Stack
- **Language**: Python 3.x
- **Libraries**: `os`, `random`, `string` (all stdlib)

## Architecture
```
renamephotos/
└── renameall.py    # single-file script
```

**Logic:**
1. Prompt user for folder path
2. `os.listdir(folder)` to get all files
3. For each file with supported extension:
   - Generate 20-char random name from `[a-z0-9]`
   - `os.rename(src, dst)`
   - Print `renamed X to Y`
4. Print "All done"

## Features (detailed)

### Random Name Generation
- Uses `random.sample(ascii_lowercase + digits, 20)` — samples without replacement
- Guarantees 20 unique characters from 36-char pool
- Preserves original extension (`.jpg`, `.jpeg`, `.png`, `.JPG`)

### Supported Extensions
- `.jpg`, `.jpeg`, `.png`, `.JPG`
- Skips all other files (including `.mov`, `.mp4` — commented out but easily re-enabled)

## Data / Config
No config file. Single input: folder path entered at runtime.

## Deployment / Run
```bash
python renameall.py
# Enter folder path when prompted
```

## Constraints & Notes
- **No collision check**: `random.sample` without replacement gives 20 unique chars but doesn't check if the generated name already exists in the folder — extremely unlikely collision but not impossible at scale
- **Irreversible**: no backup or undo; original names are gone after rename
- **Non-recursive**: only processes files directly in the specified folder, not subdirectories
- **Case-sensitive extension**: `.JPG` handled separately from `.jpg`; `.JPEG` or `.PNG` are not handled
