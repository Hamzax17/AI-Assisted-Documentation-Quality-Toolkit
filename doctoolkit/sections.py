"""Missing-section detection, driven by a JSON profile file.

Each profile lists *groups* of acceptable heading names; a group is
satisfied when any heading matches one of its names. A document is matched
to a profile by file name pattern, or by ``doc_type:`` in its front matter.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from .models import Issue
from .reader import Doc

DEFAULT_SECTIONS = Path(__file__).parent / "data" / "default_sections.json"


def load_sections(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_SECTIONS
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data.get("profiles", {}), dict):
        raise ValueError(f"{p}: 'profiles' must be an object")
    return data


def _norm(heading: str) -> str:
    s = re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s+", "", heading.lower())
    return re.sub(r"[^\w\s]", "", s).strip()


def pick_profile(doc: Doc, cfg: dict) -> Tuple[str, dict]:
    profiles = cfg.get("profiles", {})
    declared = doc.meta.get("doc_type", "").lower()
    if declared in profiles:
        return declared, profiles[declared]
    rel = PurePosixPath(doc.name.replace("\\", "/"))
    for name, prof in profiles.items():
        if any(rel.match(pat) or PurePosixPath(rel.name).match(pat) for pat in prof.get("match", [])):
            return name, prof
    return "default", cfg.get("default", {})


def _has(group: List[str], headings: List[str]) -> bool:
    alts = [_norm(a) for a in group]
    return any(h == a or h.startswith(a + " ") for h in headings for a in alts)


def check_sections(doc: Doc, cfg: dict) -> List[Issue]:
    issues: List[Issue] = []

    def add(rule, sev, line, msg, sugg=None):
        issues.append(Issue("sections", rule, sev, doc.name, line, msg, sugg))

    if cfg.get("require_h1", True) and not any(h.level == 1 for h in doc.headings) and "title" not in doc.meta:
        add("missing-title", "warning", 1, "Document has no top-level heading (H1).", "Start with \"# Title\".")

    min_words = int(cfg.get("min_words", 0))
    if min_words and doc.words < min_words:
        add("too-short", "info", 1, f"Document has only {doc.words} words (minimum {min_words}).")

    pname, prof = pick_profile(doc, cfg)
    headings = [_norm(h.text) for h in doc.headings]
    for severity, key in (("warning", "required"), ("info", "recommended")):
        for group in prof.get(key, []):
            if not _has(group, headings):
                alts = ", ".join(f'"{g}"' for g in group)
                label = "required" if key == "required" else "recommended"
                add("missing-section", severity, 1,
                    f"Missing {label} section ({pname} profile): {alts}.",
                    f"Add a \"## {group[0]}\" section.")

    # Empty sections: a heading with no content before the next heading,
    # unless that next heading is a sub-section.
    for i, h in enumerate(doc.headings):
        nxt = doc.headings[i + 1] if i + 1 < len(doc.headings) else None
        end = nxt.line - 1 if nxt else len(doc.lines)
        body = [l for l in doc.lines[h.line : end] if l.strip()]
        if not body and not (nxt and nxt.level > h.level):
            add("empty-section", "warning", h.line, f"Section \"{h.text}\" is empty.",
                "Write the section or remove the heading.")
    return issues
