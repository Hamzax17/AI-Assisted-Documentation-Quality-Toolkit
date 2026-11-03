"""AI-assisted rewriting through an LLM API.

Providers use only the standard library (urllib), so the toolkit stays
dependency-free:

    gemini     GEMINI_API_KEY (or GOOGLE_API_KEY)   default model gemini-2.0-flash
    anthropic  ANTHROPIC_API_KEY                    default model claude-sonnet-4-5
    openai     OPENAI_API_KEY (+ OPENAI_BASE_URL)   default model gpt-4o-mini
    mock       no key; offline, applies the simple rule-based fixes (for demos and tests)

Safety: a rewrite is rejected if it drops a link, URL or inline code span from
the original, or changes the length wildly. Rejected rewrites are reported,
never silently applied.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Protocol

from .models import Issue
from .reader import (BARE_URL_RE, INLINE_CODE_RE, INLINE_LINK_RE, MarkdownDoc,
                     Paragraph)
from .style import WORDY

SYSTEM_PROMPT = (
    "You are a technical documentation editor. Rewrite the given Markdown paragraph so it "
    "fixes the listed issues while keeping the meaning exactly the same.\n"
    "Rules:\n"
    "- Keep every Markdown link, URL, inline code span and product name unchanged.\n"
    "- Do not add facts, examples or claims that are not in the original.\n"
    "- Use active voice, short sentences and plain words.\n"
    "- Keep it as one paragraph (or one list item) with the same Markdown structure.\n"
    "- Return ONLY the rewritten text. No preamble, no quotes, no explanation."
)

DEFAULT_MODELS = {"gemini": "gemini-2.0-flash", "anthropic": "claude-sonnet-4-5",
                  "openai": "gpt-4o-mini", "mock": "rule-based"}


class LLMError(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...


def _post(url: str, headers: Dict[str, str], body: Dict, timeout: float) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise LLMError(f"HTTP {e.code} from {url.split('?')[0]}: {detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Network error: {e.reason}") from e


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: Optional[str] = None, timeout: float = 60) -> None:
        self.key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.key:
            raise LLMError("Set GEMINI_API_KEY (or GOOGLE_API_KEY) to use the gemini provider")
        self.model, self.timeout = model or DEFAULT_MODELS["gemini"], timeout

    def complete(self, system: str, user: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        data = _post(url, {"x-goog-api-key": self.key}, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2},
        }, self.timeout)
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Gemini response: {str(data)[:200]}") from e


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: Optional[str] = None, timeout: float = 60) -> None:
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise LLMError("Set ANTHROPIC_API_KEY to use the anthropic provider")
        self.model, self.timeout = model or DEFAULT_MODELS["anthropic"], timeout

    def complete(self, system: str, user: str) -> str:
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                     {"model": self.model, "max_tokens": 1024, "temperature": 0.2,
                      "system": system, "messages": [{"role": "user", "content": user}]},
                     self.timeout)
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise LLMError(f"Unexpected Anthropic response: {str(data)[:200]}") from e


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: Optional[str] = None, timeout: float = 60) -> None:
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise LLMError("Set OPENAI_API_KEY to use the openai provider")
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model, self.timeout = model or DEFAULT_MODELS["openai"], timeout

    def complete(self, system: str, user: str) -> str:
        data = _post(f"{self.base}/chat/completions", {"Authorization": f"Bearer {self.key}"},
                     {"model": self.model, "temperature": 0.2,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]}, self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected OpenAI response: {str(data)[:200]}") from e


class MockProvider:
    """Offline provider: applies the wordy-phrase and filler fixes with no API call."""

    name = "mock"
    model = DEFAULT_MODELS["mock"]

    def complete(self, system: str, user: str) -> str:
        m = re.search(r"<paragraph>\n(.*?)\n</paragraph>", user, re.S)
        text = m.group(1) if m else user
        for bad, good in sorted(WORDY.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(r"\b" + re.escape(bad) + r"\b",
                          lambda mm, g=good: g.capitalize() if mm.group(0)[0].isupper() else g,
                          text, flags=re.I)
        text = re.sub(r"\b(?:simply|just|easily|obviously|basically|actually|really|very)\s+",
                      "", text, flags=re.I)
        return re.sub(r" {2,}", " ", text).strip()


PROVIDERS = {"gemini": GeminiProvider, "anthropic": AnthropicProvider,
             "openai": OpenAIProvider, "mock": MockProvider}


def make_provider(name: str, model: Optional[str] = None) -> Provider:
    if name not in PROVIDERS:
        raise LLMError(f"Unknown provider '{name}'. Choose from: {', '.join(PROVIDERS)}")
    return PROVIDERS[name]() if name == "mock" else PROVIDERS[name](model)


@dataclass
class Rewrite:
    file: str
    line: int
    original: str
    rewritten: str
    issues: List[str]
    accepted: bool
    reason: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def _protected_tokens(text: str) -> List[str]:
    tokens = [m.group(0) for m in INLINE_CODE_RE.finditer(text)]
    tokens += [m.group(3) for m in INLINE_LINK_RE.finditer(text)]
    tokens += [m.group(0).rstrip(".,;:!?'") for m in BARE_URL_RE.finditer(text)]
    return [t for t in tokens if t]


def validate_rewrite(original: str, rewritten: str) -> str:
    """Return an empty string if the rewrite is safe, otherwise the rejection reason."""
    if not rewritten.strip():
        return "empty response"
    if rewritten.strip() == original.strip():
        return "no change"
    missing = [t for t in _protected_tokens(original) if t not in rewritten]
    if missing:
        return "dropped protected content: " + ", ".join(missing[:3])
    ratio = len(rewritten) / max(len(original), 1)
    if ratio < 0.4 or ratio > 1.6:
        return f"length changed too much ({ratio:.0%} of original)"
    return ""


def _clean_response(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:markdown|md)?\n|\n```$", "", t).strip()
    return t[1:-1].strip() if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t


def _paragraph_source(doc: MarkdownDoc, p: Paragraph) -> str:
    """Original Markdown text of a paragraph, with list markers and quote prefixes removed."""
    from .reader import LIST_RE, TASK_RE
    out = []
    for raw in doc.lines[p.line - 1:p.end]:
        s = re.sub(r"^[ \t]*(?:>[ \t]?)+", "", raw)
        s = TASK_RE.sub("", LIST_RE.sub("", s, count=1)).strip() if p.kind == "list" and not out else s.strip()
        out.append(s)
    return " ".join(out)


def rewrite_issues(doc: MarkdownDoc, issues: List[Issue], provider: Provider,
                   max_paragraphs: int = 10,
                   styles: Optional[List[str]] = None) -> List[Rewrite]:
    """Rewrite the paragraphs that carry style or terminology findings."""
    by_para: Dict[int, List[Issue]] = {}
    paragraphs = doc.paragraphs()
    for iss in issues:
        if iss.check not in ("style", "terminology") or iss.rule in ("STY013", "STY014", "STY015",
                                                                       "STY016", "TRM002"):
            continue
        for p in paragraphs:
            if p.line <= iss.line <= p.end:
                by_para.setdefault(p.line, []).append(iss)
                break

    ranked = sorted(by_para.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:max_paragraphs]
    results: List[Rewrite] = []
    for line, group in sorted(ranked):
        para = next(p for p in paragraphs if p.line == line)
        original = _paragraph_source(doc, para)
        bullets = "\n".join(f"- {i.message}" + (f" ({i.suggestion})" if i.suggestion else "")
                            for i in group)
        user = f"Issues to fix:\n{bullets}\n\n<paragraph>\n{original}\n</paragraph>"
        try:
            rewritten = _clean_response(provider.complete(SYSTEM_PROMPT, user))
        except LLMError as e:
            results.append(Rewrite(str(doc.path), line, original, "", [i.rule for i in group],
                                   False, f"LLM error: {e}"))
            if "HTTP 401" in str(e) or "HTTP 403" in str(e) or "HTTP 400" in str(e):
                break  # bad key or model: stop instead of failing every paragraph
            continue
        reason = validate_rewrite(original, rewritten)
        results.append(Rewrite(str(doc.path), line, original, rewritten,
                               sorted({i.rule for i in group}), not reason, reason))
    return results
