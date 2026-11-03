"""Rule-based grammar and style checks. No external dependencies."""
from __future__ import annotations

import re
from typing import Dict, List

from .models import Issue
from .reader import WORD_RE, MarkdownDoc, clean_inline

LONG_SENTENCE_WORDS = 30

RULES: Dict[str, str] = {
    "STY001": "Sentence longer than 30 words",
    "STY002": "Agentive passive voice (\"was created by ...\")",
    "STY003": "Wordy phrase with a shorter alternative",
    "STY004": "Filler or subjective word",
    "STY005": "Common misspelling",
    "STY006": "Repeated word",
    "STY007": "Wrong article (a / an)",
    "STY008": "Multiple exclamation or question marks",
    "STY009": "Multiple consecutive spaces",
    "STY010": "Stray trailing whitespace",
    "STY011": "Paragraph ends without punctuation",
    "STY012": "Sentence starts with a lowercase letter",
    "STY013": "Heading level skipped",
    "STY014": "Heading ends with punctuation",
    "STY015": "Non-descriptive link text",
    "STY016": "Image without alt text",
}

WORDY = {
    "in order to": "to",
    "utilize": "use",
    "utilise": "use",
    "due to the fact that": "because",
    "at this point in time": "now",
    "a number of": "several",
    "is able to": "can",
    "are able to": "can",
    "prior to": "before",
    "in the event that": "if",
    "with regard to": "about",
    "for the purpose of": "for",
    "in addition to": "besides",
    "make use of": "use",
}
FILLER = ["simply", "just", "easily", "obviously", "basically", "clearly",
          "very", "really", "quite", "actually", "of course"]
MISSPELLINGS = {
    "teh": "the", "recieve": "receive", "recieved": "received", "occured": "occurred",
    "occurence": "occurrence", "seperate": "separate", "definately": "definitely",
    "accomodate": "accommodate", "enviroment": "environment", "dependancy": "dependency",
    "dependancies": "dependencies", "paramter": "parameter", "paramters": "parameters",
    "succesful": "successful", "succesfully": "successfully", "refered": "referred",
    "writting": "writing", "begining": "beginning", "existance": "existence",
    "wich": "which", "adress": "address", "sucess": "success", "functionallity": "functionality",
    "configuation": "configuration", "documention": "documentation", "arguement": "argument",
    "commited": "committed", "neccessary": "necessary", "untill": "until", "wether": "whether",
}
GENERIC_LINK_TEXT = {"here", "click here", "this", "link", "this link", "read more",
                     "more", "more info", "this page", "page", "url"}

WORDY_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in WORDY) + r")\b", re.I)
FILLER_RE = re.compile(r"(?<![\w-])(" + "|".join(FILLER) + r")(?![\w-])", re.I)
MISSPELL_RE = re.compile(r"\b(" + "|".join(MISSPELLINGS) + r")\b", re.I)
REPEAT_RE = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.I)
REPEAT_OK = {"that", "had"}
ARTICLE_RE = re.compile(r"\b(a|an)\s+([A-Za-z][A-Za-z0-9'-]*)", re.I)
PASSIVE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+"
    r"(\w+ed|built|made|done|given|shown|known|found|written|chosen|taken|seen|sent|kept|held)"
    r"\s+by\b", re.I)
EMPHATIC_RE = re.compile(r"!{2,}|\?{2,}|\?!|!\?")
LOWER_START_RE = re.compile(r"(?<=[A-Za-z]{3})[.!?]\s+[a-z]")

VOWEL_SOUND_EXCEPTIONS = ("unique", "uniform", "unit", "united", "universal", "universe",
                          "university", "unicode", "unix", "unified", "unify", "union",
                          "use", "usual", "usage", "util", "european", "one", "once",
                          "ubuntu", "uuid", "euro")
SILENT_H = ("hour", "honest", "honor", "honour", "heir")
ABBREVIATIONS = ["e.g.", "i.e.", "etc.", "vs.", "approx.", "Dr.", "Mr.", "Mrs.", "Ms.",
                 "No.", "Fig.", "cf.", "U.S.", "a.m.", "p.m."]


def split_sentences(text: str) -> List[str]:
    protected = text
    for a in ABBREVIATIONS:
        protected = protected.replace(a, a.replace(".", "\u0000"))
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])", protected)
    return [p.replace("\u0000", ".").strip() for p in parts if p.strip()]


def _word_count(s: str) -> int:
    return len(WORD_RE.findall(s))


def _starts_with_vowel_sound(word: str) -> bool:
    w = word.lower()
    if w.startswith(SILENT_H):
        return True
    if w.startswith(VOWEL_SOUND_EXCEPTIONS):
        return False
    return w[0] in "aeiou"


def check_style(doc: MarkdownDoc) -> List[Issue]:
    f = str(doc.path)
    issues: List[Issue] = []

    def add(rule: str, sev: str, line: int, msg: str, sug: str | None = None) -> None:
        issues.append(Issue("style", rule, sev, f, line, msg, sug))

    # ---- line-level checks -------------------------------------------------
    for ln, raw in doc.prose_lines():
        stripped = raw.strip()
        if not stripped:
            continue
        original = doc.lines[ln - 1]
        trailing = len(original) - len(original.rstrip(" \t"))
        if trailing == 1 or trailing >= 3:
            add("STY010", "info", ln, "Trailing whitespace",
                "Remove it (two trailing spaces are a Markdown line break)")

        no_code = INLINE_CODE_RE_SUB(raw)
        if not stripped.startswith("|") and re.search(r"(?<=\S) {2,}(?=\S)", no_code.strip()):
            add("STY009", "info", ln, "Multiple consecutive spaces", "Use a single space")

        text = clean_inline(raw)
        for m in WORDY_RE.finditer(text):
            add("STY003", "info", ln, f"Wordy phrase '{m.group(0)}'",
                f"Use '{WORDY[m.group(0).lower()]}'")
        for m in FILLER_RE.finditer(text):
            add("STY004", "info", ln, f"Filler word '{m.group(0)}'",
                "Delete it, or state the exact condition instead")
        for m in MISSPELL_RE.finditer(text):
            add("STY005", "warning", ln, f"Possible misspelling '{m.group(0)}'",
                f"Did you mean '{MISSPELLINGS[m.group(0).lower()]}'?")
        for m in REPEAT_RE.finditer(text):
            if m.group(1).lower() not in REPEAT_OK:
                add("STY006", "warning", ln, f"Repeated word '{m.group(1)}'", "Remove the duplicate")
        for m in ARTICLE_RE.finditer(text):
            article, word = m.group(1), m.group(2)
            if len(word) < 2 or word.isupper():
                continue  # single letters and acronyms are ambiguous
            vowel = _starts_with_vowel_sound(word)
            if article.lower() == "a" and vowel:
                add("STY007", "warning", ln, f"Use 'an' before '{word}'", f"an {word}")
            elif article.lower() == "an" and not vowel:
                add("STY007", "warning", ln, f"Use 'a' before '{word}'", f"a {word}")
        if EMPHATIC_RE.search(text):
            add("STY008", "warning", ln, "Multiple exclamation or question marks",
                "Technical writing rarely needs emphatic punctuation")

    # ---- paragraph-level checks -------------------------------------------
    for p in doc.paragraphs():
        for s in split_sentences(p.text):
            n = _word_count(s)
            if n > LONG_SENTENCE_WORDS:
                snippet = " ".join(s.split()[:8]) + "..."
                add("STY001", "warning", p.line,
                    f"Sentence is {n} words (limit {LONG_SENTENCE_WORDS}): \"{snippet}\"",
                    "Split it into two sentences")
            m = PASSIVE_RE.search(s)
            if m:
                add("STY002", "info", p.line, f"Passive voice: \"{m.group(0)}\"",
                    "Name the actor first, for example 'The team built X'")
        if (
            p.kind == "para"
            and _word_count(p.text) >= 6
            and p.text[-1].isalnum()
            and not (p.end < len(doc.lines) and doc.in_code[p.end])
        ):
            add("STY011", "info", p.line, "Paragraph does not end with punctuation",
                "End the sentence with a period, or a colon before a code block")
        protected = p.text
        for a in ABBREVIATIONS:
            protected = protected.replace(a, a.replace(".", "\u0000"))
        if LOWER_START_RE.search(protected):
            add("STY012", "info", p.line, "A sentence starts with a lowercase letter",
                "Capitalise it, or merge it with the previous sentence")

    # ---- headings ----------------------------------------------------------
    prev = None
    for h in doc.headings:
        if prev is not None and h.level > prev.level + 1:
            add("STY013", "warning", h.line,
                f"Heading level jumps from H{prev.level} to H{h.level}: \"{h.title}\"",
                f"Use H{prev.level + 1}")
        if h.title.rstrip().endswith((".", ":", ",", ";")):
            add("STY014", "info", h.line, f"Heading ends with punctuation: \"{h.title}\"",
                "Remove the trailing punctuation")
        prev = h

    # ---- links and images --------------------------------------------------
    for link in doc.links:
        if link.is_image:
            if not link.text.strip():
                add("STY016", "warning", link.line, "Image has no alt text",
                    "Describe the image inside the square brackets")
        elif link.text.strip().lower() in GENERIC_LINK_TEXT and link.url != link.text:
            add("STY015", "warning", link.line, f"Non-descriptive link text '{link.text}'",
                "Describe where the link goes")

    issues.sort(key=lambda i: (i.line, i.rule))
    return issues


def INLINE_CODE_RE_SUB(s: str) -> str:
    return re.sub(r"`+[^`]*`+", "X", s)
