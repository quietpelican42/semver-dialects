"""Score Python version libraries, and this package, on the committed Go corpus.

    pip install -e '.[bench]' && python bench/incumbents.py

For each dialect the corpus holds 600 versions and 20000 constraints with the
answers Go's library gave. Three numbers per library:

  version-parse      share of the 600 versions accepted or rejected as Go does
  constraint-parse   share of the 20000 constraints accepted or rejected as Go does
  constraint-full    share where the accept/reject decision matches and every recorded
                     Check result (8 versions each) matches

A library that cannot parse a version Go accepted counts as a mismatch for every
check that used it. Each library call is limited to 2 seconds.
"""

from __future__ import annotations

import gzip
import json
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "tests" / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

Adapter = tuple[Callable[[str], Any], Callable[[str], Any] | None, Callable[[Any, Any], Any] | None]


def load(name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with gzip.open(DATA / f"{name}.jsonl.gz", "rt", encoding="utf-8") as fh:
        recs = [json.loads(line) for line in fh]
    return [r for r in recs if r["t"] == "version"], [r for r in recs if r["t"] == "constraint"]


class Timeout(Exception):
    pass


def _alarm(*_: Any) -> None:
    raise Timeout()


def guarded(fn: Callable[..., Any], *args: Any) -> tuple[bool, Any]:
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    try:
        return True, fn(*args)
    except BaseException:
        return False, None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def adapters(dialect: str) -> dict[str, tuple[str, Adapter]]:
    out: dict[str, tuple[str, Adapter]] = {}
    from semver_dialects import hashicorp, masterminds

    if dialect == "masterminds":
        m = masterminds
        out["semver-dialects (this package)"] = (
            "",
            (m.Version.parse, m.Constraints.parse, lambda c, v: c.check(v)),
        )
    else:
        h = hashicorp
        out["semver-dialects (this package)"] = (
            "",
            (h.Version.parse, h.Constraints.parse, lambda c, v: c.check(v)),
        )
    try:
        import semantic_version as sv

        out["semantic_version.NpmSpec"] = (sv.__version__, (sv.Version, sv.NpmSpec, lambda s, v: s.match(v)))
        out["semantic_version.SimpleSpec"] = (sv.__version__, (sv.Version, sv.SimpleSpec, lambda s, v: s.match(v)))
    except ImportError:
        print("skipped: semantic_version not installed (pip install -e '.[bench]')")
    try:
        import nodesemver

        out["node-semver"] = (
            "",
            (lambda v: nodesemver.SemVer(v, False, False), lambda c: nodesemver.Range(c, False), lambda s, v: s.test(v)),
        )
    except ImportError:
        print("skipped: node-semver not installed")
    try:
        from poetry.core.constraints.version import Version as PoetryVersion
        from poetry.core.constraints.version import parse_constraint

        out["poetry-core"] = ("", (PoetryVersion.parse, parse_constraint, lambda s, v: s.allows(v)))
    except ImportError:
        print("skipped: poetry-core not installed")
    try:
        import semver

        out["semver (python-semver, versions only)"] = ("", (semver.Version.parse, None, None))
    except ImportError:
        print("skipped: semver not installed")
    return out


def score(dialect: str) -> None:
    pool, cons = load(dialect)
    print(f"{dialect}: {len(pool)} versions, {len(cons)} constraints, {sum(c['ok'] for c in cons)} constraints valid in Go")
    for name, (_, (parse_v, parse_c, check)) in adapters(dialect).items():
        parsed: list[Any] = []
        vok = 0
        for r in pool:
            ok, v = guarded(parse_v, r["v"])
            parsed.append(v if ok else None)
            vok += ok == r["ok"]
        line = f"  {name:<40} version-parse {100 * vok / len(pool):5.1f}%"
        if parse_c is not None and check is not None:
            pok = full = 0
            for r in cons:
                ok, spec = guarded(parse_c, r["c"])
                if ok != r["ok"]:
                    continue
                pok += 1
                if not r["ok"]:
                    full += 1
                    continue
                good = True
                for vi, ch in zip(r["vi"], r["chk"], strict=True):
                    if ch == "x":
                        continue
                    if parsed[vi] is None:
                        good = False
                        break
                    ok2, res = guarded(check, spec, parsed[vi])
                    if not ok2 or bool(res) != (ch == "1"):
                        good = False
                        break
                full += good
            line += f"  constraint-parse {100 * pok / len(cons):5.1f}%  constraint-full {100 * full / len(cons):5.1f}%"
        print(line, flush=True)


if __name__ == "__main__":
    for d in ("masterminds", "hashicorp"):
        score(d)
    import importlib.metadata as md

    found = []
    for pkg in ("poetry-core", "semantic-version", "node-semver", "semver"):
        try:
            found.append(f"{pkg} {md.version(pkg)}")
        except md.PackageNotFoundError:
            pass
    print("installed:", ", ".join(found))
