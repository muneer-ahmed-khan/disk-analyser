# Disk Analyser

A read-only disk space analyser for John Crickett's [Coding Challenge #145](https://codingchallenges.substack.com/p/coding-challenge-145-disk-analyser). It walks a directory without following symbolic links, reports allocated and apparent size separately, counts hard-linked storage once, ranks large files, and shows a terminal treemap overview.

## Run

Requires Python 3.11+; there are no runtime dependencies.

```sh
python3 -m diskanalyser /path/to/folder
# interactive keyboard UI
python3 -m diskanalyser --interactive /path/to/folder
```

From this project directory:

```sh
PYTHONPATH=src python3 -m diskanalyser ~/Downloads
PYTHONPATH=src python3 -m diskanalyser -i ~/Downloads
```

Or install in a virtual environment with `python3 -m pip install .`, then run `disk-analyser ~/Downloads`. Use `--largest 20` to change the ranked list, `--min-size 104857600 --older-days 365` to filter it, or `--apparent` to select apparent size as the headline and ranking metric. Progress is printed while scanning.

Interactive keys: `j/k` select, `Enter` opens a folder, `Backspace` goes up, `a` toggles age colours, `s` toggles allocated/apparent size, `Space` stages/unstages, `r` reviews, and `q` exits. Cleanup remains staged until the review screen and a second `y` confirmation. Eligible items are moved to the user's recoverable Trash. The tool rechecks path scope, type, inode and modification timestamp immediately before moving each one and reports skipped items.

## What it measures

- File apparent size comes from `st_size`; allocated size uses filesystem block metadata (`st_blocks × 512`). Some filesystems do not expose allocated blocks, in which case allocated size reports zero.
- Hard links appear as separate names, but allocated bytes are charged to only the first encountered name. Symlinks are listed and never followed.
- Directories total descendant values. Directory age uses the newest mtime in the subtree.
- The size ranking excludes symlinks and sorts files by allocated bytes. Candidate folders include common generated output and cache names. These labels are heuristics, not a promise that removal is safe.
- The interactive treemap uses squarified rectangles, age bands, selection, directory navigation, and terminal resize redraws.

Scanning is strictly read-only. The separately confirmed cleanup flow only moves reviewed, staged items to Trash; it never permanently deletes them. Filesystem free space may not rise until Trash is emptied.

## Challenge coverage

| Challenge area | Status |
| --- | --- |
| Read-only scan, warnings, no symlink traversal | Implemented |
| Apparent and allocated sizes; directory totals | Implemented |
| Hard-link de-duplication, progress | Implemented |
| Terminal treemap overview | Basic slice view implemented |
| Interactive selection, navigation, inspector | Implemented in the terminal UI |
| Age colouring and age-filtered ranking | Implemented |
| Reclaimable-folder heuristics | Common cache and generated folder names |
| Staging, review, protected-path checks and Trash | Implemented; identity is rechecked before moving |

## Check

Run `python3 -m unittest discover -s tests -v` from this directory. The tests build temporary fixtures; they do not alter your personal files.
