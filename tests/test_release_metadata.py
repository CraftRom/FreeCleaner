import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_release_metadata.py"
spec = importlib.util.spec_from_file_location("release_meta", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_parse_tag_and_full_version():
    assert module.parse_release_tag("v1.2.0.0-build-60") == ("1.2.0.0", 60, "")
    assert module.expected_full_version("v1.2-rc1-build-7") == "1.2.0.0-build-7"


def test_reject_tag_without_build():
    try:
        module.parse_release_tag("v1.2.0")
    except ValueError:
        pass
    else:
        raise AssertionError("tag without build number must be rejected")


def test_normalizes_short_and_zero_padded_versions():
    assert module.normalize_windows_version("1.02") == "1.2.0.0"
    assert module.expected_full_version("v1.2-beta2-build-9") == "1.2.0.0-build-9"
