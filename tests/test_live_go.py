"""Differential tests that run the real Go libraries (tests/oracle) on fresh inputs.

These skip, loudly, when `go` or the Go modules are unavailable. Run them with
`pytest -rs` to see the skip reason.
"""

from __future__ import annotations

import itertools
import os
import random
from pathlib import Path
from typing import Any, Callable

import pytest

import corpus
import goracle
import probe_check as pc

SEEDS = [int(x) for x in os.environ.get("SEMVER_DIALECTS_SEEDS", "101,202").split(",")]
# The committed corpus used seed 20260929; these are different.


@pytest.mark.parametrize("seed", SEEDS)
def test_fresh_seed_matches_go(seed: int, tmp_path: Path) -> None:
    goracle.gen(tmp_path, seed, 20000, 600)
    for dialect in ("masterminds", "hashicorp"):
        rep = corpus.verify(dialect, corpus.load(tmp_path / f"{dialect}.jsonl.gz"))
        assert rep.failures == 0, f"seed {seed} {dialect}:\n" + "\n".join(rep.examples)
        assert rep.checks > 100000


def _compare(
    dialect: str,
    kind: str,
    inputs: list[str],
    tmp_path: Path,
    vs: list[str] | None = None,
) -> None:
    if kind == "version":
        reqs: list[dict[str, Any]] = [{"d": dialect, "k": "version", "v": s} for s in inputs]
        fn: Callable[[str], dict[str, Any]] = pc.mm_version if dialect == "masterminds" else pc.hv_version
    else:
        reqs = [{"d": dialect, "k": "constraint", "c": s, "vs": vs} for s in inputs]
        cfn = pc.mm_constraint if dialect == "masterminds" else pc.hv_constraint
        fn = lambda s: cfn(s, vs or [])  # noqa: E731
    answers = goracle.probe(reqs, tmp_path)
    bad: list[str] = []
    for s, ans in zip(inputs, answers, strict=True):
        assert "panic" not in ans, (s, ans)
        got = fn(s)
        want = {k: ans.get(k) for k in got}
        if got != want:
            bad.append(f"{s!r}\n  got  {got}\n  want {want}")
    assert not bad, f"{len(bad)} of {len(inputs)} differ; first:\n" + "\n".join(bad[:5])


def _strings(alphabet: str, max_len: int) -> list[str]:
    out = [""]
    for n in range(1, max_len + 1):
        out.extend("".join(t) for t in itertools.product(alphabet, repeat=n))
    return out


POOL = ["1.2.3", "1.2.3-alpha", "0.0.0", "2.0.0", "1.0.0-rc.1", "0.2.3", "1.2.3.4", "1.2", "3.0.0-0"]


def test_masterminds_versions_exhaustive(tmp_path: Path) -> None:
    _compare("masterminds", "version", _strings("01v.-+a_ ", 5), tmp_path)


def test_hashicorp_versions_exhaustive(tmp_path: Path) -> None:
    _compare("hashicorp", "version", _strings("01v.-+a~_ ", 5), tmp_path)


def test_masterminds_constraints_exhaustive(tmp_path: Path) -> None:
    _compare("masterminds", "constraint", _strings("1x*.-+ =<>!~^,|", 4) + _strings("1x.- =~,|", 6), tmp_path, POOL)


def test_hashicorp_constraints_exhaustive(tmp_path: Path) -> None:
    _compare("hashicorp", "constraint", _strings("1.-+ =<>!~,a", 5) + _strings("12.-,~> ", 7), tmp_path, POOL)


ODD = [
    " ", " 1.0", "1.0 ", " ", "\u0085", "﻿", "​", "\x00", "\x7f", "\x1b[0m",
    "é1", "\U0001f600", "1.0\U0001f600", '"', "\\", '1"2', "1\\2", "٣", "１.0", ">=１", "́", "퟿", "", "\U000e0001",
    "1.0\v", "\v1.0", "1.0\f", "\f>=1", "\t>=\n1.0\r", "1 1",
]


@pytest.mark.parametrize("dialect", ["masterminds", "hashicorp"])
def test_odd_characters_are_quoted_and_rejected_like_go(dialect: str, tmp_path: Path) -> None:
    inputs = ODD + [">=" + s for s in ODD] + [s + " || 1" for s in ODD]
    _compare(dialect, "constraint", inputs, tmp_path, POOL)
    _compare(dialect, "version", ODD, tmp_path / "v")


def test_limits_match_go(tmp_path: Path) -> None:
    long_ok = "1." + "0" * 250 + ".1"  # 254 bytes but not a valid strict version
    inputs = [
        "1" * 256, "1" * 257, "1.2." + "3" * 252, "1.2." + "3" * 253, "1.2.3-" + "a" * 250, "1.2.3-" + "a" * 251,
        "é" * 128, "é" * 129, long_ok, "1.2.3+" + "b" * 249, "1.2.3+" + "b" * 250,
    ]
    _compare("masterminds", "version", inputs, tmp_path / "v")
    cons = [
        ">=1.2.3 " * 64, ">=1.2.3 " * 64 + "1", "1" * 512, "1" * 513, "é" * 256, "é" * 257, "||".join(["1"] * 32),
        "||".join(["1"] * 33), "||".join(["1"] * 200), ">1 || " * 31 + ">1", ">1 || " * 32 + ">1",
    ]
    _compare("masterminds", "constraint", cons, tmp_path / "c", POOL)


def test_hashicorp_has_no_length_limit(tmp_path: Path) -> None:
    inputs = ["1" * 2000, "1." * 2000 + "1", "1.0-" + "a." * 500 + "a", "1.0+" + "b" * 3000, "9" * 19, "9" * 20, "1.0." + "9" * 19]
    _compare("hashicorp", "version", inputs, tmp_path / "v")
    _compare("hashicorp", "constraint", [">= " + s for s in inputs] + [",".join(["~> 1.0"] * 500)], tmp_path / "c", POOL)


def test_out_of_range_segments(tmp_path: Path) -> None:
    big = ["18446744073709551615", "18446744073709551616", "9223372036854775807", "9223372036854775808", "99999999999999999999999", "0" * 30 + "5"]
    inputs = [f"{a}.{b}.0" for a in big for b in big[:3]] + [f"1.2.3-{b}" for b in big] + [f"1.2.3-a.{b}" for b in big]
    _compare("masterminds", "version", inputs, tmp_path / "m")
    _compare("hashicorp", "version", inputs + [f"1.2.3-{b}.-{b}" for b in big], tmp_path / "h")
    _compare("masterminds", "constraint", [f">={b}" for b in big] + [f"~{b}.x" for b in big], tmp_path / "mc", POOL)
    _compare("hashicorp", "constraint", [f"~> {b}" for b in big] + [f"= 1.0.{b}" for b in big], tmp_path / "hc", POOL)


def _sort_requests(dialect: str, pool: list[str], rng: random.Random, sizes: list[int]) -> list[dict[str, Any]]:
    return [
        {"d": dialect, "k": "sort", "pool": pool, "in": [rng.randrange(len(pool)) for _ in range(n)]}
        for n in sizes
        for _ in range(40)
    ]


def _check_sorts(dialect: str, pool: list[str], tmp_path: Path) -> None:
    from semver_dialects import hashicorp, masterminds
    from semver_dialects._go import stable_sort

    mod: Any = masterminds if dialect == "masterminds" else hashicorp
    vers = [mod.Version.parse(s) for s in pool]
    reqs = _sort_requests(dialect, pool, random.Random(7), [2, 5, 19, 20, 21, 22, 40, 41, 63, 64, 100, 257])
    answers = goracle.probe(reqs, tmp_path)
    for r, a in zip(reqs, answers, strict=True):
        got = stable_sort(r["in"], lambda x, y: bool(vers[x].compare(vers[y]) < 0))
        assert got == a["out"], (dialect, len(r["in"]), r["in"], got, a["out"])
        api = mod.sort_versions([vers[i] for i in r["in"]])
        assert [str(v) for v in api] == [str(vers[i]) for i in a["out"]]


def test_masterminds_sort_beyond_twenty_elements(tmp_path: Path) -> None:
    pool = ["1.0.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-beta", "1.0.0-1", "1.0.0-2", "1.0.1", "2.0.0", "0.9.0", "1.0.0-rc.1",
            "1.0.0+b", "1.0.0-x-y", "1.0.0-99999999999999999999", "1.0.0-A", "1.10.0", "1.2.0"]
    _check_sorts("masterminds", pool, tmp_path)


def test_hashicorp_sort_beyond_twenty_elements_with_inconsistent_comparator(tmp_path: Path) -> None:
    # Prerelease parts "1" and "01" compare as less-than in both directions.
    pool = ["1.0.0", "1.0.0-1", "1.0.0-01", "1.0.0-001", "1.0.0-a", "1.0.0-A", "1.0.0-alpha.1", "1.0.0-alpha.01", "1.0.0.0", "1.0.0.0-1",
            "1.0.0-99999999999999999999", "1.0.0--5", "1.0.0-b", "1.0.0-~", "2.0", "1.0", "1.0.1", "1.0.0.1", "0.9", "1.0.0-z.1"]
    _check_sorts("hashicorp", pool, tmp_path)


def test_hashicorp_constraint_sort_beyond_twenty_elements(tmp_path: Path) -> None:
    from semver_dialects import hashicorp

    rng = random.Random(3)
    ops = ["", "=", "!=", ">", ">=", "<", "<=", "~>"]
    vers = ["1.0", "1.0.0-01", "1.0.0-1", "1.0.0-a", "2", "1.0.0.0", "1.2.3", "0.1", "1.0.0-001"]
    cons = [",".join(rng.choice(ops) + " " + rng.choice(vers) for _ in range(n)) for n in (2, 6, 20, 21, 30, 45, 64, 90) for _ in range(30)]
    answers = goracle.probe([{"d": "hashicorp", "k": "constraint", "c": c, "vs": []} for c in cons], tmp_path)
    for c, a in zip(cons, answers, strict=True):
        assert str(hashicorp.Constraints.parse(c).sorted()) == a["srt"], c


def test_readme_and_api_examples_match_go(tmp_path: Path) -> None:
    import test_api as api

    _compare("masterminds", "constraint", api.MM_EXAMPLES + [">=1.0 é\n", "1" * 513, "||".join(["1"] * 33)], tmp_path / "mc", api.MM_VERSIONS)
    _compare("hashicorp", "constraint", api.HV_EXAMPLES + [">> 1", ">= 1.0,~> 2.0,!= 3.0,< 4.0,= 5.0,<= 6.0,> 7.0"], tmp_path / "hc", api.HV_VERSIONS)
    _compare("masterminds", "version", api.MM_VERSIONS + ["v1.2-beta.1+build.5", "1.2.3.4", "1.2.3-01", "01.2.3", "1.2"], tmp_path / "mv")
    _compare("hashicorp", "version", api.HV_VERSIONS + ["v1.2.3.4-beta+meta", "1.04.0", "1.0.x", "9223372036854775808", "1.0.0-01"], tmp_path / "hv")
