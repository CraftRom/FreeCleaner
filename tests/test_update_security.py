import hashlib
import io
from pathlib import Path

import pytest

from freecleaner import logic


class FakeResponse:
    def __init__(self, body: bytes, *, final_url: str, headers=None, status=200):
        self._stream = io.BytesIO(body)
        self._final_url = final_url
        self.headers = headers or {}
        self.status = status
        self.code = status

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def trusted_url(name="FreeCleaner-1.2.0.0-build-60-win64-setup.exe"):
    return f"https://github.com/CraftRom/FreeCleaner/releases/download/v1.2.0.0-build-60/{name}"


def test_safe_headers_strip_sensitive_values():
    headers = {
        "Authorization": "secret",
        "Set-Cookie": "private",
        "ETag": '"abc"',
        "Content-Length": "123",
    }
    assert logic._safe_response_headers(headers) == {
        "etag": '"abc"',
        "content-length": "123",
    }


def test_asset_selection_includes_digest_and_size(monkeypatch):
    monkeypatch.setattr(logic, "get_update_asset_suffix", lambda: "win64")
    monkeypatch.setattr(logic, "is_update_asset_compatible", lambda _name: True)
    assets = [
        {
            "name": "FreeCleaner-1.2.0.0-build-60-win64-setup.exe",
            "browser_download_url": trusted_url(),
            "size": 42,
            "digest": "sha256:" + "a" * 64,
        }
    ]
    assert logic._select_release_asset_details(assets) == (
        trusted_url(),
        assets[0]["name"],
        42,
        "sha256:" + "a" * 64,
    )


def test_download_rejects_untrusted_initial_url(tmp_path):
    ok, message = logic.download_url_to_file(
        "https://example.com/FreeCleaner.exe", str(tmp_path / "update.exe")
    )
    assert not ok
    assert "trusted" in message.lower()


def test_download_validates_size_and_sha256(monkeypatch, tmp_path):
    body = b"signed-installer-placeholder"
    expected = hashlib.sha256(body).hexdigest()
    response = FakeResponse(
        body,
        final_url="https://release-assets.githubusercontent.com/github-production-release-asset/update.exe",
        headers={
            "Content-Length": str(len(body)),
            "Content-Type": "application/octet-stream",
        },
    )
    monkeypatch.setattr(logic.urllib.request, "urlopen", lambda *_a, **_k: response)
    destination = tmp_path / "update.exe"
    ok, message = logic.download_url_to_file(
        trusted_url(),
        str(destination),
        expected_sha256=expected,
        expected_size=len(body),
    )
    assert ok, message
    assert destination.read_bytes() == body
    assert not Path(str(destination) + ".part").exists()


def test_download_rejects_content_length_mismatch(monkeypatch, tmp_path):
    body = b"short"
    response = FakeResponse(
        body,
        final_url="https://release-assets.githubusercontent.com/update.exe",
        headers={"Content-Length": "99", "Content-Type": "application/octet-stream"},
    )
    monkeypatch.setattr(logic.urllib.request, "urlopen", lambda *_a, **_k: response)
    ok, message = logic.download_url_to_file(
        trusted_url(), str(tmp_path / "update.exe"), expected_size=99
    )
    assert not ok
    assert "byte count" in message.lower()


def test_download_verifies_signature_before_atomic_promotion(monkeypatch, tmp_path):
    body = b"signed-installer-placeholder"
    expected = hashlib.sha256(body).hexdigest()
    response = FakeResponse(
        body,
        final_url="https://release-assets.githubusercontent.com/github-production-release-asset/update.exe",
        headers={
            "Content-Length": str(len(body)),
            "Content-Type": "application/octet-stream",
        },
    )
    seen = {}

    def fake_verify(path, expected_publisher=logic.APP_UPDATE_PUBLISHER):
        seen["path"] = path
        seen["publisher"] = expected_publisher
        assert Path(path).name.endswith(".part")
        assert Path(path).exists()
        assert not (tmp_path / "update.exe").exists()
        return True, "valid", "CN=FreeCleaner"

    monkeypatch.setattr(logic.urllib.request, "urlopen", lambda *_a, **_k: response)
    monkeypatch.setattr(logic, "verify_authenticode_signature", fake_verify)
    destination = tmp_path / "update.exe"
    ok, message = logic.download_url_to_file(
        trusted_url(),
        str(destination),
        expected_sha256=expected,
        expected_size=len(body),
        verify_signature=True,
    )
    assert ok, message
    assert seen["path"].endswith(".part")
    assert destination.read_bytes() == body


def test_retry_delay_uses_rate_limit_reset(monkeypatch):
    monkeypatch.setattr(logic.time, "time", lambda: 1000.0)
    monkeypatch.setattr(logic.random, "uniform", lambda _a, _b: 0.1)
    delay = logic._retry_delay_seconds(
        {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1002"},
        1,
    )
    assert delay == pytest.approx(2.1)


def test_stable_changelog_excludes_drafts_and_prereleases():
    releases = [
        {"tag_name": "v3.0.0", "draft": True, "body": "draft"},
        {"tag_name": "v2.0.0-rc1", "prerelease": True, "body": "pre"},
        {"tag_name": "v1.0.0", "body": "stable"},
    ]
    changelog, count = logic._build_recent_release_changelog(releases)
    assert count == 1
    assert "stable" in changelog
    assert "draft" not in changelog
    assert "pre" not in changelog


def test_github_etag_304_uses_cached_payload(monkeypatch, tmp_path):
    url = "https://api.github.com/repos/CraftRom/FreeCleaner/releases/latest"
    monkeypatch.setattr(logic, "get_user_data_dir", lambda create=True: str(tmp_path))
    cached = {"tag_name": "v1.2.0.0-build-60"}
    logic._write_github_cache(url, cached, '"etag-1"')

    def not_modified(request, timeout=0):
        assert request.headers.get("If-none-match") == '"etag-1"'
        raise logic.urllib.error.HTTPError(url, 304, "Not Modified", {"ETag": '"etag-1"'}, None)

    monkeypatch.setattr(logic.urllib.request, "urlopen", not_modified)
    assert logic._github_api_request(url, max_attempts=1) == cached


def test_github_malformed_json_falls_back_to_cache(monkeypatch, tmp_path):
    url = "https://api.github.com/repos/CraftRom/FreeCleaner/releases/latest"
    monkeypatch.setattr(logic, "get_user_data_dir", lambda create=True: str(tmp_path))
    cached = {"tag_name": "v1.0.0.0-build-1"}
    logic._write_github_cache(url, cached, "")
    response = FakeResponse(b"not-json", final_url=url, headers={"Content-Type": "application/json"})
    monkeypatch.setattr(logic.urllib.request, "urlopen", lambda *_a, **_k: response)
    assert logic._github_api_request(url, max_attempts=1) == cached


def test_plain_403_is_not_retried(monkeypatch):
    url = "https://api.github.com/repos/CraftRom/FreeCleaner/releases/latest"
    calls = {"count": 0}

    def forbidden(*_a, **_k):
        calls["count"] += 1
        raise logic.urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(logic, "_read_github_cache", lambda _url: (None, ""))
    monkeypatch.setattr(logic.urllib.request, "urlopen", forbidden)
    assert logic._github_api_request(url, max_attempts=3) is None
    assert calls["count"] == 1


def test_safe_fs_rejects_root_and_symlink_ancestor(tmp_path):
    assert not logic.SafeFS.is_safe_clean_target(str(Path(tmp_path).anchor))
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    assert not logic.SafeFS.is_safe_clean_target(str(link / "cache"))
