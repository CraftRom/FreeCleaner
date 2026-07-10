import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_release_metadata.py"
spec = importlib.util.spec_from_file_location("release_meta", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_parse_tag_with_embedded_build_and_full_version():
    assert module.parse_release_tag("v1.2.0.0-build-60") == ("1.2.0.0", 60, "")
    assert module.expected_full_version("v1.2-rc1-build-7") == "1.2.0.0-build-7"


def test_accepts_short_release_tag_with_external_build_number():
    assert module.parse_release_tag("v1.4") == ("1.4", None, "")
    assert module.expected_full_version("v1.4", 73) == "1.4.0.0-build-73"
    assert (
        module.resolve_build_number("v1.4", 73, "1.4.0.0-build-73") == 73
    )


def test_accepts_short_prerelease_tag():
    assert module.parse_release_tag("v1.4-beta2") == ("1.4", None, "beta2")
    assert module.expected_full_version("v1.4-beta2", 9) == "1.4.0.0-build-9"


def test_rejects_missing_build_resolution_for_short_tag():
    with pytest.raises(ValueError, match="does not contain a build number"):
        module.expected_full_version("v1.4")


def test_rejects_conflicting_build_numbers():
    with pytest.raises(ValueError, match="build number mismatch"):
        module.resolve_build_number("v1.4-build-10", 11, "1.4.0.0-build-10")


def test_normalizes_short_and_zero_padded_versions():
    assert module.normalize_windows_version("1.02") == "1.2.0.0"
    assert module.expected_full_version("v1.2-beta2-build-9") == "1.2.0.0-build-9"
