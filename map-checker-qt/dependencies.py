#!/usr/bin/env python3
"""Install and verify the checksum-pinned Atrinik content catalog."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from urllib.error import URLError
from urllib.request import urlopen
import uuid


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_FILES = 128
LOCK_KEYS = {"schema_version", "dependency"}
DEPENDENCY_KEYS = {
    "name",
    "repository",
    "tag",
    "commit",
    "url",
    "sha256",
    "archive_prefix",
    "destination",
}


class DependencyError(RuntimeError):
    """A catalog dependency could not be validated or installed."""


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DependencyError("duplicate JSON key: {}".format(key))
        result[key] = value
    return result


def load_lock(lock_path):
    """Load and strictly validate the catalog dependency lock."""

    lock_path = Path(lock_path)
    try:
        with lock_path.open(encoding="utf-8") as source:
            lock = json.load(source, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError) as error:
        raise DependencyError("could not read {}: {}".format(lock_path, error))

    if not isinstance(lock, dict) or set(lock) != LOCK_KEYS:
        raise DependencyError("catalog lock must contain exactly schema_version and dependency")
    if lock["schema_version"] != 1:
        raise DependencyError("unsupported catalog lock schema")
    dependency = lock["dependency"]
    if not isinstance(dependency, dict) or set(dependency) != DEPENDENCY_KEYS:
        raise DependencyError("catalog dependency has missing or unknown fields")
    if dependency["name"] != "content_catalog":
        raise DependencyError("catalog dependency name must be content_catalog")

    string_fields = DEPENDENCY_KEYS - {"name"}
    if any(
        not isinstance(dependency[field], str) or not dependency[field]
        for field in string_fields
    ):
        raise DependencyError("catalog dependency fields must be non-empty strings")
    if not dependency["url"].startswith("https://"):
        raise DependencyError("catalog dependency URL must use HTTPS")
    if len(dependency["sha256"]) != 64 or any(
        character not in "0123456789abcdef" for character in dependency["sha256"]
    ):
        raise DependencyError("catalog dependency SHA-256 is invalid")
    if len(dependency["commit"]) != 40 or any(
        character not in "0123456789abcdef" for character in dependency["commit"]
    ):
        raise DependencyError("catalog dependency commit is invalid")

    destination = PurePosixPath(dependency["destination"])
    prefix = PurePosixPath(dependency["archive_prefix"])
    if (
        "\\" in dependency["destination"]
        or "\\" in dependency["archive_prefix"]
        or destination.is_absolute()
        or prefix.is_absolute()
        or ".." in destination.parts
        or ".." in prefix.parts
        or destination.parts[-1] != "content_catalog"
        or prefix.parts[-2:] != ("tools", "content_catalog")
    ):
        raise DependencyError("catalog dependency paths are invalid")
    return dependency


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_hash(package_path):
    package_path = Path(package_path)
    if package_path.is_symlink() or not package_path.is_dir():
        raise DependencyError("installed content_catalog is missing or unsafe")
    digest = hashlib.sha256()
    file_count = 0
    total_size = 0
    for path in sorted(package_path.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise DependencyError("installed content_catalog contains links or special files")
        relative_path = path.relative_to(package_path)
        if relative_path.as_posix() == ".atrinik-dependency.json":
            continue
        if "__pycache__" in relative_path.parts:
            if path.is_file() and path.suffix != ".pyc":
                raise DependencyError("installed content_catalog contains an unexpected cache file")
            continue
        if not path.is_file():
            continue
        relative = relative_path.as_posix()
        if not relative.endswith(".py"):
            raise DependencyError("installed content_catalog contains an unexpected file")
        file_count += 1
        total_size += path.stat().st_size
        if file_count > MAX_PACKAGE_FILES or total_size > MAX_PACKAGE_BYTES:
            raise DependencyError("installed content_catalog exceeds safety limits")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    if not (package_path / "__init__.py").is_file():
        raise DependencyError("installed content_catalog has no __init__.py")
    return digest.hexdigest()


def _remove_bytecode(package_path):
    for path in sorted(Path(package_path).rglob("__pycache__"), reverse=True):
        if path.is_symlink() or not path.is_dir():
            raise DependencyError("installed content_catalog contains an unsafe bytecode cache")
        shutil.rmtree(path)


def _paths(root, dependency):
    root = Path(root).resolve()
    destination = root / Path(dependency["destination"])
    try:
        destination.relative_to(root)
    except ValueError:
        raise DependencyError("catalog destination escapes the application root")
    current = root
    for part in Path(dependency["destination"]).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise DependencyError("catalog destination parent must not be a symbolic link")
    metadata = destination / ".atrinik-dependency.json"
    cache = destination.parent / "cache" / "{}.tar.gz".format(dependency["sha256"])
    return destination, metadata, cache


def _download(dependency, cache_path, opener=urlopen):
    if cache_path.parent.is_symlink():
        raise DependencyError(
            "catalog archive cache directory must not be a symbolic link"
        )
    if cache_path.parent.exists() and not cache_path.parent.is_dir():
        raise DependencyError("catalog archive cache path is not a directory")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=cache_path.parent, prefix=".catalog-", delete=False
        ) as destination:
            temporary = Path(destination.name)
            try:
                response = opener(dependency["url"], timeout=30)
                with response:
                    declared = response.headers.get("Content-Length")
                    if declared is not None and int(declared) > MAX_ARCHIVE_BYTES:
                        raise DependencyError("catalog archive exceeds download limit")
                    total = 0
                    digest = hashlib.sha256()
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_ARCHIVE_BYTES:
                            raise DependencyError("catalog archive exceeds download limit")
                        digest.update(chunk)
                        destination.write(chunk)
            except (OSError, URLError, ValueError) as error:
                raise DependencyError("catalog archive is unavailable: {}".format(error))
            if digest.hexdigest() != dependency["sha256"]:
                raise DependencyError("catalog archive SHA-256 does not match the lock")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(str(temporary), str(cache_path))
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _extract_package(archive_path, candidate, dependency):
    prefix = PurePosixPath(dependency["archive_prefix"])
    seen = set()
    total_size = 0
    file_count = 0
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (OSError, tarfile.TarError) as error:
        raise DependencyError("could not open catalog archive: {}".format(error))
    with archive:
        for member in archive:
            if "\\" in member.name:
                raise DependencyError("catalog archive contains a non-portable path")
            member_path = PurePosixPath(member.name)
            try:
                relative = member_path.relative_to(prefix)
            except ValueError:
                continue
            if not relative.parts:
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise DependencyError("catalog archive contains an unsafe path")
            if member.isdir():
                continue
            if (
                not member.isfile()
                or member.size < 0
                or not relative.name.endswith(".py")
            ):
                raise DependencyError("catalog archive package contains an unsafe member")
            relative_name = relative.as_posix()
            if relative_name in seen:
                raise DependencyError("catalog archive package contains a duplicate path")
            seen.add(relative_name)
            file_count += 1
            total_size += member.size
            if file_count > MAX_PACKAGE_FILES or total_size > MAX_PACKAGE_BYTES:
                raise DependencyError("catalog archive package exceeds safety limits")
            source = archive.extractfile(member)
            if source is None:
                raise DependencyError("catalog archive package member is unreadable")
            output = candidate.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    if not (candidate / "__init__.py").is_file():
        raise DependencyError("catalog archive does not contain the package")


def _replace_directory(candidate, destination):
    backup = None
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise DependencyError("catalog destination is not a managed directory")
        backup = destination.parent / ".content_catalog-backup-{}".format(uuid.uuid4().hex)
        os.replace(str(destination), str(backup))
    try:
        os.replace(str(candidate), str(destination))
    except BaseException:
        if backup is not None:
            os.replace(str(backup), str(destination))
        raise
    if backup is not None:
        shutil.rmtree(backup)


def sync(root, lock_path, opener=urlopen, refresh=False):
    """Install the locked package and return its import parent."""

    dependency = load_lock(lock_path)
    destination, metadata_path, cache_path = _paths(root, dependency)
    if not refresh:
        try:
            return verify(root, lock_path)
        except DependencyError:
            pass
    if cache_path.is_symlink():
        raise DependencyError("catalog archive cache must not be a symbolic link")
    if cache_path.parent.is_symlink():
        raise DependencyError(
            "catalog archive cache directory must not be a symbolic link"
        )
    if not cache_path.is_file() or _hash_file(cache_path) != dependency["sha256"]:
        _download(dependency, cache_path, opener)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".content-catalog-", dir=destination.parent)
    )
    candidate = temporary_root / "content_catalog"
    candidate.mkdir()
    try:
        _extract_package(cache_path, candidate, dependency)
        package_sha256 = _package_hash(candidate)
        metadata = {
            "name": dependency["name"],
            "repository": dependency["repository"],
            "tag": dependency["tag"],
            "commit": dependency["commit"],
            "archive_sha256": dependency["sha256"],
            "package_sha256": package_sha256,
        }
        candidate_metadata = candidate / metadata_path.name
        with candidate_metadata.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(metadata, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        _replace_directory(candidate, destination)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return verify(root, lock_path)


def verify(root, lock_path):
    """Verify the installed package and return its import parent."""

    dependency = load_lock(lock_path)
    destination, metadata_path, _ = _paths(root, dependency)
    if metadata_path.is_symlink():
        raise DependencyError("installed catalog metadata must not be a symbolic link")
    try:
        with metadata_path.open(encoding="utf-8") as source:
            metadata = json.load(source, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError) as error:
        raise DependencyError("catalog dependency is not installed: {}".format(error))
    expected = {
        "name": dependency["name"],
        "repository": dependency["repository"],
        "tag": dependency["tag"],
        "commit": dependency["commit"],
        "archive_sha256": dependency["sha256"],
    }
    expected_keys = set(expected) | {"package_sha256"}
    if (
        not isinstance(metadata, dict)
        or set(metadata) != expected_keys
        or any(metadata.get(key) != value for key, value in expected.items())
    ):
        raise DependencyError("installed catalog metadata does not match the lock")
    package_sha256 = _package_hash(destination)
    if metadata.get("package_sha256") != package_sha256:
        raise DependencyError("installed catalog package does not match its verified archive")
    _remove_bytecode(destination)
    return destination.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "sync", "verify"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    lock_path = args.lock or root / "catalog.lock.json"
    try:
        if args.command == "validate":
            dependency = load_lock(lock_path)
            print("{}: {} {}".format(lock_path, dependency["tag"], dependency["sha256"]))
        elif args.command == "sync":
            print(sync(root, lock_path, refresh=args.refresh))
        else:
            print(verify(root, lock_path))
    except DependencyError as error:
        print("dependency error: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
