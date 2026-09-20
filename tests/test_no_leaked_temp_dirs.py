"""Tests must remove the temp folders they make.

A full run leaked about 250 folders (66 MB). g2k runs this suite many times a day on the OCI host,
and 208,000 leaked folders (about 36 GB) filled its disk in three days. `tempfile.mkdtemp()` never
cleans up after itself, so a test that calls it must remove the folder.
"""
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


class NoLeakedTempDirs(unittest.TestCase):
    def test_every_test_file_that_calls_mkdtemp_also_removes_what_it_makes(self):
        leaking = []
        for path in sorted(TESTS.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            if "tempfile.mkdtemp(" in source and not re.search(r"shutil\.rmtree", source):
                leaking.append(path.name)
        self.assertEqual(
            leaking,
            [],
            "these tests call tempfile.mkdtemp() and never remove the folder; use "
            "self.addCleanup(shutil.rmtree, path, ignore_errors=True) or tempfile.TemporaryDirectory()",
        )


if __name__ == "__main__":
    unittest.main()
