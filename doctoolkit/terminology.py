"""Terminology consistency, driven by a JSON glossary.

Glossary format::

    {"terms": [{"preferred": "GitHub", "avoid": ["Github", "github"], "note": "..."}]}

An ``avoid`` form is matched case-sensitively when it differs from the
preferred form only by case, otherwise case-insensitively. Set
``"case_sensitive": true/false`` on a term to override.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .models import Issue
from .reader import Doc

DEFAULT_GLOSSARY = Path(__file__).parent / "data" / "default_glossary.json"


def load_glossary(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_GLOSSARY
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data.get("terms"), list):
        raise ValueError(f"{p}: glossary must contain a 'terms' list")
    for t in data["terms"]:
        if "preferred" not in t or not isinstance(t.get("avoid", []), list):
            raise ValueError(f"{p}: each term needs 'preferred' and an 'avoid' list")
    return data


def _pattern(term: str, case_sensitive: bool) -> re.Pattern:
    return re.compile(
        r"(?<![\w./@-])" + re.escape(term) + r"(?![\w-]|\.\w)",
        0 if case_sensitive else re.I,
    )


def check_terminology(doc: Doc, glossary: dict) -> Tuple[List[Issue], Dict[str, dict]]:
    """Return (issues, usage) where usage maps preferred term -> counts."""
    issues: List[Issue] = []
    usage: Dict[str, dict] = {}
    compiled = []
    for t in glossary["terms"]:
        pref = t["preferred"]
        usage[pref] = {"preferred": 0, "variants": {}}
        pats = []
        for bad in t.get("avoid", []):
            cs = t.get("case_sensitive", bad.lower() == pref.lower())
            pats.append((bad, _pattern(bad, cs)))
        compiled.append((t, _pattern(pref, True), pats))

    for ln, cleaned, raw in doc.clean_lines():
        for t, pref_pat, pats in compiled:
            pref = t["preferred"]
            usage[pref]["preferred"] += len(pref_pat.findall(cleaned))
            for bad, pat in pats:
                for m in pat.finditer(cleaned):
                    if m.group(0) == pref:
                        continue
                    usage[pref]["variants"][bad] = usage[pref]["variants"].get(bad, 0) + 1
                    note = f" {t['note']}" if t.get("note") else ""
                    issues.append(Issue(
                        "terminology", "inconsistent-term", "warning", doc.name, ln,
                        f"Use \"{pref}\" instead of \"{m.group(0)}\".{note}",
                        f"Replace with \"{pref}\".", raw,
                    ))
    return issues, usage
