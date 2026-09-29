"""Behavior the README shows. test_live_go.py re-checks these exact inputs against Go."""

from __future__ import annotations

import pytest

from semver_dialects import hashicorp, masterminds
from semver_dialects._go import quote, stable_sort

MM_EXAMPLES = [
    "^1.2.3 || >=3.0.0-beta.1 <3.1.0",
    ">=1.2.0",
    "1.2.3 - 2.3.4",
    "~> 1.2",
    ">=1.2.3, <2.0.0",
    "!=1.2.x",
    "1.x || 2.x",
]
MM_VERSIONS = ["1.9.0", "3.0.0-beta.2", "0.9.0", "1.3.0-beta", "v1.2", "1.2.3+build.5", "2.5.0"]
HV_EXAMPLES = ["~> 1.2", "~> 1.2.0", "~> 1.2.3.4", ">= 1.0, < 2.0", ">= 1.0.0-beta", "= 1.0", "!= 1.2.3", " >= 1.0 , < 2 "]
HV_VERSIONS = ["1.9.0", "1.3.0", "1.2.3.5", "1.0beta", "1.0.0-beta1", "1.2", "v1.2.3", "2.0.0"]


def test_masterminds_version_forms() -> None:
    v = masterminds.Version.parse("v1.2-beta.1+build.5")
    assert (v.major, v.minor, v.patch, v.prerelease, v.metadata) == (1, 2, 0, "beta.1", "build.5")
    assert str(v) == "1.2.0-beta.1+build.5"
    assert v.original == "v1.2-beta.1+build.5"
    with pytest.raises(masterminds.VersionError, match="^invalid semantic version$"):
        masterminds.Version.parse("1.2.3.4")
    with pytest.raises(masterminds.VersionError, match="^version segment starts with 0$"):
        masterminds.Version.parse("1.2.3-01")
    assert masterminds.Version.parse("01.2.3").major == 1  # the default path coerces leading zeros
    with pytest.raises(masterminds.VersionError, match="^version segment starts with 0$"):
        masterminds.Version.parse_strict("01.2.3")
    with pytest.raises(masterminds.VersionError, match="^invalid semantic version$"):
        masterminds.Version.parse_strict("1.2")


def test_masterminds_compare_ignores_metadata_and_orders_prereleases() -> None:
    p = masterminds.Version.parse
    assert p("1.2.3+a").equal(p("1.2.3+b"))
    assert p("1.0.0-alpha").less_than(p("1.0.0-alpha.1")) and p("1.0.0-alpha.1").less_than(p("1.0.0-beta"))
    assert p("1.0.0-2").less_than(p("1.0.0-10")) and p("1.0.0-10").less_than(p("1.0.0-a"))
    assert p("1.0.0-rc.1").less_than(p("1.0.0"))
    assert [str(v) for v in masterminds.sort_versions([p("2.0.0"), p("1.0.0-b"), p("1.0.0"), p("1.0.0-a")])] == [
        "1.0.0-a", "1.0.0-b", "1.0.0", "2.0.0",
    ]


def test_masterminds_constraints() -> None:
    c = masterminds.Constraints.parse("^1.2.3 || >=3.0.0-beta.1 <3.1.0")
    P = masterminds.Version.parse
    assert c.check(P("1.9.0")) and c.check(P("3.0.0-beta.2")) and not c.check(P("2.0.0"))
    ok, reasons = c.validate(P("0.9.0"))
    assert not ok and reasons == ['"0.9.0" is less than "1.2.3"', '"0.9.0" is less than "3.0.0-beta.1"']
    assert str(c) == "^1.2.3 || >=3.0.0-beta.1 <3.1.0"
    assert masterminds.Constraints.parse("1.2.3 - 2.3.4").check(P("2.0.0"))
    assert str(masterminds.Constraints.parse("1.2.3 - 2.3.4")) == ">=1.2.3 <=2.3.4"


def test_masterminds_include_prerelease() -> None:
    P = masterminds.Version.parse
    plain = masterminds.Constraints.parse(">=1.2.0")
    assert not plain.check(P("1.3.0-beta"))
    ok, reasons = plain.validate(P("1.3.0-beta"))
    assert not ok and "is a prerelease version" in reasons[0]
    assert masterminds.Constraints.parse(">=1.2.0", include_prerelease=True).check(P("1.3.0-beta"))
    plain.include_prerelease = True  # the flag can be changed after parsing
    assert plain.check(P("1.3.0-beta"))


def test_masterminds_error_texts_use_go_quoting() -> None:
    with pytest.raises(masterminds.ConstraintError) as e:
        masterminds.Constraints.parse(">=1.0 é\n")
    assert str(e.value) == 'improper constraint: ">=1.0 é\\n"'
    with pytest.raises(masterminds.ConstraintError, match="^constraint string is too long"):
        masterminds.Constraints.parse("1" * 513)
    with pytest.raises(masterminds.ConstraintError, match="^too many constraint groups"):
        masterminds.Constraints.parse("||".join(["1"] * 33))


def test_hashicorp_version_forms() -> None:
    h = hashicorp.Version.parse
    v = h("v1.2.3.4-beta+meta")
    assert v.segments == (1, 2, 3, 4) and v.prerelease == "beta" and v.metadata == "meta"
    assert str(v) == "1.2.3.4-beta+meta" and v.original == "v1.2.3.4-beta+meta"
    assert h("1.2").segments == (1, 2, 0) and h("1.2").specificity == 2
    assert h("1.0beta").prerelease == "beta"  # no hyphen needed
    assert str(h("1.04.0")) == "1.4.0"
    assert str(h("1.2.3-beta+meta").core()) == "1.2.3"
    with pytest.raises(hashicorp.VersionError, match="^malformed version: 1.0.x$"):
        h("1.0.x")
    with pytest.raises(hashicorp.VersionError, match="^malformed version: 1.0beta$"):
        hashicorp.Version.parse_semver("1.0beta")
    with pytest.raises(hashicorp.VersionError, match="value out of range"):
        h("9223372036854775808")


def test_hashicorp_compare_treats_missing_segments_as_zero() -> None:
    h = hashicorp.Version.parse
    assert h("1.0").equal(h("1.0.0.0")) and h("1.0.0.1").greater_than(h("1.0"))
    assert h("1.0.0-beta").less_than(h("1.0.0")) and h("1.0.0-beta").less_than(h("1.0.0-rc"))
    assert h("1.0.0-1").compare(h("1.0.0-01")) == -1 and h("1.0.0-01").compare(h("1.0.0-1")) == -1


def test_hashicorp_constraints() -> None:
    h = hashicorp.Version.parse
    c = hashicorp.Constraints.parse("~> 1.2")
    assert c.check(h("1.9.0")) and not c.check(h("2.0.0")) and not c.check(h("1.1.0"))
    c = hashicorp.Constraints.parse("~> 1.2.0")
    assert c.check(h("1.2.9")) and not c.check(h("1.3.0"))
    c = hashicorp.Constraints.parse("~> 1.2.3.4")
    assert c.check(h("1.2.3.5")) and not c.check(h("1.2.4.0"))
    assert not hashicorp.Constraints.parse(">= 1.0").check(h("1.5.0-beta"))  # prereleases need a prerelease bound
    assert hashicorp.Constraints.parse(">= 1.0.0-beta").check(h("1.0.0-rc"))
    raw = " >= 1.0 , < 2 "
    assert str(hashicorp.Constraints.parse(raw)) == raw  # originals are kept verbatim
    with pytest.raises(hashicorp.ConstraintError, match="^malformed constraint: >> 1$"):
        hashicorp.Constraints.parse(">> 1")


def test_hashicorp_constraint_sort_order() -> None:
    c = hashicorp.Constraints.parse(">= 1.0,~> 2.0,!= 3.0,< 4.0,= 5.0,<= 6.0,> 7.0")
    assert str(c.sorted()) == "< 4.0,= 5.0,> 7.0,~> 2.0,!= 3.0,<= 6.0,>= 1.0"
    ops = [s.split()[0] for s in str(c.sorted()).split(",")]
    assert ops == ["<", "=", ">", "~>", "!=", "<=", ">="]


def test_quote_matches_go_strconv_quote() -> None:
    assert quote("plain") == '"plain"'
    assert quote('a"b\\c') == '"a\\"b\\\\c"'
    assert quote("\t\n\r\a\b\f\v") == '"\\t\\n\\r\\a\\b\\f\\v"'
    assert quote("\x00\x1f\x7f") == '"\\x00\\x1f\\x7f"'
    assert quote("é日") == '"é日"'
    assert quote(" \u0085 ﻿") == '"\\u00a0\\u0085\\u2028\\ufeff"'
    assert quote("\U0001f600") == '"\U0001f600"'
    assert quote("\U000e0001") == '"\\U000e0001"'
    assert quote("\ud800") == '"\\xed\\xa0\\x80"'


def test_stable_sort_is_stable_and_handles_all_sizes() -> None:
    for n in (0, 1, 2, 19, 20, 21, 40, 41, 100, 333):
        items = [(i * 7919 % 13, i) for i in range(n)]
        out = stable_sort(items, lambda a, b: a[0] < b[0])
        assert out == sorted(items, key=lambda t: t[0])


def test_wrong_types_are_rejected() -> None:
    with pytest.raises(TypeError):
        masterminds.Version.parse(1.2)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hashicorp.Constraints.parse(None)  # type: ignore[arg-type]
