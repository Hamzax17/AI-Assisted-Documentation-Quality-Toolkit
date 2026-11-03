"""AI-assisted rewriting.

Flagged passages are sent to an LLM, which returns suggested rewrites. The
toolkit never edits your files: suggestions go into the report for a human to
accept or reject. Providers: ``gemini``, ``anthropic`` (both via plain HTTPS,
no SDK needed) and ``mock`` (offline, rule-based; for demos and tests).

Environment variables:
    GEMINI_API_KEY / ANTHROPIC_API_KEY   credentials
    DOCQ_PROVIDER                        gemini | anthropic | mock
    DOCQ_MODEL                           override the default model name
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from .models import Issue
from .reader import INLINE_CODE_RE
from . import style as style_mod

REWRITABLE_CHECKS = {"style", "terminology"}
REWRITABLE_RULES = {
    "long-sentence", "passive-voice", "wordy-phrase", "weasel-word",
    "repeated-word", "inconsistent-term",
}
DEFAULT_MODELS = {"gemini": "gemini-2.5-flash", "anthropic": "claude-sonnet-5-5"}

PROMPT = """You are a careful technical editor. Rewrite each Markdown passage below so that the listed problems are fixed.

Rules:
- Preserve the meaning. Do not add facts, examples or claims.
- Keep Markdown syntax, inline code, link text and URLs exactly as they are.
- Change only what is needed to fix the problems; leave the rest of the passage untouched.
- Prefer active voice, short sentences and plain words.
- Use these preferred terms where relevant: {terms}

Return ONLY a JSON array of objects {{"id": <int>, "rewrite": "<string>"}}, one per item, in the same order.

Items:
{items}
"""


class ProviderError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
def _post_json(url: str, headers: dict, body: dict, timeout: float = 90.0, retries: int = 2) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(2 ** attempt * 2)
                continue
            detail = e.read().decode(errors="replace")[:300]
            raise ProviderError(f"HTTP {e.code} from provider: {detail}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"Could not reach provider: {e.reason}") from e
    raise ProviderError("provider request failed")


def _parse_json_array(text: str) -> list:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("["), text.rfind("]")
        if a == -1 or b <= a:
            raise ProviderError("Model did not return a JSON array.")
        try:
            data = json.loads(text[a : b + 1])
        except json.JSONDecodeError as e:
            raise ProviderError("Model returned malformed JSON.") from e
    if not isinstance(data, list):
        raise ProviderError("Model did not return a JSON array.")
    return data


class LLMProvider:
    name = "base"

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.environ.get("DOCQ_MODEL") or DEFAULT_MODELS.get(self.name, "")

    def _complete(self, prompt: str) -> str:  # pragma: no cover - network
        raise NotImplementedError

    def rewrite(self, items: List[dict], terms: List[str]) -> Dict[int, str]:
        prompt = PROMPT.format(terms=", ".join(terms) or "(none)", items=json.dumps(items, indent=1))
        out: Dict[int, str] = {}
        for entry in _parse_json_array(self._complete(prompt)):
            if isinstance(entry, dict) and isinstance(entry.get("id"), int) and isinstance(entry.get("rewrite"), str):
                out[entry["id"]] = entry["rewrite"]
        return out


class GeminiProvider(LLMProvider):  # pragma: no cover - network
    name = "gemini"

    def _complete(self, prompt: str) -> str:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        data = _post_json(url, {"x-goog-api-key": key}, body)
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Gemini response: {str(data)[:200]}") from e


class AnthropicProvider(LLMProvider):  # pragma: no cover - network
    name = "anthropic"

    def _complete(self, prompt: str) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set.")
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        data = _post_json("https://api.anthropic.com/v1/messages", headers, body)
        try:
            return "".join(b.get("text", "") for b in data["content"])
        except (KeyError, TypeError) as e:
            raise ProviderError(f"Unexpected Anthropic response: {str(data)[:200]}") from e


class MockProvider(LLMProvider):
    """Offline, deterministic: fixes wordy phrases, intensifiers and glossary terms only."""

    name = "mock"
    _PROTECT = re.compile(r"(`[^`]*`|\]\([^)]*\)|https?://\S+)")

    def __init__(self, model: Optional[str] = None, glossary: Optional[dict] = None):
        super().__init__(model or "mock")
        self.glossary = glossary or {"terms": []}

    def _outside_protected(self, text: str, fn) -> str:
        parts = self._PROTECT.split(text)
        return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))

    def rewrite(self, items: List[dict], terms: List[str]) -> Dict[int, str]:
        out: Dict[int, str] = {}
        for it in items:
            def fix(seg: str) -> str:
                for phrase, repl in style_mod.DEFAULTS["wordy_phrases"].items():
                    seg = re.sub(rf"\b{re.escape(phrase)}\b", repl, seg, flags=re.I)
                for w in style_mod.DEFAULTS["weasel_words"]:
                    seg = re.sub(rf"\b{w}\s+", "", seg, flags=re.I)
                for t in self.glossary["terms"]:
                    for bad in t.get("avoid", []):
                        cs = t.get("case_sensitive", bad.lower() == t["preferred"].lower())
                        seg = re.sub(rf"(?<![\w./@-]){re.escape(bad)}(?![\w-]|\.\w)", t["preferred"],
                                     seg, flags=0 if cs else re.I)
                return seg
            out[it["id"]] = self._outside_protected(it["passage"], fix)
        return out


def get_provider(name: Optional[str] = None, model: Optional[str] = None, glossary: Optional[dict] = None) -> LLMProvider:
    name = (name or os.environ.get("DOCQ_PROVIDER") or "auto").lower()
    if name == "auto":
        if os.environ.get("GEMINI_API_KEY"):
            name = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            name = "anthropic"
        else:
            raise ProviderError(
                "No LLM credentials found. Set GEMINI_API_KEY or ANTHROPIC_API_KEY, "
                "or use --provider mock for an offline demo."
            )
    if name == "gemini":
        return GeminiProvider(model)
    if name == "anthropic":
        return AnthropicProvider(model)
    if name == "mock":
        return MockProvider(model, glossary)
    raise ProviderError(f"Unknown provider '{name}'. Choose gemini, anthropic or mock.")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def _protected_tokens(text: str) -> List[str]:
    toks = [m.group(0) for m in INLINE_CODE_RE.finditer(text)]
    toks += re.findall(r"\]\(([^)\s]+)", text)
    return toks


def build_rewrites(
    issues: List[Issue],
    provider: LLMProvider,
    terms: List[str],
    max_items: int = 20,
    batch_size: int = 10,
) -> List[dict]:
    """Group fixable issues by passage and ask the provider for rewrites."""
    groups: Dict[tuple, dict] = {}
    for i in issues:
        if i.check in REWRITABLE_CHECKS and i.rule in REWRITABLE_RULES and i.context:
            g = groups.setdefault((i.file, i.context), {"file": i.file, "line": i.line, "passage": i.context, "problems": []})
            g["line"] = min(g["line"], i.line)
            g["problems"].append(f"{i.rule}: {i.message}")
    ordered = sorted(groups.values(), key=lambda g: (-len(g["problems"]), g["file"], g["line"]))[:max_items]
    ordered.sort(key=lambda g: (g["file"], g["line"]))

    results: List[dict] = []
    for start in range(0, len(ordered), batch_size):
        chunk = ordered[start : start + batch_size]
        payload = [{"id": n, "passage": g["passage"], "problems": g["problems"]} for n, g in enumerate(chunk)]
        answers = provider.rewrite(payload, terms)
        for n, g in enumerate(chunk):
            new = answers.get(n, "").strip()
            if not new or new == g["passage"].strip():
                continue
            missing = [t for t in _protected_tokens(g["passage"]) if t not in new]
            results.append({
                "file": g["file"],
                "line": g["line"],
                "problems": g["problems"],
                "original": g["passage"],
                "rewrite": new,
                "model": f"{provider.name}:{provider.model}",
                "warnings": [f"Rewrite dropped or changed protected text: {t}" for t in missing],
            })
    return results
