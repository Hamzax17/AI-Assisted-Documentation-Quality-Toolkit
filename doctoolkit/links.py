"""Broken link checker: relative files, in-page / cross-file anchors, reference
links and (optionally) external HTTP(S) URLs."""
from __future__ import annotations

import difflib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote

from .models import Issue
from .reader import Doc, load

SKIP_PREFIXES = ("mailto:", "tel:", "data:", "javascript:", "sms:", "ftp:", "//")
MD_SUFFIXES = {".md", ".markdown"}
USER_AGENT = "doc-quality-toolkit/0.1 (link-checker)"


def is_external(target: str) -> bool:
    return target.lower().startswith(("http://", "https://"))


class ExternalChecker:
    """Checks external URLs once each, concurrently, with a shared cache."""

    def __init__(self, timeout: float = 8.0, workers: int = 8):
        self.timeout = timeout
        self.workers = workers
        self.cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}

    def _request(self, url: str, method: str):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status

    def _fetch(self, url: str) -> Tuple[Optional[int], Optional[str]]:
        try:
            return self._request(url, "HEAD"), None
        except urllib.error.HTTPError as e:
            if e.code < 400:
                return e.code, None
            # Many servers reject HEAD; retry once with GET.
            try:
                return self._request(url, "GET"), None
            except urllib.error.HTTPError as e2:
                return e2.code, None
            except Exception as e2:  # noqa: BLE001
                return None, str(e2)[:120]
        except Exception as e:  # noqa: BLE001
            return None, str(e)[:120]

    def prefetch(self, urls: Iterable[str]) -> None:
        todo = sorted({u for u in urls if u not in self.cache})
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for url, result in zip(todo, pool.map(self._fetch, todo)):
                self.cache[url] = result

    def check(self, url: str) -> Tuple[Optional[int], Optional[str]]:
        if url not in self.cache:
            self.cache[url] = self._fetch(url)
        return self.cache[url]


def _suggest(name: str, candidates: Iterable[str]) -> Optional[str]:
    match = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return match[0] if match else None


def check_links(
    doc: Doc,
    root: Path,
    external: Optional[ExternalChecker] = None,
    doc_cache: Optional[Dict[Path, Doc]] = None,
) -> List[Issue]:
    issues: List[Issue] = []
    cache = doc_cache if doc_cache is not None else {}
    root = Path(root).resolve()

    def add(rule, sev, line, msg, sugg=None):
        issues.append(Issue("links", rule, sev, doc.name, line, msg, sugg))

    for link in doc.links:
        t = link.target.strip()
        if link.kind == "ref_use":
            if t.lower() not in doc.ref_defs:
                add("undefined-reference", "error", link.line, f"Reference link [{t}] has no definition.")
            continue
        if not t:
            add("empty-link", "error", link.line, f"Link \"{link.text}\" has an empty target.")
            continue
        if t == "#" or t.lower().startswith(SKIP_PREFIXES):
            continue

        if is_external(t):
            if external is None:
                continue
            code, err = external.check(t)
            if err:
                add("unreachable-link", "warning", link.line, f"Could not reach {t} ({err}).")
            elif code is not None and code >= 400:
                if code in (401, 403, 429):
                    add("link-access-limited", "warning", link.line,
                        f"{t} returned HTTP {code}; it may block automated checks.")
                elif code >= 500:
                    add("link-server-error", "warning", link.line, f"{t} returned HTTP {code}.")
                else:
                    add("broken-link", "error", link.line, f"{t} returned HTTP {code}.")
            continue

        path_part, _, frag = t.partition("#")
        path_part = unquote(path_part.split("?", 1)[0])
        if not path_part:
            target_doc: Optional[Doc] = doc
            target_path = doc.path
        else:
            base = root if path_part.startswith("/") else doc.path.resolve().parent
            target_path = (base / path_part.lstrip("/")).resolve()
            if not target_path.exists():
                siblings = [p.name for p in target_path.parent.glob("*")] if target_path.parent.is_dir() else []
                best = _suggest(target_path.name, siblings)
                add("broken-link", "error", link.line,
                    f"Link target not found: {t}",
                    f"Did you mean \"{best}\"?" if best else None)
                continue
            target_doc = None
            if frag and target_path.suffix.lower() in MD_SUFFIXES and target_path.is_file():
                target_doc = cache.get(target_path)
                if target_doc is None:
                    target_doc = load(target_path, root)
                    cache[target_path] = target_doc
        if frag and target_doc is not None:
            if frag.lower() not in target_doc.anchors and not frag.lower().startswith("l"):
                best = _suggest(frag.lower(), target_doc.anchors)
                where = "this page" if target_doc is doc else target_path.name
                add("broken-anchor", "error", link.line,
                    f"Anchor #{frag} not found in {where}.",
                    f"Did you mean #{best}?" if best else None)
    return issues
