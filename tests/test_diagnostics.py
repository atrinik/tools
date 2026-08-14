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
        self.assertEqual(STACKTRACE.trace_address("  frame [0x1a2B]  "), "0x1a2B")
        self.assertEqual(STACKTRACE.trace_address(" 12: symbol+4 "), "symbol+4")
        self.assertIsNone(STACKTRACE.trace_address("unresolved frame"))

    def test_resolve_trace_preserves_text_and_legacy_success(self) -> None:
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

            self.assertEqual(status, 0)
            self.assertEqual(stdout.getvalue(), "heading\nfirst at source.c:12\n\n")
            self.assertEqual(stderr.getvalue(), "unresolved\n")

    def test_usage_remains_successful(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(STACKTRACE.main([]), 0)
        self.assertIn("<executable> <stacktrace file>", output.getvalue())

    def test_extra_arguments_remain_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.txt"
            trace.write_text("plain frame\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(STACKTRACE.main([str(root / "game"), str(trace), "ignored"]), 0)
            self.assertEqual(output.getvalue(), "plain frame\n")


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

    def test_extra_arguments_are_ignored_and_nonregular_debug_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "sample"
            subprocess.run(["cc", "-x", "c", "-g", "-o", str(executable), "-"], input="int main(void) { return 0; }\n", text=True, check=True)
            debug = root / "sample.debug"
            debug.mkdir()
            before = executable.read_bytes()
            result = subprocess.run([str(ROOT / "split_symbols.sh"), str(executable), "ignored"], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Refusing non-regular debug destination", result.stderr)
            self.assertEqual(executable.read_bytes(), before)
            self.assertEqual(list(debug.iterdir()), [])

    def test_symlinked_executable_is_rejected_without_mutating_referent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "sample"
            subprocess.run(["cc", "-x", "c", "-g", "-o", str(executable), "-"], input="int main(void) { return 0; }\n", text=True, check=True)
            link = root / "linked-sample"
            link.symlink_to(executable.name)
            before = executable.read_bytes()
            result = subprocess.run([str(ROOT / "split_symbols.sh"), str(link)], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(link.is_symlink())
            self.assertEqual(executable.read_bytes(), before)
            self.assertFalse((root / "linked-sample.debug").exists())

    def test_splits_disposable_elf_and_leaves_source_unchanged_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.c"
            executable = root / "sample"
            source.write_text("int retained_symbol(void) { return 42; }\nint main(void) { return retained_symbol(); }\n", encoding="utf-8")
            subprocess.run(["cc", "-g", "-o", str(executable), str(source)], check=True)

            result = subprocess.run([str(ROOT / "split_symbols.sh"), str(executable)], check=False, capture_output=True, text=True)
            debug = root / "sample.debug"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(executable.stat().st_mode & stat.S_IXUSR)
            self.assertFalse(debug.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            self.assertEqual(subprocess.run([str(executable)], check=False).returncode, 42)
            self.assertIn("retained_symbol", subprocess.run(["nm", str(debug)], check=True, capture_output=True, text=True).stdout)
            self.assertIn(".gnu_debuglink", subprocess.run(["readelf", "--sections", str(executable)], check=True, capture_output=True, text=True).stdout)

            before = executable.read_bytes()
            fake_tools = root / "fake-tools"
            fake_tools.mkdir()
            for tool in ("bash", "objcopy", "mktemp", "cp", "rm", "dirname", "basename", "chmod", "mv"):
                os.symlink(Path("/usr/bin") / tool, fake_tools / tool)
            failing_strip = fake_tools / "strip"
            failing_strip.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
            failing_strip.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(fake_tools)
            failed = subprocess.run([str(ROOT / "split_symbols.sh"), str(executable)], check=False, capture_output=True, text=True, env=env)
            self.assertEqual(failed.returncode, 9)
            self.assertEqual(executable.read_bytes(), before)
            self.assertFalse(any(root.glob(".split-symbols.*")))


if __name__ == "__main__":
    unittest.main()
