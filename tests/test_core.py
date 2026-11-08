import os
import tempfile
import unittest
from pathlib import Path

from diskanalyser.core import largest, scan, squarify, staged_size, stageable


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hardlink_symlink_and_sparse_file(self):
        (self.root / "a").write_bytes(b"x" * 8192)
        os.link(self.root / "a", self.root / "b")
        os.symlink("a", self.root / "link")
        with (self.root / "sparse").open("wb") as f:
            f.truncate(2**20)
        result = scan(self.root)
        self.assertEqual(result.apparent, sum(p.lstat().st_size for p in self.root.iterdir()))
        self.assertEqual(sum(c.disk for c in result.children if c.path.name in {"a", "b"}), (self.root / "a").stat().st_blocks * 512)
        self.assertEqual(next(c for c in result.children if c.path.name == "link").kind, "symlink")
        self.assertEqual(len(largest(result, 1)), 1)

    def test_nested_staging_union_and_safety(self):
        folder = self.root / "build"
        folder.mkdir()
        (folder / "x").write_bytes(b"data")
        file = self.root / "other"
        file.write_bytes(b"hello")
        self.assertEqual(staged_size({folder, folder / "x"}, self.root), scan(folder).disk)
        self.assertEqual(stageable(folder, self.root), (True, ""))
        self.assertFalse(stageable(self.root, self.root)[0])
        self.assertFalse(stageable(self.root.parent / "outside", self.root)[0])

    def test_treemap_preserves_area(self):
        a, b = type("I", (), {"disk": 3, "apparent": 3})(), type("I", (), {"disk": 1, "apparent": 1})()
        rects = squarify([a, b], 0, 0, 100, 50)
        self.assertAlmostEqual(sum(w*h for _, _, _, w, h in rects), 5000)
        self.assertAlmostEqual(next(w*h for i, _, _, w, h in rects if i is a), 3750)

    def test_treemap_ignores_zero_area_entries(self):
        zero = type("I", (), {"disk": 0, "apparent": 0})()
        nonzero = type("I", (), {"disk": 2048, "apparent": 2048})()
        rects = squarify([zero, nonzero], 0, 0, 80, 24)
        self.assertEqual([entry[0] for entry in rects], [nonzero])


if __name__ == "__main__":
    unittest.main()
