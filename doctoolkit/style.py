"""Grammar and style checks (rule-based, no ML).

Rules are intentionally conservative: they flag patterns that are almost
always worth a second look, and carry a suggestion where one is obvious.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .models import Issue
from .reader import Doc

DEFAULTS = {
    "max_sentence_words": 30,
    "weasel_words": [
        "very", "really", "simply", "just", "easily", "obviously", "clearly",
        "basically", "actually", "quite", "fairly", "relatively", "somewhat",
    ],
    "wordy_phrases": {
        "in order to": "to",
        "utilize": "use",
        "utilise": "use",
        "leverage": "use",
        "a number of": "several",
        "due to the fact that": "because",
        "at this point in time": "now",
        "in the event that": "if",
        "is able to": "can",
        "are able to": "can",
        "prior to": "before",
        "with regards to": "about",
        "for the purpose of": "to",
    },
}

GENERIC_LINK_TEXT = {"click here", "here", "this link", "link", "read more", "more", "this", "this page"}
PASSIVE_NOT_PARTICIPLES = {"need", "speed", "feed", "indeed", "seed", "red", "bed", "hundred", "weed"}
IRREGULAR = (
    "written|done|made|given|shown|taken|known|built|run|set|sent|seen|found|held|"
    "kept|left|lost|paid|put|read|told|chosen|stored|begun|broken|driven"
)
PASSIVE_RE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?((?:\w{2,}ed)|" + IRREGULAR + r")\b",
    re.I,
)
REPEATED_RE = re.compile(r"\b(\w+)\s+\1\b", re.I)
PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|TBD|XXX)\b|lorem ipsum", re.I)
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[§])")


def _split_sentences(text: str):
    pos = 0
    for m in SENT_SPLIT_RE.finditer(text):
        yield pos, text[pos : m.start()]
        pos = m.end()
    yield pos, text[pos:]


def _merged(cfg: Optional[dict]) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    for k, v in (cfg or {}).items():
        if k in out:
            out[k] = v
    return out


def check_style(doc: Doc, cfg: Optional[dict] = None) -> List[Issue]:
    c = _merged(cfg)
    issues: List[Issue] = []
    max_words = int(c["max_sentence_words"])
    weasel_re = re.compile(
        r"(?<![\w-])(" + "|".join(map(re.escape, c["weasel_words"])) + r")(?![\w-])", re.I
    ) if c["weasel_words"] else None
    wordy: Dict[str, str] = {k.lower(): v for k, v in c["wordy_phrases"].items()}
    wordy_re = re.compile(
        r"(?<![\w-])(" + "|".join(map(re.escape, sorted(wordy, key=len, reverse=True))) + r")(?![\w-])", re.I
    ) if wordy else None

    def add(rule, sev, line, msg, sugg=None, ctx=None):
        issues.append(Issue("style", rule, sev, doc.name, line, msg, sugg, ctx))

    # ---- sentence-level rules -------------------------------------------
    for par in doc.paragraphs():
        for off, sent in _split_sentences(par.text):
            s = sent.strip()
            if not s:
                continue
            line = par.line_at(off)
            nwords = len(s.split())
            if nwords > max_words:
                add("long-sentence", "warning", line,
                    f"Sentence has {nwords} words (limit {max_words}).",
                    "Split it into two sentences.", par.raw)
            for m in PASSIVE_RE.finditer(s):
                if m.group(1).lower() in PASSIVE_NOT_PARTICIPLES:
                    continue
                add("passive-voice", "info", par.line_at(off + m.start()),
                    f"Possible passive voice: \"{m.group(0)}\".",
                    "Prefer an active construction with a clear actor.", par.raw)
            if weasel_re:
                for m in weasel_re.finditer(s):
                    add("weasel-word", "info", par.line_at(off + m.start()),
                        f"Vague intensifier \"{m.group(1)}\".",
                        "Remove it or be specific.", par.raw)
            if wordy_re:
                for m in wordy_re.finditer(s):
                    add("wordy-phrase", "info", par.line_at(off + m.start()),
                        f"Wordy phrase \"{m.group(1)}\".",
                        f"Use \"{wordy[m.group(1).lower()]}\".", par.raw)
            for m in REPEATED_RE.finditer(s):
                if m.group(1).lower() in {"had", "that"} or m.group(1).isdigit():
                    continue
                add("repeated-word", "warning", par.line_at(off + m.start()),
                    f"Repeated word \"{m.group(1)}\".", f"Remove one \"{m.group(1)}\".", par.raw)

    # ---- line-level rules -----------------------------------------------
    for ln, cleaned, raw in doc.clean_lines():
        if PLACEHOLDER_RE.search(cleaned):
            add("placeholder-text", "warning", ln,
                f"Placeholder text left in the document: \"{PLACEHOLDER_RE.search(cleaned).group(0)}\".",
                "Finish or remove it.", raw)
        stripped = raw.rstrip(" \t")
        trailing = len(raw) - len(stripped)
        if raw.strip() and trailing and not (trailing == 2 and raw.endswith("  ")):
            add("trailing-whitespace", "info", ln, "Trailing whitespace.", "Delete it.")

    # ---- structure rules ------------------------------------------------
    h1s = [h for h in doc.headings if h.level == 1]
    if len(h1s) > 1:
        add("multiple-h1", "warning", h1s[1].line,
            f"Document has {len(h1s)} top-level headings.", "Use a single H1 as the title.")
    prev = None
    seen: Dict[str, int] = {}
    for h in doc.headings:
        if prev is not None and h.level > prev.level + 1:
            add("heading-level-skip", "warning", h.line,
                f"Heading jumps from H{prev.level} to H{h.level}.", f"Use H{prev.level + 1}.")
        if h.text.rstrip().endswith((".", ":", ",", ";")):
            add("heading-punctuation", "info", h.line, "Heading ends with punctuation.", "Remove it.")
        key = h.text.lower()
        if key in seen:
            add("duplicate-heading", "info", h.line,
                f"Duplicate heading (first used on line {seen[key]}).", "Make headings unique so anchors stay stable.")
        else:
            seen[key] = h.line
        prev = h

    for cb in doc.code_blocks:
        if not cb.closed:
            add("unclosed-code-fence", "error", cb.line, "Code fence is never closed.")
        elif not cb.lang:
            add("code-fence-language", "info", cb.line,
                "Code block has no language.", "Add a language (e.g. ```python) for highlighting.")

    for link in doc.links:
        if link.is_image and not link.text.strip():
            add("missing-alt-text", "warning", link.line, f"Image {link.target} has no alt text.",
                "Describe the image for screen readers.")
        elif not link.is_image and link.kind == "inline" and link.text.strip().lower() in GENERIC_LINK_TEXT:
            add("generic-link-text", "warning", link.line,
                f"Non-descriptive link text \"{link.text.strip()}\".", "Say where the link goes.")
    return issues
