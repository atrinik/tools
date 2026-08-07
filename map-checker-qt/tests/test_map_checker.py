import contextlib
import importlib.util
import io
import logging
import logging.handlers
from pathlib import Path
import queue
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(APP_ROOT))

SPEC = importlib.util.spec_from_file_location(
    "map_checker_application", APP_ROOT / "map-checker.py"
)
APPLICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPLICATION)


class Config:
    def __init__(self, root):
        self.root = root
        self.saved = False

    def load(self, appdir):
        pass

    def save(self):
        self.saved = True

    def get(self, section, option):
        if option == "path_dir_content":
            return str(self.root)
        raise AssertionError(option)

    def set(self, section, option, value):
        if option == "path_dir_content":
            self.root = Path(value)
            return
        raise AssertionError(option)


class FakeMapChecker:
    definitionFilesData = {
        "archetype": {},
        "artifact": {},
        "region": {},
    }

    def __init__(self, config, succeeded=False):
        self.config = config
        self.path = str(config.root)
        self.queue = queue.Queue()
        self.succeeded = succeeded

    def scan(self, **kwargs):
        if not self.succeeded:
            self.queue.put(
                {
                    "file": {"path": "/content/arch/example.arc"},
                    "severity": "error",
                    "code": "duplicate-id",
                    "message": "duplicate archetype:example",
                    "description": "unused",
                    "explanation": "",
                    "loc": None,
                    "source": {"line": 12, "column": 7},
                }
            )
        return self.succeeded

    def exit(self):
        pass


class MapCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_repository_validation_stops_focused_scan(self):
        checker = object.__new__(APPLICATION.MapChecker)
        checker.config = Config(self.root)
        checker.queue = queue.Queue()
        checker._thread_running = True
        checker._scan_succeeded = None
        checker._scan_progress = 0
        checker._scan_status = ""
        calls = []

        class Validator:
            def validate(self, root):
                calls.append(Path(root))
                return ([{"code": "duplicate-id"}], False)

        checker.catalog_validator = Validator()

        result = checker._scan(None, None, True, False, None, False)

        self.assertFalse(result)
        self.assertEqual([self.root], calls)
        self.assertEqual("duplicate-id", checker.queue.get_nowait()["code"])
        self.assertFalse(checker._thread_running)

    def test_headless_catalog_failure_returns_nonzero_with_location(self):
        config = Config(self.root)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = APPLICATION.main(
                ["--cli", "--catalog-only"],
                config_factory=lambda: config,
                map_checker_factory=lambda cfg: FakeMapChecker(cfg),
            )

        self.assertEqual(1, result)
        self.assertIn(
            "/content/arch/example.arc:12:7: error duplicate-id: "
            "duplicate archetype:example",
            output.getvalue(),
        )
        self.assertFalse(config.saved)

    def test_headless_success_returns_zero(self):
        config = Config(self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            result = APPLICATION.main(
                ["--cli", "--catalog-only"],
                config_factory=lambda: config,
                map_checker_factory=lambda cfg: FakeMapChecker(cfg, succeeded=True),
            )
        self.assertEqual(0, result)

    def test_repeated_main_calls_reuse_the_application_log_handler(self):
        config = Config(self.root)
        logger = logging.getLogger("interface-editor")
        log_path = str((APP_ROOT / "map-checker.log").resolve())

        def matching_handlers():
            return [
                handler
                for handler in logger.handlers
                if isinstance(handler, logging.handlers.RotatingFileHandler)
                and handler.baseFilename == log_path
            ]

        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                APPLICATION.main(
                    ["--cli", "--catalog-only"],
                    config_factory=lambda: config,
                    map_checker_factory=lambda cfg: FakeMapChecker(
                        cfg, succeeded=True
                    ),
                )

        self.assertEqual(1, len(matching_handlers()))


if __name__ == "__main__":
    unittest.main()
