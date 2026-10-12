import pytest

from veyra.core.semver import Version, VersionError, VersionRange


def test_precedence_follows_semver_spec():
    ordered = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
        "1.0.1",
        "1.1.0",
        "2.0.0",
    ]
    parsed = [Version.parse(v) for v in ordered]
    assert parsed == sorted(parsed)
    assert Version.parse("1.0.0+build.1") == Version.parse("1.0.0")


@pytest.mark.parametrize("bad", ["1", "1.0", "01.0.0", "1.0.0-", "v1.0.0", ""])
def test_rejects_invalid(bad):
    with pytest.raises(VersionError):
        Version.parse(bad)


@pytest.mark.parametrize(
    ("rng", "inside", "outside"),
    [
        (">=1.0.0 <2.0.0", "1.9.9", "2.0.0"),
        (">= 1.0.0, < 2.0.0", "1.0.0", "0.9.9"),
        ("^1.2.3", "1.9.0", "2.0.0"),
        ("^0.2.3", "0.2.9", "0.3.0"),
        ("~1.4.2", "1.4.9", "1.5.0"),
        ("==1.0.0", "1.0.0", "1.0.1"),
        ("!=1.0.0", "1.0.1", "1.0.0"),
    ],
)
def test_ranges(rng, inside, outside):
    r = VersionRange.parse(rng)
    assert r.contains(inside)
    assert not r.contains(outside)


def test_wildcard_range():
    assert VersionRange.parse("*").contains("99.0.0")
