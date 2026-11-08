from __future__ import annotations

import argparse
import shutil
import sys
import curses
import os
import stat
import time
from pathlib import Path

from .core import Item, human, largest, reclaimable, scan, walk, stageable, staged_size, trash_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="disk-analyser", description="Read-only disk usage analyser")
    parser.add_argument("path", nargs="?", type=Path, default=Path.cwd(), help="directory to scan")
    parser.add_argument("--apparent", action="store_true", help="rank using apparent size")
    parser.add_argument("--largest", type=int, default=10, metavar="N", help="number of largest files to show")
    parser.add_argument("--interactive", "-i", action="store_true", help="open the interactive treemap and cleanup review")
    parser.add_argument("--min-size", type=int, default=0, help="minimum allocated bytes for ranked files")
    parser.add_argument("--older-days", type=int, help="rank only files at least this many days old")
    args = parser.parse_args(argv)
    try:
        root = scan(args.path, lambda count, size: print(f"\rScanned {count:,} items · {human(size)} allocated", end="", file=sys.stderr, flush=True))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(file=sys.stderr)
    if args.interactive:
        curses.wrapper(lambda screen: interactive(screen, root))
        return 0
    metric = "apparent" if args.apparent else "disk"
    bytes_total = getattr(root, metric)
    nodes = list(walk(root))
    files = sum(i.kind == "file" for i in nodes)
    links = sum(i.kind == "symlink" for i in nodes)
    errors = [(i.path, warning) for i in nodes for warning in i.warnings]
    candidates = [i for i in nodes if i.kind == "directory" and reclaimable(i)]
    # Nested generated/cache roots overlap; report only outermost candidates.
    candidates = [i for i in candidates if not any(i.path != p.path and i.path.is_relative_to(p.path) for p in candidates)]
    print(f"Disk Analyser — {root.path}")
    print(f"Totals: {human(root.disk)} allocated on disk · {human(root.apparent)} apparent file size")
    print(f"Files: {files:,} paths (hard-link names count separately) · {links:,} symlinks")
    if candidates:
        print(f"Possible reclaimable space (folder-name estimate, review before cleanup): {human(sum(i.disk for i in candidates))}")
    print("\nLargest files (allocated size):")
    for item in largest(root, args.largest, args.min_size, args.older_days, apparent=args.apparent):
        print(f"  {human(item.apparent if args.apparent else item.disk):>10}  {item.path}")
    print("\nLargest directories:")
    dirs = sorted((i for i in nodes if i.kind == "directory" and i is not root), key=lambda i: -i.disk)[:args.largest]
    for item in dirs:
        mark = "  [rebuildable/cache candidate]" if reclaimable(item) else ""
        print(f"  {human(item.disk):>10}  {item.path}{mark}")
    print("\nTreemap — largest immediate children (area proportional to allocated bytes; labels may be shortened):")
    show_treemap(root, shutil.get_terminal_size((88, 24)).columns)
    if errors:
        print(f"\nWarnings ({len(errors)}):")
        for path, message in errors[:30]:
            print(f"  {path}: {message}")
        if len(errors) > 30:
            print(f"  … and {len(errors)-30} more")
    return 0


def interactive(screen, root: Item) -> None:
    """Keyboard treemap browser with staged review and identity rechecks."""
    current = root
    selected = 0
    staged: dict[Path, tuple[int, int, int, int]] = {}
    age_view = False
    apparent = False
    message = "j/k move · Enter open · Backspace up · space stage · r review · a age · s size · q quit"
    screen.keypad(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
    while True:
        screen.erase()
        h, w = screen.getmaxyx()
        kids = sorted(current.children, key=lambda i: -(i.apparent if apparent else i.disk))
        selected = min(selected, max(0, len(kids)-1))
        screen.addnstr(0, 0, f"Disk Analyser  {current.path}  [{('apparent' if apparent else 'allocated')}]", w-1)
        screen.addnstr(1, 0, "Age bands: <30d green · <1y yellow · ≥1y red" if age_view else "Treemap rectangles are proportional to the selected size metric", w-1)
        if kids:
            for idx, (item, x, y, rw, rh) in enumerate(__import__("diskanalyser.core", fromlist=["squarify"]).squarify(kids, 0, 0, max(1, w-1), max(1, h-7), apparent)):
                row, col = 3 + int(y), int(x)
                if row >= h-4 or col >= w-1:
                    continue
                cw, ch = max(1, min(int(rw), w-col-1)), max(1, min(int(rh), h-row-4))
                age = time.time() - item.mtime
                color = curses.color_pair(1 if age < 30*86400 else 2 if age < 365*86400 else 3) if age_view and curses.has_colors() else 0
                if idx == selected:
                    color |= curses.A_REVERSE
                if item.path in staged:
                    color |= curses.A_BOLD
                label = f"{item.path.name}{'/' if item.kind == 'directory' else ''} {human(item.apparent if apparent else item.disk)}"
                try:
                    screen.addnstr(row, col, (label[:max(1, cw-1)]).ljust(min(cw, max(1, w-col-1))), min(cw, max(1, w-col-1)), color)
                    if ch > 1:
                        for rr in range(row+1, min(row+ch, h-4)):
                            screen.addnstr(rr, col, " " * min(cw, w-col-1), min(cw, w-col-1), color)
                except curses.error:
                    pass
            item = kids[selected]
            share = item.disk / current.disk * 100 if current.disk else 0
            screen.addnstr(h-3, 0, f"Selected: {item.path} · disk {human(item.disk)} · apparent {human(item.apparent)} · {share:.1f}% of parent · {time.ctime(item.mtime)}", w-1)
            if item.kind == "directory":
                tops = sorted(item.children, key=lambda x: -x.disk)[:3]
                screen.addnstr(h-2, 0, "Largest: " + " | ".join(f"{x.path.name} {human(x.disk)}" for x in tops), w-1)
        free = shutil.disk_usage(root.path).free
        staged_paths = set(staged)
        total_staged = staged_size(staged_paths, root.path)
        screen.addnstr(h-1, 0, f"{message} · staged {human(total_staged)} · free {human(free)} → {human(free+total_staged)}", w-1)
        screen.refresh()
        key = screen.getch()
        message = ""
        if key in (ord('q'), 27):
            return
        if key in (curses.KEY_DOWN, ord('j')):
            selected = min(selected + 1, max(0, len(kids)-1))
        elif key in (curses.KEY_UP, ord('k')):
            selected = max(0, selected-1)
        elif key in (10, 13, curses.KEY_RIGHT) and kids and kids[selected].kind == "directory":
            current, selected = kids[selected], 0
        elif key in (curses.KEY_BACKSPACE, 127, 8, curses.KEY_LEFT) and current is not root:
            current, selected = next((p for p in walk(root) if current in p.children), root), 0
        elif key == ord('a'):
            age_view = not age_view
        elif key == ord('s'):
            apparent = not apparent
        elif key == ord(' ' ) and kids:
            item = kids[selected]
            ok, reason = stageable(item.path, root.path)
            if not ok:
                message = "Cannot stage: " + reason
            elif item.path in staged:
                del staged[item.path]
                message = "Unstaged " + str(item.path)
            else:
                st = item.path.lstat()
                staged[item.path] = (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode), st.st_mtime_ns)
                message = "Staged (filesystem unchanged): " + str(item.path)
        elif key == ord('r'):
            current_path = current.path
            staged = review(screen, root, staged)
            root = scan(root.path)
            current = next((i for i in walk(root) if i.path == current_path), root)


def review(screen, root: Item, staged: dict[Path, tuple[int, int, int, int]]):
    paths = list(staged)
    selected = 0
    while True:
        screen.erase()
        h, w = screen.getmaxyx()
        screen.addnstr(0, 0, "Cleanup review — nothing has moved yet", w-1)
        lines = []
        for path in paths:
            try:
                item = scan(path)
                lines.append(f"{human(item.disk):>10} {path}")
            except OSError:
                lines.append(f"  missing   {path}")
        for idx, line in enumerate(lines[:max(1,h-4)]):
            screen.addnstr(idx+2, 0, line, w-1, curses.A_REVERSE if idx == selected else 0)
        size = staged_size(set(paths), root.path)
        screen.addnstr(h-2, 0, f"Union total {human(size)} · ↑/↓ select, x remove from set, c confirm to Trash, Esc cancel", w-1)
        screen.refresh()
        key = screen.getch()
        if key == 27:
            return staged
        if key in (curses.KEY_DOWN, ord('j')) and paths:
            selected = min(selected + 1, len(paths)-1)
        elif key in (curses.KEY_UP, ord('k')) and paths:
            selected = max(selected - 1, 0)
        elif key == ord('x') and paths:
            removed = paths.pop(selected)
            staged.pop(removed, None)
            selected = min(selected, max(0, len(paths)-1))
        elif key == ord('c'):
            screen.addnstr(h-1, 0, "Move reviewed set to Trash? Press y to confirm, any other key cancels", w-1)
            screen.refresh()
            if screen.getch() != ord('y'):
                return staged
            moved = []
            failures = []
            for path in list(paths):
                allowed, why = stageable(path, root.path)
                try:
                    st = path.lstat()
                    expected = staged[path]
                    identity = (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode), st.st_mtime_ns)
                    if not allowed:
                        raise OSError(why)
                    if identity != expected:
                        raise OSError("item changed since staging")
                    trash_path(path)
                    moved.append(path)
                except OSError as exc:
                    failures.append(f"Skipped {path}: {exc}")
            detail = [f"Moved to Trash: {len(moved)} item(s), {human(staged_size(set(moved), root.path))}", f"Volume free now: {human(shutil.disk_usage(root.path).free)}"] + failures
            screen.erase()
            for idx, line in enumerate(detail[:h-2]):
                screen.addnstr(idx, 0, line, w-1)
            screen.addnstr(h-1, 0, "Press any key to return", w-1)
            screen.refresh()
            screen.getch()
            return {}


def show_treemap(root: Item, width: int) -> None:
    children = sorted(root.children, key=lambda x: -x.disk)
    if not children:
        print("  (empty)")
        return
    visible = children[:min(len(children), 8)]
    rest = children[len(visible):]
    weights = [i.disk for i in visible]
    if rest:
        visible.append(Item(root.path / "smaller items", "group", disk=sum(i.disk for i in rest)))
        weights.append(sum(i.disk for i in rest))
    total = sum(weights) or len(visible)
    remaining = width
    for index, (item, value) in enumerate(zip(visible, weights)):
        cells = remaining if index == len(visible)-1 else max(1, round(width * (value or 1) / total))
        label = f"{item.path.name}/" if item.kind == "directory" else item.path.name
        label += f" {human(value)}"
        print("  " + label[:max(1, cells-2)].ljust(max(1, cells-2)) + "│")
        remaining -= cells
    for item in children[:8]:
        if item.kind == "directory":
            print(f"    {item.path.name}/  {human(item.disk)}")
            for child in sorted(item.children, key=lambda x: -x.disk)[:3]:
                print(f"      {human(child.disk):>9}  {child.path.name}{' →' if child.kind == 'symlink' else ''}")


if __name__ == "__main__":
    raise SystemExit(main())
