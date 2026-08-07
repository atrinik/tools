from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


APP_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(APP_ROOT))

from dependencies import DependencyError
from system.catalog import CatalogValidator


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_preserves_source_location_severity_and_related_location(self):
        location = SimpleNamespace(path="arch/example.arc", line=12, column=7)
        related = SimpleNamespace(path="arch/first.arc", line=2, column=8)
        diagnostic = SimpleNamespace(
            location=location,
            related=related,
            severity="error",
            code="duplicate-id",
            message="duplicate archetype:example <unsafe>",
        )
        catalog = SimpleNamespace(diagnostics=(diagnostic,), has_errors=True)
        module = SimpleNamespace(load_catalog=lambda root: catalog)
        validator = CatalogValidator(self.root, importer=lambda: module)

        diagnostics, valid = validator.validate(self.root)

        self.assertFalse(valid)
        self.assertEqual(1, len(diagnostics))
        result = diagnostics[0]
        self.assertEqual("error", result["severity"])
        self.assertEqual("duplicate-id", result["code"])
        self.assertEqual({"line": 12, "column": 7}, result["source"])
        self.assertEqual(str(self.root / "arch/example.arc"), result["file"]["path"])
        self.assertIn("arch/first.arc:2:8", result["explanation"])
        self.assertNotIn("<unsafe>", result["description"])
        self.assertIn("&lt;unsafe&gt;", result["description"])

    def test_reports_unavailable_or_mismatched_dependency(self):
        def unavailable():
            raise DependencyError("installed package does not match")

        validator = CatalogValidator(self.root, importer=unavailable)

        diagnostics, valid = validator.validate(self.root)

        self.assertFalse(valid)
        self.assertEqual("catalog-dependency", diagnostics[0]["code"])
        self.assertEqual("error", diagnostics[0]["severity"])
        self.assertIn("dependencies.py sync", diagnostics[0]["explanation"])

    def test_converts_unexpected_import_failure_to_a_diagnostic(self):
        validator = CatalogValidator(
            self.root, importer=lambda: (_ for _ in ()).throw(TypeError("bad module"))
        )

        diagnostics, valid = validator.validate(self.root)

        self.assertFalse(valid)
        self.assertEqual("catalog-dependency", diagnostics[0]["code"])
        self.assertIn("bad module", diagnostics[0]["message"])

    def test_converts_catalog_execution_failure_to_a_diagnostic(self):
        def fail(root):
            raise ValueError("malformed content")

        validator = CatalogValidator(
            self.root, importer=lambda: SimpleNamespace(load_catalog=fail)
        )

        diagnostics, valid = validator.validate(self.root)

        self.assertFalse(valid)
        self.assertEqual("catalog-validation", diagnostics[0]["code"])
        self.assertIn("malformed content", diagnostics[0]["message"])

    def test_rejects_diagnostic_paths_outside_content_root(self):
        diagnostic = SimpleNamespace(
            location=SimpleNamespace(path="../outside", line=1, column=1),
            related=None,
            severity="error",
            code="invalid",
            message="invalid",
        )
        catalog = SimpleNamespace(diagnostics=(diagnostic,), has_errors=True)
        validator = CatalogValidator(
            self.root,
            importer=lambda: SimpleNamespace(load_catalog=lambda root: catalog),
        )

        diagnostics, valid = validator.validate(self.root)

        self.assertFalse(valid)
        self.assertEqual("catalog-validation", diagnostics[0]["code"])

    def test_import_replaces_an_unpinned_cached_module(self):
        package = self.root / "content_catalog"
        package.mkdir()
        (package / "__init__.py").write_text(
            "def load_catalog(root):\n    return root\n", encoding="utf-8"
        )
        sys.modules["content_catalog"] = SimpleNamespace(
            load_catalog=lambda root: "unpinned"
        )
        validator = CatalogValidator(self.root)
        try:
            with mock.patch("system.catalog.verify", return_value=self.root):
                module = validator._import_catalog()
            self.assertNotEqual("unpinned", module.load_catalog(None))
            self.assertEqual(package / "__init__.py", Path(module.__file__).resolve())
        finally:
            sys.modules.pop("content_catalog", None)
            while str(self.root) in sys.path:
                sys.path.remove(str(self.root))


if __name__ == "__main__":
    unittest.main()
