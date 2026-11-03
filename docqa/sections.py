"""Missing section detection, driven by per-document-type profiles in JSON."""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Issue
from .reader import MarkdownDoc, clean_inline

RULES = {
    "SEC001": "Document has no H1 title",
    "SEC002": "Document has more than one H1 title",
    "SEC003": "Required section is missing",
    "SEC004": "Section has no content",
    "SEC005": "Placeholder text left in the document",
}

DEFAULT_CONFIG: Dict = {"default": {"require_h1": True, "required": []}, "profiles": {}}

PLACEHOLDER_CASE_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b")
PLACEHOLDER_ANY_RE = re.compile(r"lorem ipsum|coming soon|to be (?:written|added|determined)", re.I)


def load_section_config(path: Optional[Path]) -> Dict:
    if path is None or not Path(path).exists():
        return DEFAULT_CONFIG
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pick_profile(doc: MarkdownDoc, cfg: Dict) -> Tuple[str, Dict]:
    """Choose a profile from front matter (doc_type) or the file name patterns."""
    profiles = cfg.get("profiles", {})
    declared = doc.front_matter.get("doc_type", "").lower()
    if declared in profiles:
        return declared, profiles[declared]
    posix = doc.path.as_posix().lower()
    name = doc.path.name.lower()
    for pname, prof in profiles.items():
        for pat in prof.get("match", []):
            pat = pat.lower()
            if fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(posix, pat) \
                    or fnmatch.fnmatchcase(posix, "*/" + pat):
                return pname, prof
    return "default", cfg.get("default", {})


def _normalise(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", clean_inline(title).lower())).strip()


def _empty_sections(doc: MarkdownDoc) -> List[int]:
    empty: List[int] = []
    hs = doc.headings
    for idx, h in enumerate(hs):
        if idx + 1 < len(hs) and hs[idx + 1].level > h.level:
            continue  # has sub-sections
        end = hs[idx + 1].line - 1 if idx + 1 < len(hs) else len(doc.lines)
        body = [ln for ln in doc.lines[h.end_line:end]
                if ln.strip() and not ln.strip().startswith("<!--")]
        if not body:
            empty.append(h.line)
    return empty


def check_sections(doc: MarkdownDoc, cfg: Optional[Dict] = None) -> List[Issue]:
    cfg = cfg or DEFAULT_CONFIG
    f = str(doc.path)
    pname, profile = pick_profile(doc, cfg)
    base = cfg.get("default", {})
    require_h1 = profile.get("require_h1", base.get("require_h1", True))
    issues: List[Issue] = []

    h1s = [h for h in doc.headings if h.level == 1]
    if require_h1 and not h1s:
        issues.append(Issue("sections", "SEC001", "warning", f, 1,
                            "Document has no H1 title", "Start the file with '# Title'"))
    if len(h1s) > 1:
        issues.append(Issue("sections", "SEC002", "warning", f, h1s[1].line,
                            f"Document has {len(h1s)} H1 titles",
                            "Keep one H1 and demote the others to H2"))

    titles = [_normalise(h.title) for h in doc.headings]
    required = list(base.get("required", [])) + list(profile.get("required", []))
    for req in required:
        aliases = [a.lower() for a in req.get("aliases", [])] or [req["name"].lower()]
        if not any(re.search(r"\b" + re.escape(a) + r"\b", t) for a in aliases for t in titles):
            issues.append(Issue(
                "sections", "SEC003", req.get("severity", "warning"), f, 1,
                f"Missing required section '{req['name']}' (profile: {pname})",
                "Add a heading such as: " + ", ".join(req.get("aliases", [req["name"]])[:3])))

    for line in _empty_sections(doc):
        title = next(h.title for h in doc.headings if h.line == line)
        issues.append(Issue("sections", "SEC004", "warning", f, line,
                            f"Section '{title}' has no content", "Add content or remove the heading"))

    for ln, raw in doc.prose_lines():
        text = clean_inline(raw)
        m = PLACEHOLDER_CASE_RE.search(text) or PLACEHOLDER_ANY_RE.search(text)
        if m:
            issues.append(Issue("sections", "SEC005", "warning", f, ln,
                                f"Placeholder text '{m.group(0)}'", "Write the missing content"))

    issues.sort(key=lambda i: (i.line, i.rule))
    return issues
