"""Run the Go oracle in tests/oracle. Skips loudly when Go or its modules are unavailable."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ORACLE = Path(__file__).parent / "oracle"
TIMEOUT = 600


def _run(args: list[str]) -> None:
    go = shutil.which("go")
    if go is None:
        pytest.skip("SKIPPED: `go` is not on PATH, so the live differential against the Go libraries did not run. Install Go to run it.")
    try:
        proc = subprocess.run(
            [go, "run", ".", *args], cwd=ORACLE, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        pytest.skip(f"SKIPPED: `go run` exceeded {TIMEOUT}s (module download stuck?). Live differential did not run.")
    if proc.returncode != 0:
        pytest.skip(
            "SKIPPED: the Go oracle failed to build or run (offline without a module cache?). "
            "Set GOPROXY to a reachable proxy or a populated cache. Live differential did not run.\n" + proc.stderr[-800:]
        )


def gen(out: Path, seed: int, n: int, pool: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _run(["gen", "-out", str(out), "-seed", str(seed), "-n", str(n), "-pool", str(pool)])


def probe(requests: list[dict[str, Any]], workdir: Path) -> list[dict[str, Any]]:
    workdir.mkdir(parents=True, exist_ok=True)
    req = workdir / "requests.jsonl"
    ans = workdir / "answers.jsonl"
    with req.open("w", encoding="utf-8") as fh:
        for r in requests:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    _run(["probe", "-in", str(req), "-out", str(ans)])
    with ans.open(encoding="utf-8") as fh:
        out = [json.loads(line) for line in fh]
    assert len(out) == len(requests)
    return out
