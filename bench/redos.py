"""Time Masterminds' original validation pattern against this package's replacement.

    python bench/redos.py

The input is n runs of "1" followed by six spaces, then "!". The original pattern
is run in a child process with a 20 second limit.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from semver_dialects import masterminds  # noqa: E402

LEGACY = r'''
import re, sys, time
W = r"[\t\n\f\r ]"
OPS = r"=||!=|>|<|>=|=>|<=|=<|~|~>|\^"
CV = (r"v?([0-9|xX*]+)(\.[0-9|xX*]+)?(\.[0-9|xX*]+)?(-([0-9A-Za-z\-]+(\.[0-9A-Za-z\-]+)*))?"
      r"(\+([0-9A-Za-z\-]+(\.[0-9A-Za-z\-]+)*))?")
L = re.compile(rf"^({W}*({OPS}){W}*({CV}){W}*)((?:{W}+|,{W}*)({OPS}){W}*({CV}){W}*)*\Z")
s = ("1" + " " * 6) * int(sys.argv[1]) + "!"
t = time.perf_counter(); L.match(s); print(time.perf_counter() - t)
'''


def main() -> None:
    print(f"{'runs':>5} {'bytes':>6}  {'original pattern':>18}  {'replacement':>12}")
    for n in (3, 4, 5, 6, 7, 70):
        s = ("1" + " " * 6) * n + "!"
        t = time.perf_counter()
        try:
            masterminds.Constraints.parse(s)
        except masterminds.ConstraintError:
            pass
        ours = f"{time.perf_counter() - t:.6f}s"
        if n > 7:
            theirs = "not run (>20s)"
        else:
            try:
                r = subprocess.run([sys.executable, "-c", LEGACY, str(n)], capture_output=True, text=True, timeout=20, check=True)
                theirs = f"{float(r.stdout):.3f}s"
            except subprocess.TimeoutExpired:
                theirs = ">20s (killed)"
        print(f"{n:>5} {len(s):>6}  {theirs:>18}  {ours:>12}")


if __name__ == "__main__":
    main()
