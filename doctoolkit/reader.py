"""Markdown file reader.

A small, dependency-free parser that extracts what the checks need:
headings (with GitHub-style anchors), links, code blocks, front matter and
prose paragraphs. Code blocks, front matter and HTML comments are never
treated as prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([^\s`]*)")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
_LINK_TEXT = r"((?:[^\[\]]|\[[^\]]*\])*)"
INLINE_LINK_RE = re.compile(
    r"(!?)\[" + _LINK_TEXT + r"\]\(\s*<?([^)\s>]*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
REF_USE_RE = re.compile(r"(?<![\]!\\])\[([^\[\]]+)\]\[([^\[\]]*)\]")
REF_DEF_RE = re.compile(r"^\s{0,3}\[([^\]\^][^\]]*)\]:\s*<?(\S+?)>?(?:\s+[\"'(].*)?\s*$")
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
BARE_URL_RE = re.compile(r"(?<![\w(<\[\"'=/])https?://[^\s<>()\[\]\"']+")
HTML_ATTR_RE = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.I)
ANCHOR_ATTR_RE = re.compile(r"""\b(?:id|name)\s*=\s*["']([^"']+)["']""", re.I)
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+(?:\[[ xX]\]\s+)?")
QUOTE_RE = re.compile(r"^\s*(?:>\s?)+")
HR_RE = re.compile(r"^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,}|=+)\s*$")
TAG_ONLY_RE = re.compile(r"^\s*</?[A-Za-z][^>]*>\s*$")
EMPHASIS_RE = re.compile(r"(\*\*|__|\*|(?<!\w)_|_(?!\w))")

CODE_PLACEHOLDER = "§"  # stands in for inline code / URLs in cleaned text


@dataclass
class Heading:
    level: int
    text: str
    line: int
    slug: str


@dataclass
class Link:
    text: str
    target: str
    line: int
    kind: str = "inline"  # inline | ref_def | ref_use | autolink | bare | html
    is_image: bool = False


@dataclass
class CodeBlock:
    lang: str
    line: int
    closed: bool = True


@dataclass
class Paragraph:
    start: int
    end: int
    raw: str
    text: str
    offsets: List[Tuple[int, int]] = field(default_factory=list)  # (char offset, line no)

    def line_at(self, offset: int) -> int:
        line = self.start
        for off, ln in self.offsets:
            if off <= offset:
                line = ln
            else:
                break
        return line


def slugify(text: str) -> str:
    """GitHub-style heading anchor."""
    s = clean_inline(text, keep_code_text=True).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s", "-", s)


def clean_inline(text: str, keep_code_text: bool = False) -> str:
    """Strip Markdown inline syntax so only human-readable prose remains."""
    if keep_code_text:
        text = INLINE_CODE_RE.sub(lambda m: m.group(2), text)
    else:
        text = INLINE_CODE_RE.sub(CODE_PLACEHOLDER, text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = AUTOLINK_RE.sub(CODE_PLACEHOLDER, text)
    text = re.sub(r"https?://[^\s<>)]+", CODE_PLACEHOLDER, text)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)
    text = EMPHASIS_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _blank_code(line: str) -> str:
    return INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)


@dataclass
class Doc:
    path: Path
    name: str
    lines: List[str]  # raw lines
    view: List[str]  # lines with HTML comments removed
    prose: List[bool]  # False for code, front matter, comments
    headings: List[Heading]
    links: List[Link]
    code_blocks: List[CodeBlock]
    ref_defs: dict
    meta: dict
    anchors: set

    # ---- derived views -------------------------------------------------
    def paragraphs(self) -> List[Paragraph]:
        """Prose paragraphs / list items (no headings, tables or code)."""
        out: List[Paragraph] = []
        cur: Optional[Paragraph] = None
        heading_lines = {h.line for h in self.headings}
        for i, line in enumerate(self.view):
            ln = i + 1
            if (
                not self.prose[i]
                or not line.strip()
                or ln in heading_lines
                or line.lstrip().startswith("|")
                or HR_RE.match(line)
                or TAG_ONLY_RE.match(line)
                or REF_DEF_RE.match(line)
            ):
                if cur:
                    out.append(cur)
                    cur = None
                continue
            s = QUOTE_RE.sub("", line)
            lm = LIST_RE.match(s)
            if lm:
                if cur:
                    out.append(cur)
                    cur = None
                s = s[lm.end():]
            cleaned = clean_inline(s.strip())
            if cur is None:
                cur = Paragraph(start=ln, end=ln, raw="", text="")
            cur.offsets.append((len(cur.text) + (1 if cur.text else 0), ln))
            cur.text += (" " if cur.text else "") + cleaned
            cur.end = ln
        if cur:
            out.append(cur)
        for p in out:
            p.raw = "\n".join(self.lines[p.start - 1 : p.end])
        return out

    def clean_lines(self) -> Iterator[Tuple[int, str, str]]:
        """Yield (line no, cleaned text, raw line) for every prose line,
        headings and table cells included."""
        for i, line in enumerate(self.view):
            if not self.prose[i] or not line.strip():
                continue
            if HR_RE.match(line) or TAG_ONLY_RE.match(line) or REF_DEF_RE.match(line):
                continue
            s = QUOTE_RE.sub("", line)
            s = LIST_RE.sub("", s, count=1)
            s = re.sub(r"^\s*#{1,6}\s+", "", s)
            s = s.replace("|", " ")
            yield i + 1, clean_inline(s), self.lines[i]

    @property
    def words(self) -> int:
        return sum(len(re.findall(r"\w+", t)) for _, t, _ in self.clean_lines())


def _closes(line: str, fence: Tuple[str, int]) -> bool:
    s = line.strip()
    return bool(s) and set(s) == {fence[0]} and len(s) >= fence[1]


def _extract_links(scan: str, ln: int, out: List[Link]) -> None:
    for m in INLINE_LINK_RE.finditer(scan):
        out.append(Link(m.group(2), m.group(3), ln, "inline", bool(m.group(1))))
        for inner in INLINE_LINK_RE.finditer(m.group(2)):
            out.append(Link(inner.group(2), inner.group(3), ln, "inline", bool(inner.group(1))))
    rest = INLINE_LINK_RE.sub(" ", scan)
    for m in REF_USE_RE.finditer(rest):
        label = (m.group(2) or m.group(1)).strip()
        out.append(Link(m.group(1), label, ln, "ref_use"))
    for m in AUTOLINK_RE.finditer(rest):
        out.append(Link(m.group(1), m.group(1), ln, "autolink"))
    for m in HTML_ATTR_RE.finditer(rest):
        out.append(Link("", m.group(1), ln, "html"))
    plain = AUTOLINK_RE.sub(" ", rest)
    for m in BARE_URL_RE.finditer(plain):
        url = m.group(0).rstrip(".,;:!?*_")
        out.append(Link(url, url, ln, "bare"))


def parse(text: str, path: Path | str = "<memory>", name: Optional[str] = None) -> Doc:
    path = Path(path)
    lines = text.splitlines()
    n = len(lines)
    view = list(lines)
    prose = [False] * n
    meta: dict = {}
    start = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, n):
            if lines[j].strip() in ("---", "..."):
                for fm in lines[1:j]:
                    m = re.match(r"^([\w-]+)\s*:\s*(.*)$", fm)
                    if m:
                        meta[m.group(1).lower()] = m.group(2).strip().strip("'\"")
                start = j + 1
                break

    headings: List[Heading] = []
    links: List[Link] = []
    code_blocks: List[CodeBlock] = []
    ref_defs: dict = {}
    anchors: set = set()
    seen_slugs: dict = {}
    fence: Optional[Tuple[str, int]] = None
    in_comment = False

    for idx in range(start, n):
        line = lines[idx]
        ln = idx + 1
        if fence:
            if _closes(line, fence):
                fence = None
                code_blocks[-1].closed = True
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1]
            else:
                view[idx] = ""
                continue
        line = re.sub(r"<!--.*?-->", "", line)
        if "<!--" in line:
            line = line.split("<!--", 1)[0]
            in_comment = True
        view[idx] = line
        fm = FENCE_RE.match(line)
        if fm:
            fence = (fm.group(1)[0], len(fm.group(1)))
            code_blocks.append(CodeBlock(fm.group(2), ln, closed=False))
            continue
        prose[idx] = True
        for am in ANCHOR_ATTR_RE.finditer(line):
            anchors.add(am.group(1).lower())

        hm = HEADING_RE.match(line)
        if hm:
            slug = slugify(hm.group(2))
            count = seen_slugs.get(slug, 0)
            seen_slugs[slug] = count + 1
            final = slug if count == 0 else f"{slug}-{count}"
            anchors.add(final)
            headings.append(Heading(len(hm.group(1)), hm.group(2).strip(), ln, final))

        scan = _blank_code(line)
        dm = REF_DEF_RE.match(scan)
        if dm:
            ref_defs[dm.group(1).strip().lower()] = ln
            links.append(Link(dm.group(1), dm.group(2), ln, "ref_def"))
            continue
        _extract_links(scan, ln, links)

    return Doc(
        path=path,
        name=name or str(path),
        lines=lines,
        view=view,
        prose=prose,
        headings=headings,
        links=links,
        code_blocks=code_blocks,
        ref_defs=ref_defs,
        meta=meta,
        anchors=anchors,
    )


def load(path: Path | str, root: Optional[Path | str] = None) -> Doc:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        name = p.resolve().relative_to(Path(root).resolve()).as_posix() if root else str(p)
    except ValueError:
        name = str(p)
    return parse(text, p, name)
