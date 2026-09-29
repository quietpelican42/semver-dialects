"""Replay a differential corpus (see data/README.txt) against this package.

The same code checks the committed corpus and freshly generated Go output.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from semver_dialects import hashicorp, masterminds
from semver_dialects._go import stable_sort

Record = dict[str, Any]


def load(path: Path) -> list[Record]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


class Report:
    """Counts checks per category and keeps the first few failures of each."""

    def __init__(self) -> None:
        self.total: dict[str, int] = {}
        self.failed: dict[str, int] = {}
        self.examples: list[str] = []

    def ok(self, kind: str, cond: bool, detail: Callable[[], str]) -> None:
        self.total[kind] = self.total.get(kind, 0) + 1
        if not cond:
            self.failed[kind] = self.failed.get(kind, 0) + 1
            if len(self.examples) < 25:
                self.examples.append(f"{kind}: {detail()}")

    @property
    def checks(self) -> int:
        return sum(self.total.values())

    @property
    def failures(self) -> int:
        return sum(self.failed.values())


def _chk(fn: Callable[[], bool]) -> str:
    return "1" if fn() else "0"


def verify(dialect: str, records: list[Record]) -> Report:
    rep = Report()
    if dialect == "masterminds":
        _masterminds(records, rep)
    else:
        _hashicorp(records, rep)
    return rep


def _masterminds(records: list[Record], rep: Report) -> None:
    M = masterminds
    pool: list[M.Version | None] = []
    for r in records:
        t = r["t"]
        if t == "version":
            assert "panic" not in r, r
            s = r["v"]
            v: M.Version | None
            try:
                v = M.Version.parse(s)
                got: Record = {
                    "ok": True, "str": str(v), "orig": v.original, "maj": str(v.major), "min": str(v.minor),
                    "pat": str(v.patch), "pre": v.prerelease, "meta": v.metadata,
                }
            except M.VersionError as e:
                v = None
                got = {"ok": False, "err": str(e)}
            pool.append(v)
            want = {k: r[k] for k in got}
            rep.ok("version.parse", got == want, lambda: f"{s!r} got {got} want {want}")
            try:
                sv = M.Version.parse_strict(s)
                sgot: Record = {"sok": True, "sstr": str(sv), "sorig": sv.original}
            except M.VersionError as e:
                sgot = {"sok": False, "serr": str(e)}
            swant = {k: r[k] for k in sgot}
            rep.ok("version.strict", sgot == swant, lambda: f"{s!r} got {sgot} want {swant}")
        elif t == "constraint":
            assert "panic" not in r, r
            c = r["c"]
            try:
                cons = M.Constraints.parse(c)
            except M.ConstraintError as e:
                rep.ok("constraint.parse", (not r["ok"]) and str(e) == r["err"], lambda: f"{c!r} got error {e} want {r}")
                continue
            rep.ok("constraint.parse", r["ok"], lambda: f"{c!r} accepted, Go rejected: {r.get('err')}")
            if not r["ok"]:
                continue
            rep.ok("constraint.string", str(cons) == r["str"], lambda: f"{c!r} got {str(cons)!r} want {r['str']!r}")
            inc = M.Constraints.parse(c, include_prerelease=True)
            for j, vi in enumerate(r["vi"]):
                v = pool[vi]
                if v is None:
                    rep.ok("constraint.pool", r["chk"][j] == "x" and r["val"][j] is None, lambda: f"{c!r} {vi}")
                    continue
                vs = v
                rep.ok("check", _chk(lambda: cons.check(vs)) == r["chk"][j], lambda: f"{c!r} vs {vs.original!r} want {r['chk'][j]}")
                rep.ok("check.include", _chk(lambda: inc.check(vs)) == r["inc"][j], lambda: f"{c!r} vs {vs.original!r} want {r['inc'][j]}")
                for label, engine, key in (("validate", cons, "val"), ("validate.include", inc, "ival")):
                    ok, reasons = engine.validate(vs)
                    got_v = "" if ok else "\n".join(reasons)
                    rep.ok(label, got_v == r[key][j], lambda: f"{c!r} vs {vs.original!r} got {got_v!r} want {r[key][j]!r}")
                    rep.ok(label + ".agrees", ok == engine.check(vs), lambda: f"{c!r} vs {vs.original!r}")
        elif t == "cmp":
            a, b = pool[r["a"]], pool[r["b"]]
            assert a is not None and b is not None
            rep.ok("compare", a.compare(b) == r["r"] and a.equal(b) == r["eq"], lambda: f"{a} {b} want {r}")
        elif t == "sort":
            idx = stable_sort(r["in"], lambda x, y: _v(pool, x).compare(_v(pool, y)) < 0)
            rep.ok("sort", idx == r["out"], lambda: f"in {r['in']} got {idx} want {r['out']}")
            vs2 = M.sort_versions([_v(pool, i) for i in r["in"]])
            rep.ok("sort.api", [str(x) for x in vs2] == [str(pool[i]) for i in r["out"]], lambda: f"in {r['in']}")


def _v(pool: list[Any], i: int) -> Any:
    v = pool[i]
    assert v is not None
    return v


def _hashicorp(records: list[Record], rep: Report) -> None:
    H = hashicorp
    pool: list[H.Version | None] = []
    for r in records:
        t = r["t"]
        if t == "version":
            assert "panic" not in r, r
            s = r["v"]
            v: H.Version | None
            try:
                v = H.Version.parse(s)
                got: Record = {
                    "ok": True, "str": str(v), "orig": v.original, "seg": [str(x) for x in v.segments],
                    "pre": v.prerelease, "meta": v.metadata, "core": str(v.core()),
                }
            except H.VersionError as e:
                v = None
                got = {"ok": False, "err": str(e)}
            pool.append(v)
            want = {k: r[k] for k in got}
            rep.ok("version.parse", got == want, lambda: f"{s!r} got {got} want {want}")
            try:
                sgot: Record = {"sok": True, "sstr": str(H.Version.parse_semver(s))}
            except H.VersionError as e:
                sgot = {"sok": False, "serr": str(e)}
            swant = {k: r[k] for k in sgot}
            rep.ok("version.semver", sgot == swant, lambda: f"{s!r} got {sgot} want {swant}")
        elif t == "constraint":
            assert "panic" not in r, r
            c = r["c"]
            try:
                cons = H.Constraints.parse(c)
            except (H.ConstraintError, H.VersionError) as e:
                rep.ok("constraint.parse", (not r["ok"]) and str(e) == r["err"], lambda: f"{c!r} got error {e} want {r}")
                continue
            rep.ok("constraint.parse", r["ok"], lambda: f"{c!r} accepted, Go rejected: {r.get('err')}")
            if not r["ok"]:
                continue
            rep.ok("constraint.string", str(cons) == r["str"], lambda: f"{c!r} got {str(cons)!r} want {r['str']!r}")
            rep.ok("constraint.sort", str(cons.sorted()) == r["srt"], lambda: f"{c!r} got {str(cons.sorted())!r} want {r['srt']!r}")
            for j, vi in enumerate(r["vi"]):
                v = pool[vi]
                if v is None:
                    rep.ok("constraint.pool", r["chk"][j] == "x", lambda: f"{c!r} {vi}")
                    continue
                vs = v
                rep.ok("check", _chk(lambda: cons.check(vs)) == r["chk"][j], lambda: f"{c!r} vs {vs.original!r} want {r['chk'][j]}")
        elif t == "cmp":
            a, b = pool[r["a"]], pool[r["b"]]
            assert a is not None and b is not None
            rep.ok("compare", a.compare(b) == r["r"] and a.equal(b) == r["eq"], lambda: f"{a} {b} want {r}")
        elif t == "sort":
            idx = stable_sort(r["in"], lambda x, y: _v(pool, x).compare(_v(pool, y)) < 0)
            rep.ok("sort", idx == r["out"], lambda: f"in {r['in']} got {idx} want {r['out']}")
            vs2 = H.sort_versions([_v(pool, i) for i in r["in"]])
            rep.ok("sort.api", [str(x) for x in vs2] == [str(pool[i]) for i in r["out"]], lambda: f"in {r['in']}")
