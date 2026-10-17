"""The farming analyzer release asset is deterministic and contains only its package."""

import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "package-farming-analyzer.sh"


@unittest.skipUnless(shutil.which("git"), "git is required")
class FarmingAnalyzerReleaseAssetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "LICENSE").write_text("MIT\n")
        (self.repo / "farming_analyzer").mkdir()
        (self.repo / "farming_analyzer" / "__init__.py").write_text('"""Analyzer."""\n')
        (self.repo / "map-checker-qt").mkdir()
        (self.repo / "map-checker-qt" / "LICENSE").write_text("GPL\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "release")
        self.git("tag", "v1.2.3")

    def tearDown(self):
        self.directory.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
            check=True, capture_output=True, text=True).stdout

    def package(self, tag, output):
        return subprocess.run(["bash", str(SCRIPT), tag, str(output)], cwd=self.repo,
                              capture_output=True, text=True)

    def test_asset_is_deterministic_and_scoped_to_the_analyzer(self):
        first, second = Path(self.directory.name) / "a", Path(self.directory.name) / "b"
        for output in (first, second):
            result = self.package("v1.2.3", output)
            self.assertEqual(result.returncode, 0, result.stderr)
        name = "atrinik-tools-farming-analyzer-1.2.3.tar.gz"
        data = (first / name).read_bytes()
        self.assertEqual(data, (second / name).read_bytes())
        self.assertEqual((first / "SHA256SUMS").read_text(),
                         f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        with tarfile.open(first / name) as archive:
            members = sorted(member.name for member in archive.getmembers() if member.isfile())
        self.assertEqual(members, [
            "atrinik-tools-farming-analyzer-1.2.3/LICENSE",
            "atrinik-tools-farming-analyzer-1.2.3/farming_analyzer/__init__.py",
        ])

    def test_rejects_malformed_and_unreleased_tags(self):
        output = Path(self.directory.name) / "out"
        self.assertNotEqual(self.package("1.2.3", output).returncode, 0)
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "LICENSE").write_text("changed\n")
        self.git("commit", "-q", "-am", "side")
        self.git("tag", "v9.9.9")
        result = self.package("v9.9.9", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not reachable from main", result.stderr)


if __name__ == "__main__":
    unittest.main()
