"""Hostile inputs must finish quickly. Each case runs in its own process with a hard timeout."""

from __future__ import annotations

import subprocess
import sys

import pytest

TIMEOUT = 20

RUNNER = """
import sys
from semver_dialects import {mod}
s = eval(sys.argv[1])
try:
    {mod}.{call}
except ({mod}.VersionError, {mod}.ConstraintError, ValueError):
    pass
"""


def run(mod: str, call: str, expr: str) -> None:
    code = RUNNER.format(mod=mod, call=call)
    try:
        subprocess.run([sys.executable, "-c", code, expr], check=True, timeout=TIMEOUT, capture_output=True)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{mod}.{call} on {expr[:80]} exceeded {TIMEOUT}s")
    except subprocess.CalledProcessError as e:
        pytest.fail(e.stderr.decode()[-500:])


# Each family stays inside masterminds' 512-byte constraint limit.
MASTERMINDS_CONSTRAINTS = {
    "seven-space runs then junk": '("1" + " " * 6) * 73 + "!"',
    "seven-space runs, valid": '("1" + " " * 6) * 73',
    "single-space runs": '"1 " * 250 + "!"',
    "comma runs": '"1 , " * 120 + "!"',
    "whitespace only": '" " * 500 + "!"',
    "operator after operator": '"> " * 250 + "1!"',
    "range chain": '"1 - " * 120 + "!"',
    "range chain with versions": '"1 - 2 " * 80 + "!"',
    "hyphen chain": '"1" + "-1" * 250 + "!"',
    "pipes": '"1|" * 250 + "!"',
    "wildcards": '"x" * 500 + "!"',
    "or groups with padding": '"||".join([" " * 12 + "1" + " " * 10] * 20) + "!"',
    "tabs and operators": '"~> \\t" * 120 + "1!"',
}


@pytest.mark.parametrize("name", MASTERMINDS_CONSTRAINTS)
def test_masterminds_constraints(name: str) -> None:
    run("masterminds", "Constraints.parse(s)", MASTERMINDS_CONSTRAINTS[name])


def test_masterminds_constraint_length_cap_applies_before_any_regex() -> None:
    run("masterminds", "Constraints.parse(s)", '("1" + " " * 6) * 5000 + "!"')


HASHICORP_VERSIONS = {
    "200k digits": '"1" * 200000 + "x"',
    "dotted core": '"1" + ".1" * 100000 + "x"',
    "dotted prerelease": '"1.0-" + "a." * 100000 + "!"',
    "hyphen run": '"1.0-" + "-" * 200000 + "!"',
    "tilde run": '"1.0" + "~a" * 100000 + "+"',
    "metadata": '"1.0+" + "a.b" * 100000 + "!"',
}


@pytest.mark.parametrize("name", HASHICORP_VERSIONS)
def test_hashicorp_versions(name: str) -> None:
    run("hashicorp", "Version.parse(s)", HASHICORP_VERSIONS[name])


HASHICORP_CONSTRAINTS = {
    "many commas": '",".join(["~> 1.0"] * 50000) + ",!"',
    "whitespace both sides": '" " * 200000 + "1" + " " * 200000 + "!"',
    "whitespace after operator": '"> " + " " * 200000 + "1 x"',
}


@pytest.mark.parametrize("name", HASHICORP_CONSTRAINTS)
def test_hashicorp_constraints(name: str) -> None:
    run("hashicorp", "Constraints.parse(s)", HASHICORP_CONSTRAINTS[name])


def test_int_digit_limit_does_not_leak() -> None:
    """Python refuses int() on more than 4300 digits by default; Go reports a range error."""
    from semver_dialects import hashicorp, masterminds

    huge = "9" * 5000
    with pytest.raises(hashicorp.VersionError, match="value out of range"):
        hashicorp.Version.parse(huge)
    with pytest.raises(masterminds.VersionError, match="too long"):
        masterminds.Version.parse(huge)
    with pytest.raises(masterminds.VersionError, match="value out of range"):
        masterminds.Version.parse("9" * 200)



def test_harness_detects_a_hang() -> None:
    """Negative control: Go's original validation pattern stalls the same harness."""
    code = (
        "import re\n"
        'W=r"[\\t\\n\\f\\r ]";OPS=r"=||!=|>|<|>=|=>|<=|=<|~|~>|\\^"\n'
        'CV=r"v?([0-9|xX*]+)(\\.[0-9|xX*]+)?(\\.[0-9|xX*]+)?(-([0-9A-Za-z\\-]+(\\.[0-9A-Za-z\\-]+)*))?(\\+([0-9A-Za-z\\-]+(\\.[0-9A-Za-z\\-]+)*))?"\n'
        'L=re.compile(rf"^({W}*({OPS}){W}*({CV}){W}*)((?:{W}+|,{W}*)({OPS}){W}*({CV}){W}*)*\\Z")\n'
        'L.match(("1"+" "*6)*9+"!")\n'
    )
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([sys.executable, "-c", code], timeout=3, capture_output=True)
