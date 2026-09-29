"""The hashicorp/go-version dialect (Terraform, Packer, Nomad constraints).

hashicorp/go-version is MPL-2.0. This module is an independent implementation
of its observable behavior, written from measured output rather than from its
source, and shares no code with it. Every rule below was confirmed against
go-version v1.9.0 by the differential tests.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ._go import WS, ConstraintError, VersionError, parse_int64, stable_sort

__all__ = [
    "Constraints",
    "ConstraintError",
    "Version",
    "VersionError",
    "sort_versions",
]

# A dotted run of identifier characters. Prerelease and metadata are both made of these.
_TAIL = r"[0-9A-Za-z\-~]+(?:\.[0-9A-Za-z\-~]+)*"
_META = re.compile(_TAIL)
# A prerelease that starts with a letter, hyphen or tilde (a digit start is handled apart).
_WORD_PRE = re.compile(r"[A-Za-z\-~][0-9A-Za-z\-~]*(?:\.[0-9A-Za-z\-~]+)*")
_CORE = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_DIGIT_CHARS = tuple("0123456789")


def _split(text: str, strict: bool) -> tuple[str, str, str] | None:
    """Split into (numeric core, prerelease, metadata), or None when malformed.

    The prerelease may be introduced by a hyphen. Without a hyphen (`1.0beta`) it
    must start with a letter or tilde, and a hyphen-less form is refused when
    `strict` is set. A hyphen followed by a digit is always a separator; a
    hyphen followed by anything else is a separator only if what follows is a
    valid prerelease, otherwise the hyphen belongs to the prerelease itself
    (`1.0-` has prerelease `-`).
    """
    core = _CORE.match(text, 1 if text.startswith("v") else 0)
    if core is None:
        return None
    rest = text[core.end() :]
    meta = ""
    plus = rest.find("+")
    if plus != -1:
        meta = rest[plus + 1 :]
        rest = rest[:plus]
        if _META.fullmatch(meta) is None:
            return None
    if rest == "":
        return core.group(), "", meta
    after = rest[1:]
    if rest[0] == "-":
        if after[:1] in _DIGIT_CHARS and after:
            return (core.group(), after, meta) if _META.fullmatch(after) else None
        if _WORD_PRE.fullmatch(after):
            return core.group(), after, meta
        if not strict and _WORD_PRE.fullmatch(rest):
            return core.group(), rest, meta
        return None
    if not strict and _WORD_PRE.fullmatch(rest):
        return core.group(), rest, meta
    return None


def _numeric(part: str) -> tuple[bool, int]:
    """(is numeric, value) the way the comparison sees a prerelease part.

    The value is meaningful even for a non-numeric part: a syntax error reads as
    0 and an out-of-range number reads as the clamped limit, and the comparison
    falls back on that value in one branch.
    """
    value, err = parse_int64(part)
    return err is None, value


def _compare_part(a: str, b: str) -> int:
    if a == b:
        return 0
    a_num, a_val = _numeric(a)
    b_num, b_val = _numeric(b)
    if a == "":
        return -1 if b_num else 1
    if b == "":
        return 1 if a_num else -1
    if a_num and not b_num:
        return -1
    if not a_num and b_num:
        return 1
    if not a_num and not b_num and a > b:
        return 1
    if a_val > b_val:
        return 1
    return -1


def _compare_prerelease(a: str, b: str) -> int:
    if a == b:
        return 0
    pa, pb = a.split("."), b.split(".")
    for i in range(max(len(pa), len(pb))):
        d = _compare_part(pa[i] if i < len(pa) else "", pb[i] if i < len(pb) else "")
        if d != 0:
            return d
    return 0


@dataclass(frozen=True, slots=True)
class Version:
    """A parsed version with any number of numeric segments (at least three)."""

    segments: tuple[int, ...]
    #: How many numeric segments the input spelled out (`1.2` gives 2 and segments (1, 2, 0)).
    specificity: int
    prerelease: str
    metadata: str
    original: str

    @classmethod
    def _build(cls, text: str, strict: bool) -> Version:
        parts = _split(text, strict)
        if parts is None:
            raise VersionError(f"malformed version: {text}")
        core, pre, meta = parts
        nums: list[int] = []
        for piece in core.split("."):
            value, err = parse_int64(piece)
            if err is not None:
                raise VersionError(f"error parsing version: {err}")
            nums.append(value)
        given = len(nums)
        nums.extend([0] * (3 - given))
        return cls(tuple(nums), given, pre, meta, text)

    @classmethod
    def parse(cls, text: str) -> Version:
        """Parse like Go's NewVersion: `v` prefix, any segment count, prerelease with or without a hyphen."""
        if not isinstance(text, str):
            raise TypeError("version must be a str")
        return cls._build(text, False)

    @classmethod
    def parse_semver(cls, text: str) -> Version:
        """Parse like Go's NewSemver: a prerelease needs its hyphen."""
        if not isinstance(text, str):
            raise TypeError("version must be a str")
        return cls._build(text, True)

    def __str__(self) -> str:
        """The normalized form: no `v`, padded to three segments, no leading zeros."""
        s = ".".join(str(n) for n in self.segments)
        if self.prerelease:
            s += "-" + self.prerelease
        if self.metadata:
            s += "+" + self.metadata
        return s

    def core(self) -> Version:
        """The first three segments only, without prerelease or metadata."""
        return Version._build("%d.%d.%d" % self.segments[:3], False)

    def compare(self, other: Version) -> int:
        """Return -1, 0 or 1.

        Segments are compared first, with missing trailing segments read as
        zero; the prerelease is consulted only when both versions have the same
        number of segments with the same values.
        """
        if self.segments == other.segments:
            a, b = self.prerelease, other.prerelease
            if a == "" and b == "":
                return 0
            if a == "":
                return 1
            if b == "":
                return -1
            return _compare_prerelease(a, b)
        sa, sb = self.segments, other.segments
        for i in range(max(len(sa), len(sb))):
            if i >= len(sa):
                return 0 if not any(sb[i:]) else -1
            if i >= len(sb):
                return 0 if not any(sa[i:]) else 1
            if sa[i] != sb[i]:
                return -1 if sa[i] < sb[i] else 1
        return 0

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


def sort_versions(versions: Sequence[Version]) -> list[Version]:
    """Order versions as Go's sort.Stable over version.Collection would.

    The comparison is not always antisymmetric (prerelease parts `1` and `01`),
    so the result can depend on the algorithm; Go's is reproduced.
    """
    return stable_sort(versions, lambda a, b: a.compare(b) < 0)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

# Operators in the order Go tries them; "" means equality.
_OPERATORS = ("<=", ">=", "!=", "~>", "<", ">", "=", "")

# Sort key per operator. Go orders by the operator's rune value, which puts
# < = > ~ before the three non-ASCII symbols it uses for !=, <= and >=.
_RANK = {"<": 0, "=": 1, ">": 2, "~>": 3, "!=": 4, "<=": 5, ">=": 6}


def _prerelease_ok(v: Version, c: Version) -> bool:
    if c.prerelease and v.prerelease:
        return v.segments == c.segments
    if v.prerelease:
        return False
    return True


def _check(op: str, v: Version, c: Version) -> bool:
    if op == "=":
        return v.equal(c)
    if op == "!=":
        return not v.equal(c)
    if op == "~>":
        return _pessimistic(v, c)
    if not _prerelease_ok(v, c):
        return False
    d = v.compare(c)
    if op == ">":
        return d == 1
    if op == "<":
        return d == -1
    if op == ">=":
        return d >= 0
    return d <= 0


def _pessimistic(v: Version, c: Version) -> bool:
    if not _prerelease_ok(v, c) or (c.prerelease and not v.prerelease):
        return False
    if v.less_than(c):
        return False
    width = len(c.segments)
    if width > len(v.segments):
        return False
    for i in range(c.specificity - 1):
        if v.segments[i] != c.segments[i]:
            return False
    return c.segments[width - 1] <= v.segments[width - 1]


@dataclass(frozen=True, slots=True)
class _Constraint:
    op: str
    version: Version
    original: str

    def __str__(self) -> str:
        return self.original


def _parse_single(raw: str) -> _Constraint:
    text = raw.strip(WS)
    op = next(o for o in _OPERATORS if text.startswith(o))
    body = text[len(op) :].lstrip(WS)
    parts = _split(body, False)
    if parts is None:
        raise ConstraintError(f"malformed constraint: {raw}")
    # Errors from here (an out-of-range segment) are reported as version errors.
    return _Constraint(op or "=", Version.parse(body), raw)


class Constraints:
    """A comma-separated list of constraints, all of which must hold."""

    __slots__ = ("_items",)

    def __init__(self, items: Sequence[_Constraint]) -> None:
        self._items = tuple(items)

    @classmethod
    def parse(cls, text: str) -> Constraints:
        """Parse like Go's NewConstraint. Raises ConstraintError or VersionError with Go's message."""
        if not isinstance(text, str):
            raise TypeError("constraint must be a str")
        return cls([_parse_single(piece) for piece in text.split(",")])

    def check(self, v: Version) -> bool:
        """True when v satisfies every constraint."""
        return all(_check(c.op, v, c.version) for c in self._items)

    def sorted(self) -> Constraints:
        """A copy ordered as Go's sort.Stable over Constraints orders it (operator, then version)."""

        def less(a: _Constraint, b: _Constraint) -> bool:
            ra, rb = _RANK[a.op], _RANK[b.op]
            if ra != rb:
                return ra < rb
            return a.version.less_than(b.version)

        return Constraints(stable_sort(self._items, less))

    def __len__(self) -> int:
        return len(self._items)

    def __str__(self) -> str:
        """The original pieces (whitespace included) joined with commas."""
        return ",".join(c.original for c in self._items)

    def __repr__(self) -> str:
        return f"Constraints({str(self)!r})"
