import contextlib
import importlib.util
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from system import baseline  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "map_checker_application_baseline", APP_ROOT / "map-checker.py"
)
APPLICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPLICATION)


def finding(path, description, severity="warning", loc=(3, 4)):
    if loc is not None:
        description += "&nbsp;<br><b>X</b>: {}&nbsp;<br><b>Y</b>: {}".format(
            *loc)
    return {
        "file": {"name": "map", "path": path, "is_map": True},
        "severity": severity,
        "description": description,
        "explanation": "",
        "loc": list(loc) if loc is not None else None,
    }


class Config:
    def __init__(self, root):
        self.root = root

    def load(self, appdir):
        pass

    def save(self):
        raise AssertionError("headless runs must not save config")

    def set(self, section, option, value):
        pass


class FakeDatabase:
    def __init__(self):
        self.purged = False

    def purge(self, path=None):
        self.purged = True


class FakeMapChecker:
    definitionFilesData = {"archetype": {}, "artifact": {}, "region": {}}

    def __init__(self, config, errors):
        self.path = str(config.root)
        self.queue = queue.Queue()
        self.db = FakeDatabase()
        self.errors = errors

    def scan(self, **kwargs):
        for error in self.errors:
            self.queue.put(error)
        return True

    def exit(self):
        pass


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.map_path = str(self.maps / "town" / "inn")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_key_ignores_location_and_root(self):
        a = finding(self.map_path, "Monster has no loot.", loc=(1, 2))
        b = finding(self.map_path, "Monster has no loot.", loc=(7, 9))
        self.assertEqual(baseline.finding_key(a, str(self.maps)),
                         baseline.finding_key(b, str(self.maps)))
        self.assertEqual("town/inn\twarning\tMonster has no loot.",
                         baseline.finding_key(a, str(self.maps)))

    def test_round_trip_and_counts(self):
        errors = [finding(self.map_path, "Monster has no loot."),
                  finding(self.map_path, "Monster has no loot."),
                  finding(self.map_path, "Ignored.", severity="fixed")]
        path = self.root / "baseline.json"
        self.assertEqual(2, baseline.write_baseline(str(path), errors,
                                                    str(self.maps)))
        known = baseline.load_baseline(str(path))
        self.assertEqual([], baseline.new_findings(errors, known,
                                                   str(self.maps)))

        extra = errors + [finding(self.map_path, "Monster has no loot.")]
        self.assertEqual(1, len(baseline.new_findings(extra, known,
                                                      str(self.maps))))

    def test_catalog_diagnostics_are_never_baselined(self):
        error = finding(self.map_path, "x", severity="error", loc=None)
        error["source"] = {"line": 1, "column": 1}
        known = baseline.count_findings([error])
        self.assertEqual([error], baseline.new_findings([error], known))

    def test_rejects_unsupported_baseline(self):
        path = self.root / "baseline.json"
        path.write_text(json.dumps({"version": 99, "findings": []}))
        with self.assertRaises(ValueError):
            baseline.load_baseline(str(path))

    def _run(self, args, errors):
        checker = {}

        def factory(cfg):
            checker["instance"] = FakeMapChecker(cfg, errors)
            return checker["instance"]

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = APPLICATION.main(
                args + ["--directory", str(self.maps)],
                config_factory=lambda: Config(self.root),
                map_checker_factory=factory,
            )
        self.assertTrue(checker["instance"].db.purged)
        return result, output.getvalue()

    def test_cli_fails_only_on_new_findings(self):
        path = str(self.root / "baseline.json")
        known = [finding(self.map_path, "Monster has no loot.")]

        result, output = self._run(["--write-baseline", path], known)
        self.assertEqual(0, result)
        self.assertIn("Wrote 1 findings", output)

        result, output = self._run(["--baseline", path], known)
        self.assertEqual(0, result)
        self.assertIn("No new map checker findings.", output)

        new = known + [finding(self.map_path, "Monster has no race set.")]
        result, output = self._run(["--baseline", path], new)
        self.assertEqual(1, result)
        self.assertIn("Monster has no race set.", output)
        self.assertNotIn("Monster has no loot.", output)
        self.assertIn("1 new map checker findings", output)

    def test_cli_missing_baseline_is_usage_error(self):
        result, output = self._run(
            ["--baseline", str(self.root / "missing.json")], [])
        self.assertEqual(2, result)
        self.assertIn("Cannot load baseline", output)


if __name__ == "__main__":
    unittest.main()
