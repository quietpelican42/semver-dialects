"""Masterminds' validConstraintRegex versus the unambiguous replacement in the package.

LEGACY is the Go pattern translated to Python (`\\s` written out as Go defines it,
`$` as `\\Z`). It backtracks exponentially, so it is only ever run on short strings.
"""

from __future__ import annotations

import itertools
import re

import pytest

from semver_dialects import masterminds

W = r"[\t\n\f\r ]"
OPS = r"=||!=|>|<|>=|=>|<=|=<|~|~>|\^"
CV = (
    r"v?([0-9|x|X|\*]+)(\.[0-9|x|X|\*]+)?(\.[0-9|x|X|\*]+)?"
    r"(-([0-9A-Za-z\-]+(\.[0-9A-Za-z\-]+)*))?"
    r"(\+([0-9A-Za-z\-]+(\.[0-9A-Za-z\-]+)*))?"
)
LEGACY = re.compile(rf"^({W}*({OPS}){W}*({CV}){W}*)((?:{W}+|,{W}*)({OPS}){W}*({CV}){W}*)*\Z")
NEW = masterminds._VALID


def _strings(alphabet: str, max_len: int) -> itertools.chain[str]:
    return itertools.chain([""], (("".join(t)) for n in range(1, max_len + 1) for t in itertools.product(alphabet, repeat=n)))


@pytest.mark.parametrize(
    ("alphabet", "max_len"),
    [
        ("1x|.-+a=!<>~^ ,v*\n", 5),   # every token class, short
        ("1 ,=>~", 9),                # whitespace/comma/operator splitting, long
        ("1.x- \t,>|", 7),
        ("1 \t\n\f\r,", 8),           # every Go whitespace character
        ("1  \v ,=", 6),    # characters Python's \s accepts and Go's does not
    ],
)
def test_replacement_accepts_exactly_the_same_strings(alphabet: str, max_len: int) -> None:
    checked = accepted = 0
    for s in _strings(alphabet, max_len):
        want = LEGACY.match(s) is not None
        got = NEW.fullmatch(s) is not None
        assert got == want, repr(s)
        checked += 1
        accepted += want
    assert checked > 30000 and 0 < accepted < checked


def test_replacement_is_immune_to_the_input_that_stalls_the_original() -> None:
    """The Go pattern takes about ten seconds on six of these groups and doubles with each more."""
    hostile = ("1" + " " * 6) * 70 + "!"
    assert NEW.fullmatch(hostile) is None
    assert NEW.fullmatch(hostile[:-1]) is not None
