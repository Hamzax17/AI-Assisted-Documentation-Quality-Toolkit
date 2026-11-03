"""Terminology consistency: a JSON glossary plus cross-document variant detection."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .models import Issue
from .reader import MarkdownDoc, clean_inline

RULES = {
    "TRM001": "Term differs from the preferred form in the glossary",
    "TRM002": "Spelling variants of the same word are mixed across the documents",
}


@dataclass
class Term:
    preferred: str
    avoid: List[str]
    note: str = ""
    case_sensitive: bool = True
    _patterns: List[Tuple[str, "re.Pattern[str]"]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        for bad in self.avoid:
            pattern = r"(?<![\w./@#-])" + re.escape(bad) + r"(?![\w@-]|\.\w)"
            self._patterns.append((bad, re.compile(pattern, flags)))


def load_terms(path: Optional[Path]) -> List[Term]:
    """Load terms from a JSON file shaped like {"terms": [{"preferred": ..., "avoid": [...]}]}."""
    if path is None or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    terms: List[Term] = []
    for i, entry in enumerate(data.get("terms", [])):
        if "preferred" not in entry or not entry.get("avoid"):
            raise ValueError(f"{path}: term #{i + 1} needs 'preferred' and a non-empty 'avoid' list")
        terms.append(Term(
            preferred=entry["preferred"],
            avoid=list(entry["avoid"]),
            note=entry.get("note", ""),
            case_sensitive=entry.get("case_sensitive", True),
        ))
    return terms


def _texts(doc: MarkdownDoc) -> Iterable[Tuple[int, str]]:
    for ln, raw in doc.prose_lines():
        yield ln, clean_inline(raw)
    for h in doc.headings:
        yield h.line, clean_inline(h.title)


def check_terminology(doc: MarkdownDoc, terms: List[Term]) -> List[Issue]:
    f = str(doc.path)
    issues: List[Issue] = []
    for ln, text in _texts(doc):
        for term in terms:
            for bad, pattern in term._patterns:
                for m in pattern.finditer(text):
                    if m.group(0) == term.preferred:
                        continue
                    sug = f"Use '{term.preferred}'" + (f" ({term.note})" if term.note else "")
                    issues.append(Issue("terminology", "TRM001", "warning", f, ln,
                                        f"Use '{term.preferred}' instead of '{m.group(0)}'", sug))
    issues.sort(key=lambda i: (i.line, i.rule))
    return issues


def find_variant_inconsistencies(docs: List[MarkdownDoc]) -> List[Issue]:
    """Flag hyphenated words that also appear joined or spaced (for example set-up / setup).

    Looks across all documents so one project does not mix 'back-end' and 'backend'.
    Reports every occurrence of the less common forms.
    """
    uni_loc: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    bi_loc: Dict[Tuple[str, str], List[Tuple[str, int]]] = defaultdict(list)
    hy_loc: Dict[Tuple[str, str], List[Tuple[str, int]]] = defaultdict(list)

    for doc in docs:
        f = str(doc.path)
        for ln, text in _texts(doc):
            for segment in re.split(r"[.!?;:,()\[\]\"/]", text.lower()):
                tokens = re.findall(r"[a-z]+(?:-[a-z]+)*", segment)
                plain: List[str] = []
                for tok in tokens:
                    if "-" in tok:
                        parts = tok.split("-")
                        if len(parts) == 2 and all(len(p) >= 2 for p in parts):
                            hy_loc[(parts[0], parts[1])].append((f, ln))
                        plain.append("")  # break bigram chains at hyphenated words
                    else:
                        uni_loc[tok].append((f, ln))
                        plain.append(tok)
                for a, b in zip(plain, plain[1:]):
                    if a and b:
                        bi_loc[(a, b)].append((f, ln))

    issues: List[Issue] = []
    for (a, b), hy_where in hy_loc.items():
        forms = {f"{a}-{b}": hy_where}
        if uni_loc.get(a + b):
            forms[a + b] = uni_loc[a + b]
        if bi_loc.get((a, b)):
            forms[f"{a} {b}"] = bi_loc[(a, b)]
        if len(forms) < 2:
            continue
        preferred = max(forms, key=lambda k: (len(forms[k]), k == a + b))
        counts = ", ".join(f"'{k}' x{len(v)}" for k, v in forms.items())
        for form, where in forms.items():
            if form == preferred:
                continue
            for file, line in where:
                issues.append(Issue(
                    "terminology", "TRM002", "info", file, line,
                    f"Mixed spellings: {counts}",
                    f"Use '{preferred}' everywhere, or add the pair to the glossary"))
    return issues
