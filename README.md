# semver-dialects

Version parsing and constraint checking for Python that behaves like Go's Masterminds/semver v3 (Helm) and hashicorp/go-version (Terraform, Packer, Nomad), verified against both libraries.

```python
from semver_dialects import hashicorp, masterminds

c = masterminds.Constraints.parse("^1.2.3 || >=3.0.0-beta.1 <3.1.0")    # Helm chart style
c.check(masterminds.Version.parse("1.9.0"))                              # True
c.validate(masterminds.Version.parse("0.9.0"))                           # (False, ['"0.9.0" is less than "1.2.3"', '"0.9.0" is less than "3.0.0-beta.1"'])

t = hashicorp.Constraints.parse("~> 1.2")                                # Terraform required_version style
t.check(hashicorp.Version.parse("1.9.0"))                                # True
hashicorp.Constraints.parse("~> 1.2.0").check(hashicorp.Version.parse("1.3.0"))  # False
```

## Why

Helm and many Go tools use Masterminds/semver constraints. Terraform, Packer and Nomad use hashicorp/go-version constraints. Both differ from PEP 440 and from npm ranges. Masterminds accepts `1.2.x`, hyphen ranges, `||`, `~>` and `=<`, and hides prereleases unless the constraint names one. go-version accepts four or more segments, prereleases without a hyphen (`1.0beta`), and `~>` with segment-count semantics, and its prerelease rules differ from Masterminds'. A Python tool that reads a `Chart.yaml` or a `required_version` either rejects these strings or converts them to another dialect and loses the differences.

Measured: `pip install -e '.[bench]' && python bench/incumbents.py`

```
masterminds: 600 versions, 20000 constraints, 14268 constraints valid in Go
  semver-dialects (this package)           version-parse 100.0%  constraint-parse 100.0%  constraint-full 100.0%
  semantic_version.NpmSpec                 version-parse  75.8%  constraint-parse  42.8%  constraint-full  29.5%
  semantic_version.SimpleSpec              version-parse  75.8%  constraint-parse  36.6%  constraint-full  28.5%
  node-semver                              version-parse  81.7%  constraint-parse  61.2%  constraint-full  35.1%
  poetry-core                              version-parse  85.0%  constraint-parse  48.8%  constraint-full  31.9%
  semver (python-semver, versions only)    version-parse  76.0%
hashicorp: 600 versions, 20000 constraints, 16934 constraints valid in Go
  semver-dialects (this package)           version-parse 100.0%  constraint-parse 100.0%  constraint-full 100.0%
  semantic_version.NpmSpec                 version-parse  45.2%  constraint-parse  21.1%  constraint-full  14.3%
  semantic_version.SimpleSpec              version-parse  45.2%  constraint-parse  21.4%  constraint-full  15.2%
  node-semver                              version-parse  47.3%  constraint-parse  32.8%  constraint-full  13.9%
  poetry-core                              version-parse  86.7%  constraint-parse  53.7%  constraint-full  27.7%
  semver (python-semver, versions only)    version-parse  45.2%
installed: poetry-core 2.5.0, semantic-version 2.10.0, node-semver 0.9.1, semver 3.1.0
```

Constraint-full means the constraint is accepted or rejected as Go does and every recorded `Check` result matches. The corpus is deliberately edge-heavy (mutated strings, oversized numbers, odd whitespace), so the percentages describe that corpus, not real manifests. `packaging` was not measured: it implements PEP 440, not semver. Searching the PyPI simple index (901,816 projects, 2026-09-29) for names starting with `masterminds`, `hashicorp`, `go-version`, `terraform-version` and `helm-semver` found `hashicorp-vault-client-api` and `hashicorp-vault-django` (Vault clients) and `terraform-version` (its PyPI summary: "Package for tracking existing Terraform versions"). None of them implements either dialect's constraints.

## Installation

Not yet on PyPI. From a checkout:

```sh
pip install .
```

Python 3.11 or later. No runtime dependencies.

## Usage

### Masterminds (Helm)

```python
from semver_dialects.masterminds import Constraints, Version, sort_versions

Version.parse("v1.2-beta.1+build.5")        # Version(major=1, minor=2, patch=0, prerelease='beta.1', ...)
str(Version.parse("v1.2"))                   # '1.2.0'
Version.parse_strict("1.2")                  # raises VersionError: invalid semantic version

Constraints.parse(">=1.2.0").check(Version.parse("1.3.0-beta"))                           # False
Constraints.parse(">=1.2.0", include_prerelease=True).check(Version.parse("1.3.0-beta"))  # True
str(Constraints.parse("1.2.3 - 2.3.4"))      # '>=1.2.3 <=2.3.4'
```

A prerelease version only satisfies a constraint group that itself names a prerelease, unless `include_prerelease` is set. `validate` returns Go's reasons in Go's order.

### go-version (Terraform)

```python
from semver_dialects.hashicorp import Constraints, Version, sort_versions

Version.parse("v1.2.3.4-beta+meta").segments      # (1, 2, 3, 4)
Version.parse("1.0beta").prerelease                # 'beta'  (the hyphen is optional)
str(Version.parse("1.04.0"))                       # '1.4.0'

Constraints.parse("~> 1.2.3.4").check(Version.parse("1.2.3.5"))        # True
Constraints.parse(">= 1.0.0-beta").check(Version.parse("1.0.0-rc"))    # True
Constraints.parse(">= 1.0").check(Version.parse("1.5.0-beta"))         # False
```

`~> 1.2` allows any `1.x` at or above `1.2`. `~> 1.2.0` allows `1.2.x` only. The last segment given is the one that may increase.

### Sorting

```python
str(Constraints.parse("~> 2.0, >= 1.0, < 4.0, = 5.0").sorted())   # ' < 4.0, = 5.0,~> 2.0, >= 1.0'
```

`sort_versions` and `Constraints.sorted` return new lists. They reproduce Go's `sort.Stable` step for step, including the insertion sort Go uses up to 20 elements. This matters for go-version, whose comparison is not antisymmetric for prerelease parts such as `1` and `01`. A constraint keeps its original text, whitespace included, so a sorted string can start with a space.

### Errors

Rejected input raises `VersionError` or `ConstraintError` (both `ValueError`). The message is Go's `err.Error()` text, byte for byte, with Go's `%q` quoting:

```python
Constraints.parse(">=1.0 é\n")      # ConstraintError: improper constraint: ">=1.0 é\n"
hashicorp.Constraints.parse(">> 1")  # ConstraintError: malformed constraint: >> 1
```

## Reference

### `semver_dialects.masterminds`

| Name | Description |
| --- | --- |
| `Version.parse(text)` | Go `NewVersion` (default coercing mode). `v` prefix and missing minor or patch accepted. Limit 256 UTF-8 bytes. |
| `Version.parse_strict(text)` | Go `StrictNewVersion`. Exactly `MAJOR.MINOR.PATCH`, no `v`, no leading zeros. |
| `Version.major`, `minor`, `patch` | `int`, in the uint64 range. |
| `Version.prerelease`, `metadata`, `original` | `str`. `original` is the input as given. |
| `str(version)` | Go `String()`. |
| `compare(other)` | `-1`, `0` or `1`. Metadata is ignored. |
| `equal`, `less_than`, `less_than_or_equal`, `greater_than`, `greater_than_or_equal` | Go's `Equal`, `LessThan`, and so on, via `compare`. |
| `Constraints.parse(text, *, include_prerelease=False)` | Go `NewConstraint`. Limits: 512 UTF-8 bytes, 32 `||` groups. |
| `Constraints.include_prerelease` | Writable, like Go's public field. |
| `Constraints.check(version)` | `bool`. |
| `Constraints.validate(version)` | `(ok, reasons)`; `reasons` is `[]` when `ok`. |
| `str(constraints)` | Go `Constraints.String()`. |
| `sort_versions(versions)` | New list, ordered as Go `sort.Stable` would order it. |
| `VersionError`, `ConstraintError` | `ValueError` subclasses. |

Operators: none, `=`, `!=`, `>`, `<`, `>=`, `=>`, `<=`, `=<`, `~`, `~>`, `^`. Wildcards `x`, `X`, `*`. Hyphen ranges `A - B`. `||`, comma and whitespace.

### `semver_dialects.hashicorp`

| Name | Description |
| --- | --- |
| `Version.parse(text)` | Go `NewVersion`. Any number of numeric segments, padded to three. Prerelease with or without a hyphen. |
| `Version.parse_semver(text)` | Go `NewSemver`. A prerelease needs its hyphen. |
| `Version.segments` | `tuple[int, ...]`, int64 range, at least three entries. |
| `Version.specificity` | Segments the input spelled out (`1.2` gives 2). `~>` uses it. |
| `Version.prerelease`, `metadata`, `original` | `str`. |
| `str(version)`, `core()` | Go `String()` and `Core()`. |
| `compare(other)` and the named comparisons | As in `masterminds`. |
| `Constraints.parse(text)` | Go `NewConstraint`. Comma-separated. May raise `VersionError` for an out-of-range segment. |
| `Constraints.check(version)` | `bool`. All constraints must hold. |
| `Constraints.sorted()` | New `Constraints`, ordered by operator then version. |
| `str(constraints)` | The original pieces joined with `,`. |
| `sort_versions(versions)` | As in `masterminds`. |

Operators: none, `=`, `!=`, `>`, `<`, `>=`, `<=`, `~>`.

## How it works

The Masterminds side is a port of the Go source (MIT). One piece is not: `validConstraintRegex`. In that pattern an empty operator makes several `\s*` and `\s+` groups adjacent, so a run of whitespace can be divided among them in many ways. When a match fails late, a backtracking engine tries every division of every group. Go's own engine is linear-time, so Go is unaffected. Under Python's `re` the cost multiplies by about 20 for every additional group. The package replaces the pattern with one in which an operator, when present, is non-empty and the separator between constraints is either whitespace or a comma with optional whitespace, so each accepted string has one parse. Measured: `python bench/redos.py`

```
 runs  bytes    original pattern   replacement
    3     22              0.001s     0.000019s
    4     29              0.023s     0.000046s
    5     36              0.495s     0.000055s
    6     43             10.515s     0.000049s
    7     50       >20s (killed)     0.000055s
   70    491      not run (>20s)     0.000199s
```

`tests/test_valid_regex.py` checks that the replacement and the original pattern accept exactly the same strings, exhaustively for every string up to length 5 over an 18-character alphabet and up to length 6 to 9 over smaller ones, including the characters Python's `\s` accepts and Go's does not. `tests/test_redos.py` runs hostile inputs, in child processes with a 20 second limit.

The hashicorp/go-version side is an independent implementation. go-version is MPL-2.0. Its behavior was measured and reimplemented, and no file was ported or closely translated. Every rule was confirmed against go-version v1.9.0 by the differential tests below. There is no license file for it here because no go-version code is included.

Other Go details reproduced on purpose:

- Go's `\s` is `[\t\n\f\r ]`, and its `\d` is ASCII. The package uses explicit ASCII classes, never Python's Unicode-aware ones, and anchors with a full match so a trailing newline is not ignored.
- Masterminds segments are `uint64` and go-version segments are `int64`, with Go's `strconv` error texts. Digit runs are checked before `int()` sees them, because CPython refuses `int()` on more than 4300 digits.
- go-version's prerelease comparison reads the value `strconv.ParseInt` returns alongside an error (0 for a syntax error, the clamped limit for a range error). That changes some orderings, and it is reproduced.
- Length limits count UTF-8 bytes.

## Limitations

- Pinned to Masterminds/semver v3.5.0 and hashicorp/go-version v1.9.0. Other releases differ in places.
- Masterminds: only the default `CoerceNewVersion = true` path of `NewVersion` is modeled. The package-level Go switches (`CoerceNewVersion`, `DetailedNewVersionErrors`) are not exposed. `IncMajor`, `IncMinor`, `IncPatch`, `SetPrerelease`, `SetMetadata`, `New` and the JSON and SQL hooks are not implemented.
- go-version: the `WithPrefix` option, `Constraints.Equals`, `Constraint.Prerelease`, and the JSON and SQL hooks are not implemented.
- Errors carry Go's message but not Go's sentinel identity (`errors.Is`).
- Input must be `str`. `bytes` is rejected. Lone surrogates are escaped byte by byte, as Go escapes invalid UTF-8, but that path is not covered by the Go differential.
- `%q` quoting decides which characters are printable with Python's Unicode tables, and Go uses its own. A code point assigned in one Unicode version and not the other would be quoted differently. The Go differential covers a fixed set of unusual characters, not every code point.
- `==` on a `Version` compares all fields, including `original` and `metadata`. Use `equal()` for Go's `Equal`.
- Not designed for PEP 440. Use `packaging` for that.

## Compatibility

Run: CPython 3.14.7 on macOS (arm64), Go 1.27.1 for the differential. Tests pass with `pytest` and `mypy --strict src tests`. The CI workflow runs the tests on 3.11, 3.12, 3.13 and 3.14. Those four are "run in CI", not tested here. Only 3.14 was run for this release.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -rs
.venv/bin/python -m mypy --strict src tests
```

Tests, and what each proves:

- `tests/test_corpus.py` replays `tests/data/*.jsonl.gz`: 600 versions and 20000 constraints per dialect, with parse accept/reject and error text, `String`, `Original`, `Check`, `Validate`, `Compare`, and `sort.Stable` results recorded from the Go libraries. `tests/data/README.txt` describes the records. The corpus was produced by `tests/oracle` with seed 20260929.
- `tests/test_live_go.py` runs the Go oracle on fresh seeds (101 and 202 by default, or `SEMVER_DIALECTS_SEEDS=1,2,3`), and on exhaustive short inputs, odd Unicode, size limits, out-of-range numbers, and sorts of up to 257 elements. It needs `go` on `PATH` and the two Go modules, which Go downloads on first run (`tests/oracle/go.mod` names them; nothing from them is vendored). When Go is missing or cannot fetch the modules, these tests skip and `-rs` prints why.
- `tests/test_valid_regex.py` and `tests/test_redos.py` cover the regex replacement and hostile inputs.

For a run without network access: `GOPROXY=file://$(go env GOMODCACHE)/cache/download GOSUMDB=off GOFLAGS=-mod=mod`.

## License

MIT. See [LICENSE](LICENSE). The Masterminds port carries that project's MIT license in [LICENSE-masterminds-semver](LICENSE-masterminds-semver).
