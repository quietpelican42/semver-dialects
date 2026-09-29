"""Small pieces of Go behavior that both dialects depend on."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

#: Go's regexp `\s` is exactly this set. Python's is much wider.
WS = "\t\n\f\r "
DIGITS = "0123456789"
#: Character class body shared by prerelease and metadata identifiers.
ALNUM_HYPHEN = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-"


class VersionError(ValueError):
    """A version string was rejected. The message is Go's error text."""


class ConstraintError(ValueError):
    """A constraint string was rejected. The message is Go's error text."""


def utf8_len(s: str) -> int:
    """Length in UTF-8 bytes, the unit Go's len() reports."""
    return len(s.encode("utf-8", "surrogatepass"))


def _is_print(ch: str) -> bool:
    if ch == " ":
        return True
    return unicodedata.category(ch)[0] in "LMNPS"


_SIMPLE = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}


def quote(s: str) -> str:
    """strconv.Quote, the formatting behind Go's %q verb."""
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if ch == '"' or ch == "\\":
            out.append("\\" + ch)
        elif 0xD800 <= cp <= 0xDFFF:
            # A lone surrogate is invalid UTF-8 in Go; each byte is escaped.
            out.extend("\\x%02x" % b for b in ch.encode("utf-8", "surrogatepass"))
        elif _is_print(ch):
            out.append(ch)
        elif ch in _SIMPLE:
            out.append(_SIMPLE[ch])
        elif cp < 0x20 or cp == 0x7F:
            out.append("\\x%02x" % cp)
        elif cp < 0x10000:
            out.append("\\u%04x" % cp)
        else:
            out.append("\\U%08x" % cp)
    out.append('"')
    return "".join(out)


def only(s: str, allowed: str) -> bool:
    """True when every character of s is in allowed (true for the empty string)."""
    return all(c in allowed for c in s)


def parse_uint64(s: str) -> int:
    """strconv.ParseUint(s, 10, 64). Raises ValueError carrying Go's text."""
    if s == "" or not only(s, DIGITS):
        raise ValueError(f"strconv.ParseUint: parsing {quote(s)}: invalid syntax")
    # Long inputs are refused before int() sees them: int() rejects strings over
    # 4300 digits by default, and any run of 21 or more significant digits is out of range anyway.
    digits = s.lstrip("0")
    if len(digits) > 20 or (digits and int(digits) > 0xFFFFFFFFFFFFFFFF):
        raise ValueError(f"strconv.ParseUint: parsing {quote(s)}: value out of range")
    return int(digits) if digits else 0


_I64_MAX = (1 << 63) - 1
_I64_MIN = -(1 << 63)


def parse_int64(s: str) -> tuple[int, str | None]:
    """strconv.ParseInt(s, 10, 64) as (value, error text or None).

    Go returns 0 on a syntax error and the clamped limit on a range error, and
    hashicorp/go-version's prerelease comparison reads that value even when the
    error is set, so it is preserved here.
    """
    body = s[1:] if s[:1] in ("+", "-") else s
    if body == "" or not only(body, DIGITS):
        return 0, f"strconv.ParseInt: parsing {quote(s)}: invalid syntax"
    digits = body.lstrip("0")
    negative = s[:1] == "-"
    n = int(digits) if 0 < len(digits) <= 20 else (0 if not digits else 1 << 70)
    if negative:
        n = -n
    if n > _I64_MAX:
        return _I64_MAX, f"strconv.ParseInt: parsing {quote(s)}: value out of range"
    if n < _I64_MIN:
        return _I64_MIN, f"strconv.ParseInt: parsing {quote(s)}: value out of range"
    return n, None


# ---------------------------------------------------------------------------
# sort.Stable
#
# Go's sort.Stable is insertion sort in blocks of 20 followed by SymMerge. With
# a comparator that is not a strict weak order (hashicorp/go-version's is not
# always antisymmetric) the result depends on the exact algorithm, so the same
# sequence of Less/Swap calls is reproduced here.
# ---------------------------------------------------------------------------


def stable_sort(items: Sequence[T], less: Callable[[T, T], bool]) -> list[T]:
    """Return a copy of items ordered as Go's sort.Stable would order them."""
    data = list(items)
    n = len(data)

    def lt(i: int, j: int) -> bool:
        return less(data[i], data[j])

    def swap(i: int, j: int) -> None:
        data[i], data[j] = data[j], data[i]

    def insertion(a: int, b: int) -> None:
        for i in range(a + 1, b):
            j = i
            while j > a and lt(j, j - 1):
                swap(j, j - 1)
                j -= 1

    def swap_range(a: int, b: int, cnt: int) -> None:
        for i in range(cnt):
            swap(a + i, b + i)

    def rotate(a: int, m: int, b: int) -> None:
        i = m - a
        j = b - m
        while i != j:
            if i > j:
                swap_range(m - i, m, j)
                i -= j
            else:
                swap_range(m - i, m + j - i, i)
                j -= i
        swap_range(m - i, m, i)

    def sym_merge(a: int, m: int, b: int) -> None:
        if m - a == 1:
            i, j = m, b
            while i < j:
                h = (i + j) >> 1
                if lt(h, a):
                    i = h + 1
                else:
                    j = h
            for k in range(a, i - 1):
                swap(k, k + 1)
            return
        if b - m == 1:
            i, j = a, m
            while i < j:
                h = (i + j) >> 1
                if not lt(m, h):
                    i = h + 1
                else:
                    j = h
            for k in range(m, i, -1):
                swap(k, k - 1)
            return
        mid = (a + b) >> 1
        total = mid + m
        if m > mid:
            start, r = total - b, mid
        else:
            start, r = a, m
        p = total - 1
        while start < r:
            c = (start + r) >> 1
            if not lt(p - c, c):
                start = c + 1
            else:
                r = c
        end = total - start
        if start < m < end:
            rotate(start, m, end)
        if a < start < mid:
            sym_merge(a, start, mid)
        if mid < end < b:
            sym_merge(mid, end, b)

    block = 20
    a, b = 0, block
    while b <= n:
        insertion(a, b)
        a = b
        b += block
    insertion(a, n)
    while block < n:
        a, b = 0, 2 * block
        while b <= n:
            sym_merge(a, a + block, b)
            a = b
            b += 2 * block
        m = a + block
        if m < n:
            sym_merge(a, m, n)
        block *= 2
    return data
