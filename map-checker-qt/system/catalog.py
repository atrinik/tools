"""Bridge the map checker to the released Atrinik content catalog."""

import importlib
import html
from pathlib import Path
import sys

from dependencies import DependencyError, verify


class CatalogValidator:
    """Verify, load, and execute the checksum-pinned catalog package."""

    def __init__(self, application_root, importer=None):
        self.application_root = Path(application_root).resolve()
        self.lock_path = self.application_root / "catalog.lock.json"
        self.importer = importer or self._import_catalog

    def _import_catalog(self):
        import_parent = verify(self.application_root, self.lock_path)
        import_parent_text = str(import_parent)
        if import_parent_text in sys.path:
            sys.path.remove(import_parent_text)
        sys.path.insert(0, import_parent_text)
        for name in tuple(sys.modules):
            if name == "content_catalog" or name.startswith("content_catalog."):
                del sys.modules[name]
        importlib.invalidate_caches()
        module = importlib.import_module("content_catalog")
        module_path = Path(module.__file__).resolve()
        expected_path = (import_parent / "content_catalog").resolve()
        try:
            module_path.relative_to(expected_path)
        except ValueError:
            raise DependencyError("content_catalog was imported from an unpinned path")
        if not callable(getattr(module, "load_catalog", None)):
            raise DependencyError("installed content_catalog API is incompatible")
        return module

    @staticmethod
    def _dependency_diagnostic(message, lock_path):
        return {
            "file": {
                "name": lock_path.name,
                "path": str(lock_path),
                "is_map": False,
            },
            "severity": "error",
            "code": "catalog-dependency",
            "message": message,
            "description": "Content catalog dependency unavailable: {}".format(
                html.escape(message)
            ),
            "explanation": (
                "Run map-checker-qt/dependencies.py sync and retry the scan."
            ),
            "loc": None,
            "source": {"line": 1, "column": 1},
        }

    @staticmethod
    def _diagnostic(catalog_root, diagnostic):
        location = diagnostic.location
        source_path = catalog_root / Path(location.path)
        related = None
        if diagnostic.related is not None:
            related = {
                "path": diagnostic.related.path,
                "line": diagnostic.related.line,
                "column": diagnostic.related.column,
            }
        explanation = ""
        if related is not None:
            explanation = "Related definition: {}:{}:{}".format(
                html.escape(related["path"]),
                related["line"],
                related["column"],
            )
        return {
            "file": {
                "name": location.path,
                "path": str(source_path),
                "is_map": False,
            },
            "severity": diagnostic.severity,
            "code": diagnostic.code,
            "message": diagnostic.message,
            "description": (
                "<b>Line</b>: {line}, <b>column</b>: {column}<br>"
                "{code}: {message}"
            ).format(
                line=location.line,
                column=location.column,
                code=html.escape(diagnostic.code),
                message=html.escape(diagnostic.message),
            ),
            "explanation": explanation,
            "loc": None,
            "source": {"line": location.line, "column": location.column},
            "related": related,
        }

    def validate(self, catalog_root):
        """Return translated diagnostics and whether identity validation passed."""

        catalog_root = Path(catalog_root).resolve()
        try:
            module = self.importer()
            catalog = module.load_catalog(catalog_root)
        except (DependencyError, ImportError, OSError, RuntimeError) as error:
            return [self._dependency_diagnostic(str(error), self.lock_path)], False
        diagnostics = [
            self._diagnostic(catalog_root, diagnostic)
            for diagnostic in catalog.diagnostics
        ]
        return diagnostics, not catalog.has_errors
