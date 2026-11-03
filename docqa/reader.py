"""Markdown reader.

Parses a Markdown file into headings, links, code regions and prose, with no
third-party dependencies. All line numbers are 1-based.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
SETEXT_RE = re.compile(r"^[ \t]{0,3}(={2,}|-{2,})[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
LIST_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
TASK_RE = re.compile(r"^\[[ xX]\][ \t]+")
HR_RE = re.compile(r"^(?:[-*_][ \t]*){3,}$")

INLINE_CODE_RE = re.compile(r"`+[^`]*`+")
INLINE_LINK_RE = re.compile(
    r"(!?)\[([^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
REF_DEF_RE = re.compile(r"^[ \t]{0,3}\[([^\]]+)\]:[ \t]*<?(\S+?)>?(?:[ \t]+.*)?$")
REF_USE_RE = re.compile(r"(!?)\[([^\]]+)\]\[([^\]]*)\]")
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
BARE_URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
EMPHASIS_RE = re.compile(r"(?<![\w*])(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1(?![\w*])")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


@dataclass
class Heading:
    level: int
    title: str
    line: int
    end_line: int  # last line of the heading (differs from line for setext)


@dataclass
class Link:
    text: str
    url: str
    line: int
    is_image: bool = False
    undefined_ref: Optional[str] = None  # set when [text][ref] has no definition


@dataclass
class Paragraph:
    line: int
    end: int
    text: str  # cleaned prose: no code, URLs or markup
    kind: str  # "para" or "list"


def clean_inline(s: str) -> str:
    """Strip inline code, links, URLs, HTML tags and emphasis from a line."""
    s = INLINE_CODE_RE.sub(" ", s)
    s = INLINE_LINK_RE.sub(lambda m: "" if m.group(1) else m.group(2), s)
    s = REF_USE_RE.sub(lambda m: "" if m.group(1) else m.group(2), s)
    s = AUTOLINK_RE.sub(" ", s)
    s = BARE_URL_RE.sub(" ", s)
    s = HTML_TAG_RE.sub(" ", s)
    for _ in range(2):
        s = EMPHASIS_RE.sub(r"\2", s)
    return s


def slugify(title: str) -> str:
    """GitHub-style heading anchor."""
    t = re.sub(r"`([^`]*)`", r"\1", title)
    t = INLINE_LINK_RE.sub(lambda m: m.group(2), t)
    for _ in range(2):
        t = EMPHASIS_RE.sub(r"\2", t)
    t = re.sub(r"[^\w\- ]", "", t.strip().lower(), flags=re.UNICODE)
    return t.replace(" ", "-")


@dataclass
class MarkdownDoc:
    path: Path
    text: str
    lines: List[str]
    in_code: List[bool]
    hidden: List[bool]  # front matter and HTML comments
    structural: List[bool]  # headings, setext underlines, reference definitions
    front_matter: Dict[str, str]
    headings: List[Heading]
    links: List[Link]

    # -- prose access -------------------------------------------------------
    def prose_lines(self) -> Iterator[Tuple[int, str]]:
        """Yield (line number, text) for lines that are plain prose."""
        for i, line in enumerate(self.lines):
            if self.in_code[i] or self.hidden[i] or self.structural[i]:
                continue
            yield i + 1, re.sub(r"^[ \t]*(?:>[ \t]?)+", "", line)

    def paragraphs(self) -> List[Paragraph]:
        """Prose grouped into paragraphs; each list item is its own paragraph."""
        out: List[Paragraph] = []
        cur: Optional[Dict] = None

        def flush() -> None:
            nonlocal cur
            if cur and cur["parts"]:
                cleaned = (clean_inline(p).strip() for p in cur["parts"])
                text = re.sub(r"\s+", " ", " ".join(c for c in cleaned if c)).strip()
                if text:
                    out.append(Paragraph(cur["line"], cur["end"], text, cur["kind"]))
            cur = None

        for ln, raw in self.prose_lines():
            s = raw.strip()
            if not s:
                flush()
                continue
            if s.startswith("|") or HR_RE.match(s):
                flush()
                continue
            lm = LIST_RE.match(raw)
            if lm:
                flush()
                body = TASK_RE.sub("", raw[lm.end():])
                cur = {"line": ln, "end": ln, "kind": "list", "parts": [body]}
            else:
                if cur is None:
                    cur = {"line": ln, "end": ln, "kind": "para", "parts": []}
                cur["parts"].append(raw)
                cur["end"] = ln
        flush()
        return out

    def word_count(self) -> int:
        return sum(len(WORD_RE.findall(p.text)) for p in self.paragraphs())

    # -- structure ----------------------------------------------------------
    @property
    def anchors(self) -> List[str]:
        seen: Dict[str, int] = {}
        result: List[str] = []
        for h in self.headings:
            slug = slugify(h.title)
            n = seen.get(slug, 0)
            result.append(slug if n == 0 else f"{slug}-{n}")
            seen[slug] = n + 1
        return result

    def code_blocks(self) -> List[str]:
        """Return each fenced code block (fences included) as one string."""
        blocks: List[str] = []
        cur: List[str] = []
        for i, line in enumerate(self.lines):
            if self.in_code[i]:
                cur.append(line)
            elif cur:
                blocks.append("\n".join(cur))
                cur = []
        if cur:
            blocks.append("\n".join(cur))
        return blocks


def parse(text: str, path: str | Path = "<string>") -> MarkdownDoc:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    n = len(lines)
    in_code = [False] * n
    hidden = [False] * n
    structural = [False] * n
    front: Dict[str, str] = {}
    start = 0

    # YAML front matter
    if lines and lines[0].strip() == "---":
        for j in range(1, min(n, 200)):
            if lines[j].strip() in ("---", "..."):
                for k in range(j + 1):
                    hidden[k] = True
                for k in range(1, j):
                    m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", lines[k])
                    if m:
                        front[m.group(1).lower()] = m.group(2).strip().strip("\"'")
                start = j + 1
                break

    # Fenced code blocks and HTML comments
    fence: Optional[Tuple[str, int]] = None
    in_comment = False
    for i in range(start, n):
        line = lines[i]
        m = FENCE_RE.match(line)
        if fence is None:
            if in_comment:
                hidden[i] = True
                if "-->" in line:
                    in_comment = False
                continue
            if m:
                fence = (m.group(1)[0], len(m.group(1)))
                in_code[i] = True
                continue
            if "<!--" in line:
                hidden[i] = True
                if "-->" not in line.split("<!--", 1)[1]:
                    in_comment = True
        else:
            in_code[i] = True
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= fence[1]
                and line.strip().strip(fence[0]) == ""
            ):
                fence = None

    # Headings (ATX and setext)
    headings: List[Heading] = []
    for i in range(start, n):
        if in_code[i] or hidden[i]:
            continue
        m = HEADING_RE.match(lines[i])
        if m:
            headings.append(Heading(len(m.group(1)), m.group(2).strip(), i + 1, i + 1))
            structural[i] = True
            continue
        line = lines[i]
        if (
            i + 1 < n
            and line.strip()
            and not LIST_RE.match(line)
            and not line.lstrip().startswith(("|", ">", "<"))
            and not in_code[i + 1]
            and not hidden[i + 1]
            and (i == start or not lines[i - 1].strip())
        ):
            m2 = SETEXT_RE.match(lines[i + 1])
            if m2:
                level = 1 if m2.group(1)[0] == "=" else 2
                headings.append(Heading(level, line.strip(), i + 1, i + 2))
                structural[i] = structural[i + 1] = True

    # Reference definitions, then links
    defs: Dict[str, str] = {}
    links: List[Link] = []
    for i in range(start, n):
        if in_code[i] or hidden[i]:
            continue
        m = REF_DEF_RE.match(lines[i])
        if m:
            defs[m.group(1).lower()] = m.group(2)
            links.append(Link(m.group(1), m.group(2), i + 1))
            structural[i] = True

    def blank(m: "re.Match[str]") -> str:
        return " " * len(m.group(0))

    for i in range(start, n):
        if in_code[i] or hidden[i] or REF_DEF_RE.match(lines[i]):
            continue
        masked = INLINE_CODE_RE.sub(blank, lines[i])
        for m in INLINE_LINK_RE.finditer(masked):
            links.append(Link(m.group(2), m.group(3), i + 1, is_image=bool(m.group(1))))
        masked = INLINE_LINK_RE.sub(blank, masked)
        for m in REF_USE_RE.finditer(masked):
            label = (m.group(3) or m.group(2)).lower()
            if label.lower() not in defs and re.search(r"[A-Za-z]", label):
                links.append(
                    Link(m.group(2), "", i + 1, is_image=bool(m.group(1)), undefined_ref=label)
                )
        masked = REF_USE_RE.sub(blank, masked)
        for m in AUTOLINK_RE.finditer(masked):
            links.append(Link(m.group(1), m.group(1), i + 1))
        masked = AUTOLINK_RE.sub(blank, masked)
        for m in BARE_URL_RE.finditer(masked):
            url = m.group(0).rstrip(".,;:!?'")
            links.append(Link(url, url, i + 1))

    return MarkdownDoc(
        path=Path(path),
        text=text,
        lines=lines,
        in_code=in_code,
        hidden=hidden,
        structural=structural,
        front_matter=front,
        headings=headings,
        links=links,
    )


def read_markdown(path: str | Path) -> MarkdownDoc:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8", errors="replace"), p)


SKIP_DIRS = {"node_modules", "venv", ".venv", "__pycache__", "site-packages", "reports", "rewritten"}


def find_markdown_files(paths: Iterable[str | Path]) -> List[Path]:
    """Expand files and directories into a sorted, de-duplicated list of Markdown files."""
    found: Dict[Path, None] = {}
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            raise FileNotFoundError(f"No such file or directory: {p}")
        if p.is_file():
            found[p] = None
            continue
        for f in sorted(list(p.rglob("*.md")) + list(p.rglob("*.markdown"))):
            parts = f.relative_to(p).parts[:-1]
            if any(part.startswith(".") or part in SKIP_DIRS for part in parts):
                continue
            found[f] = None
    return list(found)
