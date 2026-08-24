#!/usr/bin/env python3
"""Verify that the locked Content catalog release is published and reachable."""

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from dependencies import DependencyError, load_lock


API_ROOT = "https://api.github.com"
REQUEST_TIMEOUT = 30
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
USER_AGENT = "atrinik-tools-catalog-preflight"


class ReleasePreflightError(RuntimeError):
    """The locked Content release cannot be safely consumed."""


def _headers(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _read_json(response, description):
    try:
        try:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, ValueError) as error:
            raise ReleasePreflightError(
                "{} response could not be read: {}".format(description, error)
            )
    finally:
        response.close()
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ReleasePreflightError(
            "{} response exceeds the safety limit".format(description)
        )
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ReleasePreflightError(
            "{} response is not valid JSON: {}".format(description, error)
        )


def _get_json(url, headers, opener):
    request = Request(url, headers=headers)
    try:
        response = opener(request, timeout=REQUEST_TIMEOUT)
    except HTTPError as error:
        status = error.code
        error.close()
        if status == 404:
            raise ReleasePreflightError("{} was not found".format(url))
        raise ReleasePreflightError(
            "{} request failed with HTTP {}".format(url, status)
        )
    except URLError as error:
        raise ReleasePreflightError("{} request failed: {}".format(url, error.reason))
    except OSError as error:
        raise ReleasePreflightError("{} request failed: {}".format(url, error))

    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    if status != 200:
        response.close()
        raise ReleasePreflightError("{} returned HTTP {}".format(url, status))
    return _read_json(response, url)


def _release_api_url(api_root, owner, repository, tag):
    return "{}/repos/{}/{}/releases/tags/{}".format(
        api_root.rstrip("/"),
        quote(owner, safe=""),
        quote(repository, safe=""),
        quote(tag, safe=""),
    )


def _tag_api_url(api_root, owner, repository, tag):
    return "{}/repos/{}/{}/git/ref/tags/{}".format(
        api_root.rstrip("/"),
        quote(owner, safe=""),
        quote(repository, safe=""),
        quote(tag, safe=""),
    )


def _tag_object_api_url(api_root, owner, repository, object_sha):
    return "{}/repos/{}/{}/git/tags/{}".format(
        api_root.rstrip("/"),
        quote(owner, safe=""),
        quote(repository, safe=""),
        quote(object_sha, safe=""),
    )


def _resolve_tag_commit(api_root, owner, repository, tag, headers, opener):
    tag_ref_url = _tag_api_url(api_root, owner, repository, tag)
    tag_ref = _get_json(tag_ref_url, headers, opener)
    current = tag_ref.get("object") if isinstance(tag_ref, dict) else None
    for _ in range(4):
        if not isinstance(current, dict):
            break
        object_type = current.get("type")
        object_sha = current.get("sha")
        if not isinstance(object_sha, str) or not object_sha:
            break
        if object_type == "commit":
            return object_sha
        if object_type != "tag":
            break
        tag_object = _get_json(
            _tag_object_api_url(api_root, owner, repository, object_sha),
            headers,
            opener,
        )
        current = tag_object.get("object") if isinstance(tag_object, dict) else None
    raise ReleasePreflightError(
        "tag {} does not resolve to a commit".format(tag)
    )


def _validate_download_url(dependency, owner, repository):
    parsed = urlparse(dependency["url"])
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise ReleasePreflightError(
            "locked catalog URL must use github.com over HTTPS"
        )
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    expected = [owner, repository, "releases", "download", dependency["tag"]]
    if len(parts) != len(expected) + 1 or parts[: len(expected)] != expected:
        raise ReleasePreflightError(
            "locked catalog URL does not identify the locked repository and release"
        )
    asset_name = parts[-1]
    if (
        not asset_name
        or asset_name in {".", ".."}
        or "/" in asset_name
        or "\\" in asset_name
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in asset_name
        )
    ):
        raise ReleasePreflightError("locked catalog URL has no safe asset name")
    return asset_name


def _validate_archive_prefix(dependency, asset_name):
    prefix_parts = dependency["archive_prefix"].split("/")
    if len(prefix_parts) < 3:
        raise ReleasePreflightError("locked archive prefix is incomplete")
    if not asset_name.endswith(".tar.gz"):
        raise ReleasePreflightError("locked catalog asset is not a gzip tar archive")
    archive_root = asset_name[: -len(".tar.gz")]
    if prefix_parts[0] != archive_root:
        raise ReleasePreflightError(
            "locked archive prefix does not match the release asset name"
        )


def _check_asset_reachable(url, headers, opener):
    request = Request(url, headers=headers, method="HEAD")
    try:
        response = opener(request, timeout=REQUEST_TIMEOUT)
    except HTTPError as error:
        status = error.code
        error.close()
        raise ReleasePreflightError(
            "locked catalog asset is not reachable (HTTP {})".format(status)
        )
    except URLError as error:
        raise ReleasePreflightError(
            "locked catalog asset is not reachable: {}".format(error.reason)
        )
    except OSError as error:
        raise ReleasePreflightError(
            "locked catalog asset is not reachable: {}".format(error)
        )
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    response.close()
    if status < 200 or status >= 400:
        raise ReleasePreflightError(
            "locked catalog asset is not reachable (HTTP {})".format(status)
        )


def preflight(
    lock_path,
    *,
    api_root=API_ROOT,
    token=None,
    json_opener=urlopen,
    asset_opener=urlopen,
):
    """Validate the locked release metadata and reachable download asset."""

    lock_path = Path(lock_path)
    try:
        dependency = load_lock(lock_path)
    except DependencyError as error:
        raise ReleasePreflightError("invalid catalog lock: {}".format(error))

    repository_parts = dependency["repository"].split("/")
    if len(repository_parts) != 2 or not all(repository_parts):
        raise ReleasePreflightError("locked catalog repository must be owner/name")
    owner, repository = repository_parts
    if dependency["repository"] != "atrinik/content":
        raise ReleasePreflightError(
            "locked catalog repository must be atrinik/content"
        )
    asset_name = _validate_download_url(dependency, owner, repository)
    _validate_archive_prefix(dependency, asset_name)

    headers = _headers(token if token is not None else os.environ.get("GITHUB_TOKEN"))
    release_url = _release_api_url(
        api_root, owner, repository, dependency["tag"]
    )
    release = _get_json(release_url, headers, json_opener)
    if (
        not isinstance(release, dict)
        or release.get("tag_name") != dependency["tag"]
    ):
        raise ReleasePreflightError(
            "GitHub release tag does not match the catalog lock"
        )
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ReleasePreflightError(
            "locked Content release is draft or prerelease, not a published stable release"
        )
    if not release.get("published_at"):
        raise ReleasePreflightError("locked Content release has no publication timestamp")

    release_commit = _resolve_tag_commit(
        api_root, owner, repository, dependency["tag"], headers, json_opener
    )
    if release_commit != dependency["commit"]:
        raise ReleasePreflightError(
            "locked Content tag resolves to {}, expected {}".format(
                release_commit, dependency["commit"]
            )
        )

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleasePreflightError("GitHub release has no asset inventory")
    matching_assets = [
        asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name") == asset_name
    ]
    if len(matching_assets) != 1:
        raise ReleasePreflightError(
            "locked catalog asset {} is missing or duplicated in the release".format(
                asset_name
            )
        )
    asset = matching_assets[0]
    if asset.get("state") != "uploaded":
        raise ReleasePreflightError(
            "locked catalog asset {} is not uploaded".format(asset_name)
        )
    if asset.get("browser_download_url") != dependency["url"]:
        raise ReleasePreflightError(
            "locked catalog asset URL does not match the release asset"
        )
    if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
        raise ReleasePreflightError(
            "locked catalog asset {} has no positive size".format(asset_name)
        )
    _check_asset_reachable(dependency["url"], _headers(None), asset_opener)
    return {
        "asset": asset_name,
        "commit": release_commit,
        "repository": dependency["repository"],
        "tag": dependency["tag"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).with_name("catalog.lock.json"),
        help="path to the catalog lock (default: catalog.lock.json)",
    )
    args = parser.parse_args(argv)
    try:
        result = preflight(args.lock)
    except ReleasePreflightError as error:
        print("release preflight error: {}".format(error), file=sys.stderr)
        return 1
    print(
        "release preflight passed: {repository} {tag} {commit} {asset}".format(
            **result
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
