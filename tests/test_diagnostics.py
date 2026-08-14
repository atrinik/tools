from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stacktrace", ROOT / "stacktrace.py")
assert SPEC is not None and SPEC.loader is not None
STACKTRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STACKTRACE)


class StacktraceTests(unittest.TestCase):
    def test_trace_address_accepts_supported_formats(self) -> None:
        self.assertEqual(STACKTRACE.trace_address("frame [0x1a2B]"), "0x1a2B")
        self.assertEqual(STACKTRACE.trace_address("12: 0xfeed"), "0xfeed")
        self.assertIsNone(STACKTRACE.trace_address("unresolved frame"))

    def test_resolve_trace_preserves_text_and_reports_tool_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.txt"
            trace.write_text("heading\nframe [0x12]\n1: 0x34\n", encoding="utf-8")
            resolver = root / "addr2line"
            resolver.write_text(
                "#!/bin/sh\n"
                "case \"$5\" in\n"
                "  0x12) printf 'first at source.c:12\\n' ;;\n"
                "  *) printf 'unresolved\\n' >&2; exit 3 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            resolver.chmod(resolver.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}{os.pathsep}{old_path}"
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    status = STACKTRACE.resolve_trace(root / "game", trace)
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(status, 3)
            self.assertEqual(stdout.getvalue(), "heading\nfirst at source.c:12\n")
            self.assertEqual(stderr.getvalue(), "unresolved\n")

    def test_usage_remains_successful(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(STACKTRACE.main([]), 0)
        self.assertIn("<executable> <stacktrace file>", output.getvalue())


class SplitSymbolsTests(unittest.TestCase):
    def test_usage_remains_successful(self) -> None:
        result = subprocess.run(
            [str(ROOT / "split_symbols.sh")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("<executable>", result.stdout)


if __name__ == "__main__":
    unittest.main()
