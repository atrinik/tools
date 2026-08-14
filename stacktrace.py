#!/usr/bin/env python3
"""Resolve native stack-trace addresses with addr2line."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


_BRACKETED_ADDRESS = re.compile(r"\[(0x[0-9a-fA-F]+)\]\s*$")
_NUMBERED_ADDRESS = re.compile(r"^\d+:\s*(0x[0-9a-fA-F]+)\s*$")


def trace_address(line: str) -> str | None:
    """Return an address from a supported stack-trace line."""

    for pattern in (_BRACKETED_ADDRESS, _NUMBERED_ADDRESS):
        match = pattern.search(line)
        if match is not None:
            return match.group(1)
    return None


def resolve_trace(executable: Path, trace: Path) -> int:
    """Print a symbolized trace and return a process-style status."""

    status = 0
    with trace.open(encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.rstrip("\r\n")
            address = trace_address(line)
            if address is None:
                print(line)
                continue

            result = subprocess.run(
                ["addr2line", "-e", str(executable), "-f", "-p", address],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                print(result.stdout.rstrip("\r\n"))
            if result.returncode != 0:
                status = result.returncode
                if result.stderr:
                    print(result.stderr.rstrip("\r\n"), file=sys.stderr)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <executable> <stacktrace file>")
        return 0
    return resolve_trace(Path(args[0]), Path(args[1]))


if __name__ == "__main__":
    raise SystemExit(main())
