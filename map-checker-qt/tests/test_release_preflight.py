import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError


APP_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(APP_ROOT))

import release_preflight


class Response:
    def __init__(self, payload=b"", status=200):
        self.payload = payload
        self.status = status

    def read(self, limit=-1):
        if limit < 0:
            return self.payload
        return self.payload[:limit]

    def close(self):
        return None

    def getcode(self):
        return self.status


class JsonOpener:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url, timeout))
        response = self.responses[request.full_url]
        if isinstance(response, BaseException):
            raise response
        return Response(json.dumps(response).encode("utf-8"))


class AssetOpener:
    def __init__(self, response=None):
        self.response = response or Response()
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url, timeout))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class ReleasePreflightTests(unittest.TestCase):
    API_ROOT = "https://api.example.test"
    TAG = "v1.2.0"
    COMMIT = "a" * 40
    ASSET = "atrinik-content-1.2.0.tar.gz"
    DOWNLOAD_URL = (
        "https://github.com/atrinik/content/releases/download/"
        "v1.2.0/atrinik-content-1.2.0.tar.gz"
    )

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.temporary_directory.name) / "catalog.lock.json"
        self.write_lock()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_lock(self, **overrides):
        dependency = {
            "name": "content_catalog",
            "repository": "atrinik/content",
            "tag": self.TAG,
            "commit": self.COMMIT,
            "url": self.DOWNLOAD_URL,
            "sha256": "b" * 64,
            "archive_prefix": "atrinik-content-1.2.0/tools/content_catalog",
            "destination": ".dependencies/content_catalog",
        }
        dependency.update(overrides)
        self.lock_path.write_text(
            json.dumps({"schema_version": 1, "dependency": dependency}),
            encoding="utf-8",
        )

    def openers(self, release=None, tag_commit=None, asset_response=None):
        release = release or {
            "tag_name": self.TAG,
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-24T00:00:00Z",
            "assets": [
                {
                    "name": self.ASSET,
                    "state": "uploaded",
                    "size": 123,
                    "browser_download_url": self.DOWNLOAD_URL,
                }
            ],
        }
        tag_commit = tag_commit or self.COMMIT
        responses = {
            release_preflight._release_api_url(
                self.API_ROOT, "atrinik", "content", self.TAG
            ): release,
            release_preflight._tag_api_url(
                self.API_ROOT, "atrinik", "content", self.TAG
            ): {"object": {"type": "commit", "sha": tag_commit}},
        }
        return JsonOpener(responses), AssetOpener(asset_response)

    def run_preflight(self, json_opener, asset_opener):
        return release_preflight.preflight(
            self.lock_path,
            api_root=self.API_ROOT,
            token="",
            json_opener=json_opener,
            asset_opener=asset_opener,
        )

    def test_accepts_published_release_and_reachable_asset(self):
        json_opener, asset_opener = self.openers()

        result = self.run_preflight(json_opener, asset_opener)

        self.assertEqual(
            {
                "asset": self.ASSET,
                "commit": self.COMMIT,
                "repository": "atrinik/content",
                "tag": self.TAG,
            },
            result,
        )
        self.assertEqual("HEAD", asset_opener.calls[0][0])

    def test_reports_missing_release_before_tag_or_asset_checks(self):
        release_url = release_preflight._release_api_url(
            self.API_ROOT, "atrinik", "content", self.TAG
        )
        json_opener = JsonOpener(
            {release_url: HTTPError(release_url, 404, "missing", {}, io.BytesIO())}
        )

        with self.assertRaisesRegex(release_preflight.ReleasePreflightError, "not found"):
            self.run_preflight(json_opener, AssetOpener())

        self.assertEqual(1, len(json_opener.calls))

    def test_reports_missing_asset(self):
        release = {
            "tag_name": self.TAG,
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-24T00:00:00Z",
            "assets": [],
        }
        json_opener, asset_opener = self.openers(release=release)

        with self.assertRaisesRegex(
            release_preflight.ReleasePreflightError, "missing or duplicated"
        ):
            self.run_preflight(json_opener, asset_opener)

        self.assertFalse(asset_opener.calls)

    def test_rejects_draft_release(self):
        release, asset_opener = self.openers(
            release={
                "tag_name": self.TAG,
                "draft": True,
                "prerelease": False,
                "published_at": "2026-08-24T00:00:00Z",
                "assets": [],
            }
        )

        with self.assertRaisesRegex(
            release_preflight.ReleasePreflightError, "draft"
        ):
            self.run_preflight(release, asset_opener)

    def test_rejects_tag_commit_mismatch(self):
        json_opener, asset_opener = self.openers(tag_commit="c" * 40)

        with self.assertRaisesRegex(
            release_preflight.ReleasePreflightError, "expected"
        ):
            self.run_preflight(json_opener, asset_opener)

    def test_rejects_asset_url_mismatch(self):
        release, asset_opener = self.openers(
            release={
                "tag_name": self.TAG,
                "draft": False,
                "prerelease": False,
                "published_at": "2026-08-24T00:00:00Z",
                "assets": [
                    {
                        "name": self.ASSET,
                        "state": "uploaded",
                        "size": 123,
                        "browser_download_url": "https://github.com/atrinik/content/wrong",
                    }
                ],
            }
        )

        with self.assertRaisesRegex(
            release_preflight.ReleasePreflightError, "URL"
        ):
            self.run_preflight(release, asset_opener)

    def test_rejects_unreachable_asset(self):
        json_opener, asset_opener = self.openers(
            asset_response=URLError("offline")
        )

        with self.assertRaisesRegex(
            release_preflight.ReleasePreflightError, "not reachable"
        ):
            self.run_preflight(json_opener, asset_opener)


if __name__ == "__main__":
    unittest.main()
