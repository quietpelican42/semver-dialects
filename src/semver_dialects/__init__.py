"""Version constraints that behave like Go's Masterminds/semver and hashicorp/go-version.

Use `semver_dialects.masterminds` for Helm-style constraints and
`semver_dialects.hashicorp` for Terraform-style constraints.
"""

from __future__ import annotations

from . import hashicorp, masterminds

__all__ = ["hashicorp", "masterminds"]
__version__ = "0.1.0"
