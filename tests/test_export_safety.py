"""Private exporter regression: no existing output is ever removed."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export-public.py"


@unittest.skipUnless(SCRIPT.is_file(), "private export tool is not distributed")
class ExportSafetyTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("private_export", SCRIPT)
        self.exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.exporter)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_existing_output_preserves_uncommitted_file(self):
        dest = self.root / "existing"
        dest.mkdir()
        marker = dest / "uncommitted.txt"
        marker.write_bytes(b"keep this exact content")
        with self.assertRaises(FileExistsError):
            self.exporter.new_destination(dest, self.root)
        self.assertEqual(marker.read_bytes(), b"keep this exact content")

    def test_escape_and_root_are_rejected_before_writes(self):
        for dest in (self.root, self.root / ".." / "escaped-output"):
            with self.assertRaises(ValueError):
                self.exporter.new_destination(dest, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_new_directory_is_reserved_once(self):
        dest = self.root / "new"
        self.assertEqual(self.exporter.new_destination(dest, self.root), dest.resolve())
        with self.assertRaises(FileExistsError):
            self.exporter.new_destination(dest, self.root)

    def test_source_overlap_rejected(self):
        with self.assertRaises(ValueError):
            self.exporter.new_destination(self.exporter.REPO / "output", self.exporter.REPO)

    def test_linked_ancestor_is_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        link = self.root / "alias"
        try:
            link.symlink_to(actual, target_is_directory=True)
        except OSError:
            self.skipTest("creating symlinks requires local privileges")
        with self.assertRaises(ValueError):
            self.exporter.new_destination(link / "output", self.root)
        self.assertEqual(list(actual.iterdir()), [])
