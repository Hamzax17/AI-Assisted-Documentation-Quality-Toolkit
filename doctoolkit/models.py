"""Shared data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

SEVERITIES = ("error", "warning", "info")
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    check: str  # links | style | terminology | sections
    rule: str  # machine-readable rule id, e.g. "broken-link"
    severity: str  # error | warning | info
    file: str
    line: int
    message: str
    suggestion: Optional[str] = None
    context: Optional[str] = None  # raw passage the issue belongs to (used by AI rewriting)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("context", None)  # keep the report compact; rewrites carry the passage
        return d
