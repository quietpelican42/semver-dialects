"""Compare this package with Go on arbitrary inputs via the probe oracle."""

from __future__ import annotations

from typing import Any

from semver_dialects import hashicorp, masterminds


def mm_version(s: str) -> dict[str, Any]:
    M = masterminds
    try:
        v = M.Version.parse(s)
        got: dict[str, Any] = {"ok": True, "str": str(v), "orig": v.original, "maj": str(v.major), "min": str(v.minor),
                               "pat": str(v.patch), "pre": v.prerelease, "meta": v.metadata}
    except M.VersionError as e:
        got = {"ok": False, "err": str(e)}
    try:
        sv = M.Version.parse_strict(s)
        got.update({"sok": True, "sstr": str(sv), "sorig": sv.original})
    except M.VersionError as e:
        got.update({"sok": False, "serr": str(e)})
    return got


def hv_version(s: str) -> dict[str, Any]:
    H = hashicorp
    try:
        v = H.Version.parse(s)
        got: dict[str, Any] = {"ok": True, "str": str(v), "orig": v.original, "seg": [str(x) for x in v.segments],
                               "pre": v.prerelease, "meta": v.metadata, "core": str(v.core())}
    except H.VersionError as e:
        got = {"ok": False, "err": str(e)}
    try:
        got.update({"sok": True, "sstr": str(H.Version.parse_semver(s))})
    except H.VersionError as e:
        got.update({"sok": False, "serr": str(e)})
    return got


def mm_constraint(c: str, vs: list[str]) -> dict[str, Any]:
    M = masterminds
    try:
        cons = M.Constraints.parse(c)
    except M.ConstraintError as e:
        return {"ok": False, "err": str(e)}
    inc = M.Constraints.parse(c, include_prerelease=True)
    chk, ichk = "", ""
    val: list[str | None] = []
    ival: list[str | None] = []
    for s in vs:
        try:
            v = M.Version.parse(s)
        except M.VersionError:
            chk += "x"
            ichk += "x"
            val.append(None)
            ival.append(None)
            continue
        chk += "1" if cons.check(v) else "0"
        ichk += "1" if inc.check(v) else "0"
        ok, rs = cons.validate(v)
        val.append("" if ok else "\n".join(rs))
        ok, rs = inc.validate(v)
        ival.append("" if ok else "\n".join(rs))
    return {"ok": True, "str": str(cons), "chk": chk, "inc": ichk, "val": val, "ival": ival}


def hv_constraint(c: str, vs: list[str]) -> dict[str, Any]:
    H = hashicorp
    try:
        cons = H.Constraints.parse(c)
    except (H.ConstraintError, H.VersionError) as e:
        return {"ok": False, "err": str(e)}
    chk = ""
    for s in vs:
        try:
            v = H.Version.parse(s)
        except H.VersionError:
            chk += "x"
            continue
        chk += "1" if cons.check(v) else "0"
    return {"ok": True, "str": str(cons), "srt": str(cons.sorted()), "chk": chk}
