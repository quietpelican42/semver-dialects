"""The Masterminds/semver v3 dialect (Helm chart constraints).

Derived from github.com/Masterminds/semver/v3 v3.5.0, which is MIT licensed:

    Copyright (C) 2014-2019, Matt Butcher and Matt Farina

The license text ships beside this package as LICENSE-masterminds-semver. The
parsing and checking rules are a port of that library. The one deliberate
departure is `_VALID`: the original validation regex backtracks exponentially
under Python's `re` (and under any backtracking engine), so an equivalent
unambiguous pattern replaces it. See the README for how the two were compared.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ._go import (
    ALNUM_HYPHEN,
    DIGITS,
    ConstraintError,
    VersionError,
    only,
    parse_uint64,
    quote,
    stable_sort,
    utf8_len,
)

__all__ = [
    "MAX_CONSTRAINT_GROUPS",
    "MAX_CONSTRAINT_LEN",
    "MAX_VERSION_LEN",
    "Constraints",
    "ConstraintError",
    "Version",
    "VersionError",
    "sort_versions",
]

MAX_VERSION_LEN = 256
MAX_CONSTRAINT_LEN = 512
MAX_CONSTRAINT_GROUPS = 32

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

_IDENT = r"[0-9A-Za-z\-]+(?:\.[0-9A-Za-z\-]+)*"
_LOOSE = re.compile(
    r"v?([0-9]+)(\.[0-9]+)?(\.[0-9]+)?"
    r"(-(" + _IDENT + r"))?"
    r"(\+(" + _IDENT + r"))?"
)


def _validate_prerelease(p: str) -> None:
    for part in p.split("."):
        if part == "":
            raise VersionError("invalid prerelease string")
        if only(part, DIGITS):
            if len(part) > 1 and part[0] == "0":
                raise VersionError("version segment starts with 0")
        elif not only(part, ALNUM_HYPHEN):
            raise VersionError("invalid prerelease string")


def _validate_metadata(m: str) -> None:
    for part in m.split("."):
        if part == "" or not only(part, ALNUM_HYPHEN):
            raise VersionError("invalid metadata string")


def _segment(s: str) -> int:
    try:
        return parse_uint64(s)
    except ValueError as e:
        raise VersionError(f"error parsing version segment: {e}") from None


@dataclass(frozen=True, slots=True)
class Version:
    """A parsed version. Metadata is kept but ignored by comparison."""

    major: int
    minor: int
    patch: int
    prerelease: str
    metadata: str
    original: str

    @classmethod
    def parse(cls, text: str) -> Version:
        """Parse like Go's NewVersion: `v` prefix and missing minor/patch are accepted."""
        if not isinstance(text, str):
            raise TypeError("version must be a str")
        if utf8_len(text) > MAX_VERSION_LEN:
            raise VersionError(f"version string is too long (max {MAX_VERSION_LEN} bytes)")
        m = _LOOSE.fullmatch(text)
        if m is None:
            raise VersionError("invalid semantic version")
        pre = m.group(5) or ""
        meta = m.group(7) or ""
        major = _segment(m.group(1))
        minor = _segment(m.group(2)[1:]) if m.group(2) else 0
        patch = _segment(m.group(3)[1:]) if m.group(3) else 0
        if pre:
            _validate_prerelease(pre)
        if meta:
            _validate_metadata(meta)
        return cls(major, minor, patch, pre, meta, text)

    @classmethod
    def parse_strict(cls, text: str) -> Version:
        """Parse like Go's StrictNewVersion: exactly MAJOR.MINOR.PATCH, no `v`, no leading zeros."""
        if not isinstance(text, str):
            raise TypeError("version must be a str")
        if text == "":
            raise VersionError("version string empty")
        if utf8_len(text) > MAX_VERSION_LEN:
            raise VersionError(f"version string is too long (max {MAX_VERSION_LEN} bytes)")
        parts = text.split(".", 2)
        if len(parts) != 3:
            raise VersionError("invalid semantic version")
        pre = meta = ""
        if "+" in parts[2]:
            parts[2], meta = parts[2].split("+", 1)
            _validate_metadata(meta)
        if "-" in parts[2]:
            parts[2], pre = parts[2].split("-", 1)
            _validate_prerelease(pre)
        for p in parts:
            if not only(p, DIGITS):
                raise VersionError("invalid characters in version")
            if len(p) > 1 and p[0] == "0":
                raise VersionError("version segment starts with 0")
        nums: list[int] = []
        for p in parts:
            try:
                nums.append(parse_uint64(p))
            except ValueError as e:
                raise VersionError(str(e)) from None
        return cls(nums[0], nums[1], nums[2], pre, meta, text)

    def __str__(self) -> str:
        """The normalized form: no `v`, all three segments, prerelease and metadata."""
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += "-" + self.prerelease
        if self.metadata:
            s += "+" + self.metadata
        return s

    def compare(self, other: Version) -> int:
        """Return -1, 0 or 1. Prereleases always count; metadata never does."""
        for a, b in ((self.major, other.major), (self.minor, other.minor), (self.patch, other.patch)):
            if a != b:
                return -1 if a < b else 1
        ps, po = self.prerelease, other.prerelease
        if ps == "" and po == "":
            return 0
        if ps == "":
            return 1
        if po == "":
            return -1
        return _compare_prerelease(ps, po)

    def equal(self, other: Version) -> bool:
        return self.compare(other) == 0

    def less_than(self, other: Version) -> bool:
        return self.compare(other) < 0

    def less_than_or_equal(self, other: Version) -> bool:
        return self.compare(other) <= 0

    def greater_than(self, other: Version) -> bool:
        return self.compare(other) > 0

    def greater_than_or_equal(self, other: Version) -> bool:
        return self.compare(other) >= 0


def _compare_prerelease(v: str, o: str) -> int:
    sp = v.split(".")
    op = o.split(".")
    for i in range(max(len(sp), len(op))):
        d = _compare_pre_part(sp[i] if i < len(sp) else "", op[i] if i < len(op) else "")
        if d != 0:
            return d
    return 0


def _as_uint(s: str) -> int | None:
    try:
        return parse_uint64(s)
    except ValueError:
        return None


def _compare_pre_part(s: str, o: str) -> int:
    if s == o:
        return 0
    if s == "":
        return -1
    if o == "":
        return 1
    si = _as_uint(s)
    oi = _as_uint(o)
    if si is None and oi is None:
        return 1 if s > o else -1
    if oi is None:
        return -1  # s is a number, o is a string
    if si is None:
        return 1
    return 1 if si > oi else -1


def sort_versions(versions: Sequence[Version]) -> list[Version]:
    """Order versions as Go's sort.Stable over semver.Collection would."""
    return stable_sort(versions, lambda a, b: a.compare(b) < 0)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

_W = r"[\t\n\f\r ]"
_CV = (
    r"v?([0-9|xX*]+)(\.[0-9|xX*]+)?(\.[0-9|xX*]+)?"
    r"(-(" + _IDENT + r"))?"
    r"(\+(" + _IDENT + r"))?"
)
# Same alternatives, in the same order, as the Go source (the empty one is deliberate).
_OPS = r"=||!=|>|<|>=|=>|<=|=<|~|~>|\^"

_CONSTRAINT = re.compile(rf"{_W}*({_OPS}){_W}*({_CV}){_W}*")
_RANGE = re.compile(rf"{_W}*({_CV}){_W}+-{_W}+({_CV}){_W}*")
# Group holding the second version: the first wrapper is group 1 and _CV opens seven groups.
_RANGE_TO = 9
assert _RANGE.groups == 16 and re.compile(_CV).groups == 7
_FIND = re.compile(rf"(?:{_OPS}){_W}*(?:{_CV})")

# Unambiguous replacement for Go's validConstraintRegex. The Go pattern lets
# whitespace between two constraints be split between four adjacent `\s*`/`\s+`
# groups (an empty operator makes them adjacent), which is exponential on a
# failing match. Here an operator, when present, is non-empty, and the separator
# between constraints is either whitespace or a comma with optional whitespace
# on both sides, so each accepted string has exactly one parse.
_NEOP = r"(?:!=|>=|=>|<=|=<|~>|~|>|<|=|\^)"
_V = (
    r"v?[0-9|xX*]+(?:\.[0-9|xX*]+)?(?:\.[0-9|xX*]+)?"
    r"(?:-" + _IDENT + r")?"
    r"(?:\+" + _IDENT + r")?"
)
_SEG = rf"(?:{_NEOP}{_W}*)?{_V}"
_VALID = re.compile(rf"{_W}*{_SEG}(?:(?:{_W}+|{_W}*,{_W}*){_SEG})*{_W}*")


def _is_x(s: str) -> bool:
    return s in ("x", "*", "X")


@dataclass(frozen=True, slots=True)
class _Constraint:
    con: Version
    orig: str
    op: str
    minor_dirty: bool
    patch_dirty: bool
    dirty: bool

    def __str__(self) -> str:
        return self.op + self.orig


def _improper(text: str) -> ConstraintError:
    return ConstraintError(f"improper constraint: {quote(text)}")


def _parse_constraint(text: str) -> _Constraint:
    m = _CONSTRAINT.fullmatch(text)
    if m is None:
        raise _improper(text)
    op = m.group(1)
    orig = m.group(2)
    g3, g4, g5, g6 = (m.group(i) or "" for i in (3, 4, 5, 6))
    ver = orig
    minor_dirty = patch_dirty = dirty = False
    if _is_x(g3) or g3 == "":
        ver = "0.0.0" + g6
        dirty = True
    elif _is_x(g4.removeprefix(".")) or g4 == "":
        minor_dirty = dirty = True
        ver = f"{g3}.0.0{g6}"
    elif _is_x(g5.removeprefix(".")) or g5 == "":
        dirty = patch_dirty = True
        ver = f"{g3}{g4}.0{g6}"
    try:
        con = Version.parse(ver)
    except VersionError:
        raise ConstraintError("constraint parser error") from None
    return _Constraint(con, orig, op, minor_dirty, patch_dirty, dirty)


_PRE = "{} is a prerelease version and the constraint is only looking for release versions"


def _pre_msg(v: Version) -> str:
    return _PRE.format(quote(str(v)))


def _not_eq(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    equal_msg = f"{quote(str(v))} is equal to {quote(c.orig)}"
    if c.dirty:
        if c.con.major != v.major:
            return True, None
        if c.con.minor != v.minor and not c.minor_dirty:
            return True, None
        elif c.minor_dirty:
            return False, equal_msg
        elif c.con.patch != v.patch and not c.patch_dirty:
            return True, None
        elif c.patch_dirty:
            if v.prerelease or c.con.prerelease:
                if _compare_prerelease(v.prerelease, c.con.prerelease) != 0:
                    return True, None
                return False, equal_msg
            return False, equal_msg
    if v.equal(c.con):
        return False, equal_msg
    return True, None


def _gt(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    fail = f"{quote(str(v))} is less than or equal to {quote(c.orig)}"
    if not c.dirty:
        return (True, None) if v.compare(c.con) == 1 else (False, fail)
    if v.major > c.con.major:
        return True, None
    elif v.major < c.con.major:
        return False, fail
    elif c.minor_dirty:
        return False, fail
    elif c.patch_dirty:
        return (True, None) if v.minor > c.con.minor else (False, fail)
    return (True, None) if v.compare(c.con) == 1 else (False, fail)


def _lt(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    if v.compare(c.con) < 0:
        return True, None
    return False, f"{quote(str(v))} is greater than or equal to {quote(c.orig)}"


def _ge(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    if v.compare(c.con) >= 0:
        return True, None
    return False, f"{quote(str(v))} is less than {quote(c.orig)}"


def _le(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    fail = f"{quote(str(v))} is greater than {quote(c.orig)}"
    if not c.dirty:
        return (True, None) if v.compare(c.con) <= 0 else (False, fail)
    if v.major > c.con.major:
        return False, fail
    elif v.major == c.con.major and v.minor > c.con.minor and not c.minor_dirty:
        return False, fail
    return True, None


def _tilde(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    if v.less_than(c.con):
        return False, f"{quote(str(v))} is less than {quote(c.orig)}"
    if (
        c.con.major == 0
        and c.con.minor == 0
        and c.con.patch == 0
        and not c.minor_dirty
        and not c.patch_dirty
    ):
        return True, None
    if v.major != c.con.major:
        return False, f"{quote(str(v))} does not have same major version as {quote(c.orig)}"
    if v.minor != c.con.minor and not c.minor_dirty:
        return False, f"{quote(str(v))} does not have same major and minor version as {quote(c.orig)}"
    return True, None


def _tilde_or_equal(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    if c.dirty:
        return _tilde(v, c, inc)
    if v.equal(c.con):
        return True, None
    return False, f"{quote(str(v))} is not equal to {quote(c.orig)}"


def _caret(v: Version, c: _Constraint, inc: bool) -> tuple[bool, str | None]:
    if v.prerelease and not inc:
        return False, _pre_msg(v)
    if v.less_than(c.con):
        return False, f"{quote(str(v))} is less than {quote(c.orig)}"
    qv, qo = quote(str(v)), quote(c.orig)
    if c.con.major > 0 or c.minor_dirty:
        if v.major == c.con.major:
            return True, None
        return False, f"{qv} does not have same major version as {qo}"
    if c.con.major == 0 and v.major > 0:
        return False, f"{qv} does not have same major version as {qo}"
    if c.con.minor > 0 or c.patch_dirty:
        if v.minor == c.con.minor:
            return True, None
        return False, (
            f"{qv} does not have same minor version as {qo}. "
            "Expected minor versions to match when constraint major version is 0"
        )
    if c.con.minor == 0 and v.minor > 0:
        return False, f"{qv} does not have same minor version as {qo}"
    if c.con.patch == v.patch:
        return True, None
    return False, f"{qv} does not equal {qo}. Expect version and constraint to equal when major and minor versions are 0"


_CHECKS = {
    "": _tilde_or_equal,
    "=": _tilde_or_equal,
    "!=": _not_eq,
    ">": _gt,
    "<": _lt,
    ">=": _ge,
    "=>": _ge,
    "<=": _le,
    "=<": _le,
    "~": _tilde,
    "~>": _tilde,
    "^": _caret,
}


def _rewrite_range(text: str) -> str:
    out = text
    for m in _RANGE.finditer(text):
        out = out.replace(m.group(0), f">= {m.group(1)}, <= {m.group(_RANGE_TO)} ", 1)
    return out


class Constraints:
    """One or more constraints a Version can be checked against.

    `include_prerelease` may be changed after parsing, as Go's public field can.
    """

    __slots__ = ("_groups", "_has_pre", "include_prerelease")

    def __init__(self, groups: list[list[_Constraint]], has_pre: list[bool], include_prerelease: bool) -> None:
        self._groups = groups
        self._has_pre = has_pre
        self.include_prerelease = include_prerelease

    @classmethod
    def parse(cls, text: str, *, include_prerelease: bool = False) -> Constraints:
        """Parse like Go's NewConstraint. Raises ConstraintError with Go's message."""
        if not isinstance(text, str):
            raise TypeError("constraint must be a str")
        if utf8_len(text) > MAX_CONSTRAINT_LEN:
            raise ConstraintError(f"constraint string is too long (max {MAX_CONSTRAINT_LEN} bytes)")
        text = _rewrite_range(text)
        ors = text.split("||")
        if len(ors) > MAX_CONSTRAINT_GROUPS:
            raise ConstraintError(f"too many constraint groups (max {MAX_CONSTRAINT_GROUPS})")
        groups: list[list[_Constraint]] = []
        has_pre: list[bool] = []
        for seg in ors:
            if _VALID.fullmatch(seg) is None:
                raise _improper(seg)
            found = [m.group(0) for m in _FIND.finditer(seg)] or [seg]
            group = [_parse_constraint(s) for s in found]
            groups.append(group)
            has_pre.append(any(c.con.prerelease != "" for c in group))
        return cls(groups, has_pre, include_prerelease)

    def check(self, v: Version) -> bool:
        """True when some OR group is satisfied by v."""
        for i, group in enumerate(self._groups):
            inc = self.include_prerelease or self._has_pre[i]
            if all(_CHECKS[c.op](v, c, inc)[0] for c in group):
                return True
        return False

    def validate(self, v: Version) -> tuple[bool, list[str]]:
        """Like Check, but also return Go's reasons for each failure."""
        reasons: list[str] = []
        pre_reported = False
        for i, group in enumerate(self._groups):
            ok = True
            inc = self.include_prerelease or self._has_pre[i]
            for c in group:
                if not self.include_prerelease and not self._has_pre[i] and v.prerelease:
                    if not pre_reported:
                        reasons.append(_pre_msg(v))
                        pre_reported = True
                    ok = False
                else:
                    _, err = _CHECKS[c.op](v, c, inc)
                    if err is not None:
                        reasons.append(err)
                        ok = False
            if ok:
                return True, []
        return False, reasons

    def __str__(self) -> str:
        return " || ".join(" ".join(str(c) for c in group) for group in self._groups)

    def __repr__(self) -> str:
        return f"Constraints({str(self)!r})"
