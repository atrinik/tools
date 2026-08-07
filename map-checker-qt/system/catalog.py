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
    def _failure_diagnostic(message, lock_path, code, summary, explanation):
        return {
            "file": {
                "name": lock_path.name,
                "path": str(lock_path),
                "is_map": False,
            },
            "severity": "error",
            "code": code,
            "message": message,
            "description": "{}: {}".format(summary, html.escape(message)),
            "explanation": explanation,
            "loc": None,
            "source": {"line": 1, "column": 1},
        }

    @staticmethod
    def _diagnostic(catalog_root, diagnostic):
        location = diagnostic.location
        location_path = Path(location.path)
        if location_path.is_absolute() or ".." in location_path.parts:
            raise ValueError("catalog diagnostic contains an unsafe source path")
        source_path = catalog_root / location_path
        related = None
        if diagnostic.related is not None:
            related_path = Path(diagnostic.related.path)
            if related_path.is_absolute() or ".." in related_path.parts:
                raise ValueError("catalog diagnostic contains an unsafe related path")
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
        except Exception as error:
            diagnostic = self._failure_diagnostic(
                str(error),
                self.lock_path,
                "catalog-dependency",
                "Content catalog dependency unavailable",
                "Run map-checker-qt/dependencies.py sync and retry the scan.",
            )
            return [diagnostic], False
        try:
            catalog = module.load_catalog(catalog_root)
            diagnostics = [
                self._diagnostic(catalog_root, diagnostic)
                for diagnostic in catalog.diagnostics
            ]
            has_errors = catalog.has_errors
        except Exception as error:
            message = str(error) or error.__class__.__name__
            diagnostic = self._failure_diagnostic(
                message,
                self.lock_path,
                "catalog-validation",
                "Content catalog validation failed",
                "Confirm that the content root is readable and retry the scan.",
            )
            return [diagnostic], False
        return diagnostics, not has_errors
