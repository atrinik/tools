"""
Baseline support for headless map checker runs.

A baseline records the findings that already exist in a content tree, so
that CI can fail only when a change introduces new findings. Findings are
keyed by file (relative to a root), severity and description with the
object's coordinates removed, so moving an object does not create a new
finding. Identical findings in one file are counted, so adding another
copy of an existing problem is still reported.
"""

from collections import Counter
import json
import os
import re

BASELINE_VERSION = 1

# Severities that never count as findings.
IGNORED_SEVERITIES = ("fixed",)

_PATTERN_LOCATION = re.compile(r"(?:&nbsp;)?<br><b>[XY]</b>: -?\d+")


def _relative_path(path, root):
    if not root or not path:
        return path

    root = os.path.realpath(root)
    real = os.path.realpath(path)

    if real == root or real.startswith(root + os.sep):
        return os.path.relpath(real, root).replace(os.sep, "/")

    return path


def finding_key(error, root=None):
    """Return a stable, location-independent key for a checker finding."""
    path = _relative_path(error["file"]["path"], root)
    description = error.get("message", error.get("description", ""))
    description = _PATTERN_LOCATION.sub("", description)
    return "{}\t{}\t{}".format(path, error["severity"], description)


def is_finding(error):
    """Whether an error counts as a finding for baseline purposes."""
    return error["severity"] not in IGNORED_SEVERITIES


def count_findings(errors, root=None):
    """Count findings by key."""
    return Counter(finding_key(error, root) for error in errors
                   if is_finding(error))


def write_baseline(path, errors, root=None):
    """Write the findings in errors to a baseline file."""
    counts = count_findings(errors, root)
    document = {
        "version": BASELINE_VERSION,
        "findings": [{"key": key, "count": counts[key]}
                     for key in sorted(counts)],
    }

    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(document, fp, indent=2, sort_keys=True)
        fp.write("\n")

    return sum(counts.values())


def load_baseline(path):
    """Load a baseline file into a Counter of finding keys."""
    with open(path, encoding="utf-8") as fp:
        document = json.load(fp)

    if not isinstance(document, dict) or \
            document.get("version") != BASELINE_VERSION:
        raise ValueError("unsupported map checker baseline: {}".format(path))

    counts = Counter()

    for entry in document.get("findings", []):
        key = entry["key"]
        count = entry["count"]

        if not isinstance(key, str) or not isinstance(count, int) or \
                count < 1:
            raise ValueError("invalid map checker baseline entry: "
                             "{!r}".format(entry))

        counts[key] += count

    return counts


def new_findings(errors, baseline, root=None):
    """
    Return the findings in errors that are not covered by baseline.

    Each baseline entry covers as many matching findings as its count.
    Catalog diagnostics (which carry a source location) are always
    returned, since the catalog gate is strict independently.
    """
    remaining = Counter(baseline)
    result = []

    for error in errors:
        if not is_finding(error):
            continue

        if error.get("source") is not None:
            result.append(error)
            continue

        key = finding_key(error, root)

        if remaining[key] > 0:
            remaining[key] -= 1
            continue

        result.append(error)

    return result
