"""The committed corpus: outputs recorded from the Go libraries (see data/README.txt)."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

import corpus

DATA = Path(__file__).parent / "data"
DIALECTS = ["masterminds", "hashicorp"]


def test_corpus_files_match_recorded_checksums() -> None:
    for line in (DATA / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_recorded_answer_is_reproduced(dialect: str) -> None:
    records = corpus.load(DATA / f"{dialect}.jsonl.gz")
    rep = corpus.verify(dialect, records)
    assert rep.failures == 0, "\n".join(rep.examples)
    # The corpus must actually exercise each category, or a green run means little.
    kinds = {r["t"] for r in records}
    assert kinds == {"meta", "version", "constraint", "cmp", "sort"}
    assert rep.total["version.parse"] == 600
    assert rep.total["constraint.parse"] == 20000
    assert rep.total["sort"] == 3000
    assert rep.total["check"] > 60000
    assert rep.failed == {}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_corpus_has_both_outcomes(dialect: str) -> None:
    """Negative control: Go accepted and rejected inputs, and checks came out both ways."""
    records = corpus.load(DATA / f"{dialect}.jsonl.gz")
    cons = [r for r in records if r["t"] == "constraint"]
    assert 0.3 < sum(r["ok"] for r in cons) / len(cons) < 0.95
    chk = "".join(r["chk"] for r in cons if r["ok"])
    assert "1" in chk and "0" in chk and "x" in chk


@pytest.mark.parametrize("dialect", DIALECTS)
def test_checker_detects_a_wrong_answer(dialect: str, tmp_path: Path) -> None:
    """Negative control for the checker: flipping recorded answers must be reported."""
    records = corpus.load(DATA / f"{dialect}.jsonl.gz")
    flip = {"0": "1", "1": "0", "x": "x"}
    changed = 0
    for r in records:
        if r["t"] == "constraint" and r["ok"] and changed < 50:
            r["chk"] = "".join(flip[c] for c in r["chk"])
            changed += 1
        if r["t"] == "cmp":
            r["r"] = -r["r"] if r["r"] else 1
    rep = corpus.verify(dialect, records)
    assert rep.failed.get("check", 0) > 0
    assert rep.failed.get("compare", 0) > 0


def test_corpus_is_valid_gzip_jsonl() -> None:
    for dialect in DIALECTS:
        with gzip.open(DATA / f"{dialect}.jsonl.gz", "rt", encoding="utf-8") as fh:
            first = json.loads(fh.readline())
        assert first["t"] == "meta" and first["dialect"] == dialect
