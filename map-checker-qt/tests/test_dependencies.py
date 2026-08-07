import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from urllib.error import URLError


APP_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(APP_ROOT))

import dependencies


class Response(io.BytesIO):
    def __init__(self, contents):
        super().__init__(contents)
        self.headers = {"Content-Length": str(len(contents))}


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.lock_path = self.root / "catalog.lock.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def archive(member_type=tarfile.REGTYPE, member_name="model.py"):
        output = io.BytesIO()
        prefix = "atrinik-content-1.2.0/tools/content_catalog"
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            files = {
                "__init__.py": b"def load_catalog(root):\n    return root\n",
                member_name: b"VALUE = 1\n",
            }
            for name, contents in files.items():
                info = tarfile.TarInfo("{}/{}".format(prefix, name))
                info.size = len(contents)
                if name == member_name and member_type != tarfile.REGTYPE:
                    info.type = member_type
                    info.linkname = "/outside"
                    info.size = 0
                    archive.addfile(info)
                else:
                    archive.addfile(info, io.BytesIO(contents))
        return output.getvalue()

    def write_lock(self, archive, sha256=None):
        digest = sha256 or hashlib.sha256(archive).hexdigest()
        self.lock_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "dependency": {
                        "name": "content_catalog",
                        "repository": "atrinik/content",
                        "tag": "v1.2.0",
                        "commit": "0" * 40,
                        "url": "https://example.invalid/content.tar.gz",
                        "sha256": digest,
                        "archive_prefix": (
                            "atrinik-content-1.2.0/tools/content_catalog"
                        ),
                        "destination": ".dependencies/content_catalog",
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_installs_and_verifies_locked_package(self):
        archive = self.archive()
        self.write_lock(archive)

        import_parent = dependencies.sync(
            self.root,
            self.lock_path,
            opener=lambda url, timeout: Response(archive),
        )

        self.assertEqual(self.root / ".dependencies", import_parent)
        self.assertTrue((import_parent / "content_catalog/__init__.py").is_file())
        self.assertEqual(import_parent, dependencies.verify(self.root, self.lock_path))

    def test_rejects_archive_with_mismatched_digest(self):
        archive = self.archive()
        self.write_lock(archive, "f" * 64)

        with self.assertRaisesRegex(dependencies.DependencyError, "SHA-256"):
            dependencies.sync(
                self.root,
                self.lock_path,
                opener=lambda url, timeout: Response(archive),
            )

        self.assertFalse((self.root / ".dependencies/content_catalog").exists())

    def test_reports_unavailable_archive(self):
        archive = self.archive()
        self.write_lock(archive)

        def unavailable(url, timeout):
            raise URLError("offline")

        with self.assertRaisesRegex(dependencies.DependencyError, "unavailable"):
            dependencies.sync(self.root, self.lock_path, opener=unavailable)

    def test_detects_modified_installed_package(self):
        archive = self.archive()
        self.write_lock(archive)
        import_parent = dependencies.sync(
            self.root,
            self.lock_path,
            opener=lambda url, timeout: Response(archive),
        )
        (import_parent / "content_catalog/model.py").write_text(
            "VALUE = 2\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(dependencies.DependencyError, "verified archive"):
            dependencies.verify(self.root, self.lock_path)

    def test_removes_generated_bytecode_after_verifying_sources(self):
        archive = self.archive()
        self.write_lock(archive)
        import_parent = dependencies.sync(
            self.root,
            self.lock_path,
            opener=lambda url, timeout: Response(archive),
        )
        bytecode = import_parent / "content_catalog/__pycache__/model.pyc"
        bytecode.parent.mkdir()
        bytecode.write_bytes(b"generated")

        dependencies.verify(self.root, self.lock_path)

        self.assertFalse(bytecode.parent.exists())

    def test_rejects_links_in_catalog_package(self):
        archive = self.archive(tarfile.SYMTYPE)
        self.write_lock(archive)

        with self.assertRaisesRegex(dependencies.DependencyError, "unsafe member"):
            dependencies.sync(
                self.root,
                self.lock_path,
                opener=lambda url, timeout: Response(archive),
            )

    def test_rejects_nonportable_archive_traversal(self):
        archive = self.archive(member_name="..\\outside.py")
        self.write_lock(archive)

        with self.assertRaisesRegex(dependencies.DependencyError, "non-portable"):
            dependencies.sync(
                self.root,
                self.lock_path,
                opener=lambda url, timeout: Response(archive),
            )

    def test_rejects_symlinked_dependency_parent(self):
        archive = self.archive()
        self.write_lock(archive)
        with tempfile.TemporaryDirectory() as external:
            (self.root / ".dependencies").symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(dependencies.DependencyError, "symbolic link"):
                dependencies.sync(
                    self.root,
                    self.lock_path,
                    opener=lambda url, timeout: Response(archive),
                )

    def test_rejects_symlinked_archive_cache_directory(self):
        archive = self.archive()
        self.write_lock(archive)
        (self.root / ".dependencies").mkdir()
        with tempfile.TemporaryDirectory() as external:
            (self.root / ".dependencies/cache").symlink_to(
                external, target_is_directory=True
            )

            with self.assertRaisesRegex(dependencies.DependencyError, "cache directory"):
                dependencies.sync(
                    self.root,
                    self.lock_path,
                    opener=lambda url, timeout: Response(archive),
                )

    def test_rejects_unrecognized_installed_metadata(self):
        archive = self.archive()
        self.write_lock(archive)
        import_parent = dependencies.sync(
            self.root,
            self.lock_path,
            opener=lambda url, timeout: Response(archive),
        )
        metadata_path = import_parent / "content_catalog/.atrinik-dependency.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["unexpected"] = True
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(dependencies.DependencyError, "metadata"):
            dependencies.verify(self.root, self.lock_path)


if __name__ == "__main__":
    unittest.main()
