"""Filesystem scanning and treemap layout primitives."""

from __future__ import annotations

import os
import stat
import time
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class Item:
    path: Path
    kind: str
    apparent: int = 0
    disk: int = 0
    mtime: float = 0
    inode_key: tuple[int, int] | None = None
    children: list["Item"] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(c.count for c in self.children) if self.kind == "directory" else int(self.kind == "file")


def scan(root: Path, progress=None) -> Item:
    """Walk without following symlinks. Count allocated storage once per inode."""
    root = root.expanduser().resolve(strict=True)
    seen: set[tuple[int, int]] = set()
    scanned = 0
    total = 0

    def visit(path: Path) -> Item:
        nonlocal scanned, total
        try:
            st = path.lstat()
        except OSError as exc:
            return Item(path, "unreadable", warnings=[str(exc)])
        scanned += 1
        kind = "symlink" if stat.S_ISLNK(st.st_mode) else "directory" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
        inode = (st.st_dev, st.st_ino) if kind == "file" else None
        disk = int(getattr(st, "st_blocks", 0) * 512)
        if kind == "file":
            if inode in seen:
                disk = 0
            else:
                seen.add(inode)
        item = Item(path, kind, int(st.st_size) if kind in ("file", "symlink") else 0, disk, st.st_mtime, inode)
        if kind == "directory":
            try:
                with os.scandir(path) as entries:
                    names = sorted((Path(e.path) for e in entries), key=lambda p: p.name.casefold())
                for child in names:
                    item.children.append(visit(child))
            except OSError as exc:
                item.warnings.append(f"cannot read directory: {exc}")
            item.apparent = sum(c.apparent for c in item.children)
            item.disk = sum(c.disk for c in item.children)
            item.mtime = max([item.mtime, *(c.mtime for c in item.children)])
        total += item.disk
        if progress and scanned % 128 == 0:
            progress(scanned, total)
        return item

    result = visit(root)
    if progress:
        progress(scanned, result.disk)
    return result


def walk(item: Item) -> Iterator[Item]:
    yield item
    for child in item.children:
        yield from walk(child)


def human(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


def reclaimable(item: Item) -> bool:
    parts = {p.casefold() for p in item.path.parts}
    name = item.path.name.casefold()
    known = {"node_modules", "target", "build", "dist", ".next", "__pycache__"}
    return name in known or name == ".cache" or (name == "caches" and "library" in parts)


def largest(root: Item, limit: int = 10, minimum: int = 0, older_days: int | None = None, now: float | None = None, apparent: bool = False) -> list[Item]:
    cutoff = (now or time.time()) - older_days * 86400 if older_days is not None else None
    files = (x for x in walk(root) if x.kind == "file" and (x.apparent if apparent else x.disk) >= minimum and (cutoff is None or x.mtime <= cutoff))
    return sorted(files, key=lambda x: (-(x.apparent if apparent else x.disk), str(x.path)))[:limit]


def squarify(items: list[Item], x: float, y: float, width: float, height: float, apparent: bool = False) -> list[tuple[Item, float, float, float, float]]:
    """Lay out items using a compact squarified treemap approximation."""
    weight = lambda i: i.apparent if apparent else i.disk
    total = sum(weight(i) for i in items)
    if not items or width <= 0 or height <= 0:
        return []
    if total == 0:
        total = len(items)
        weight = lambda _i: 1
    scaled = sorted(((weight(i) * width * height / total, i) for i in items), reverse=True, key=lambda x: x[0])
    result = []
    rect = [x, y, width, height]

    def worst(row, side):
        if not row or side <= 0:
            return float("inf")
        area = sum(a for a, _ in row)
        largest, smallest = max(a for a, _ in row), min(a for a, _ in row)
        return max(side * side * largest / (area * area), area * area / (side * side * smallest))

    while scaled:
        side = min(rect[2], rect[3])
        row = []
        while scaled and (not row or worst(row + [scaled[0]], side) <= worst(row, side)):
            row.append(scaled.pop(0))
        area = sum(a for a, _ in row)
        if rect[2] >= rect[3]:
            strip = area / rect[3] if rect[3] else 0
            cursor = rect[1]
            for a, item in row:
                h = a / strip if strip else 0
                result.append((item, rect[0], cursor, strip, h))
                cursor += h
            rect[0] += strip
            rect[2] -= strip
        else:
            strip = area / rect[2] if rect[2] else 0
            cursor = rect[0]
            for a, item in row:
                w = a / strip if strip else 0
                result.append((item, cursor, rect[1], w, strip))
                cursor += w
            rect[1] += strip
            rect[3] -= strip
    return result


PROTECTED = {Path("/"), Path("/System"), Path("/usr"), Path("/bin"), Path("/etc"), Path("/sbin"), Path("/var")}


def stageable(path: Path, root: Path) -> tuple[bool, str]:
    resolved_root = root.resolve()
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(resolved_root):
        return False, "outside the scan root"
    if resolved in PROTECTED or any(parent in PROTECTED and parent != Path("/") for parent in resolved.parents):
        return False, "protected system path"
    if resolved == resolved_root:
        return False, "the scan root cannot be staged"
    try:
        path.lstat()
    except OSError as exc:
        return False, f"item is unavailable: {exc}"
    return True, ""


def staged_size(paths: set[Path], root: Path) -> int:
    """Compute union allocation without double-counting nested stages/hardlinks."""
    canonical = []
    for path in sorted(paths, key=lambda p: len(p.parts)):
        if not any(path == parent or path.is_relative_to(parent) for parent in canonical):
            canonical.append(path)
    seen: set[tuple[int, int]] = set()
    total = 0
    for path in canonical:
        try:
            item = scan(path)
        except (OSError, ValueError):
            continue
        for node in walk(item):
            if node.kind == "file" and node.inode_key and node.inode_key not in seen:
                seen.add(node.inode_key)
                total += node.disk
    return total


def trash_path(path: Path) -> Path:
    """Move to a recoverable per-user Trash location, never unlink permanently."""
    home = Path.home()
    if sys_platform() == "darwin":
        trash = home / ".Trash"
    else:
        trash = home / ".local/share/Trash/files"
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / path.name
    suffix = 1
    while target.exists():
        target = trash / f"{path.name}.{suffix}"
        suffix += 1
    shutil.move(str(path), str(target))
    return target


def sys_platform() -> str:
    import sys
    return sys.platform
