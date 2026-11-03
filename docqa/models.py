"""Shared data models and the quality score."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_WEIGHT = {"error": 5.0, "warning": 2.0, "info": 0.5}


@dataclass
class Issue:
    """One finding produced by a check."""

    check: str  # links | style | terminology | sections
    rule: str  # stable rule id, e.g. STY001
    severity: str  # error | warning | info
    file: str
    line: int
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


def quality_score(issues: Iterable[Issue], words: int) -> int:
    """Score from 0 to 100.

    Each issue adds a penalty (error 5, warning 2, info 0.5). Penalties are
    scaled down for documents longer than 500 words, so long documents are not
    punished for having more text.
    """
    penalty = sum(SEVERITY_WEIGHT.get(i.severity, 0.0) for i in issues)
    scale = 500 / max(words, 500)
    return max(0, round(100 - penalty * scale))


@dataclass
class FileResult:
    """All findings for one Markdown file."""

    file: str
    words: int
    issues: List[Issue] = field(default_factory=list)

    @property
    def score(self) -> int:
        return quality_score(self.issues, self.words)

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)
