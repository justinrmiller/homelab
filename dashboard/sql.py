"""SQL helpers.

The dashboard deliberately exposes a raw SQL console, but the guided
table-management controls should not be a second, sloppier injection path —
identifiers there are validated before interpolation.
"""

from __future__ import annotations

import re

# Postgres identifiers are limited to 63 bytes; anything outside this shape
# would have to be quoted, which the guided controls do not support.
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def safe_identifier(name: str) -> str:
    """Return ``name`` if it is a bare SQL identifier, else raise ``ValueError``."""
    candidate = name.strip()
    if not IDENTIFIER_RE.match(candidate):
        raise ValueError(
            f"{name!r} is not a valid table name. Use letters, digits and "
            "underscores, starting with a letter or underscore."
        )
    return candidate


def is_read_only(statement: str) -> bool:
    """Best-effort check for whether a statement only reads.

    Used to decide between rendering a result grid and running a write; it is a
    UI affordance, not a security boundary.
    """
    first = statement.strip().lstrip("(").lower()
    return first.startswith(("select", "with", "show", "explain", "table", "values"))
