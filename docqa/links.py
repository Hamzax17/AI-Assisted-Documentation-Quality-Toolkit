"""Broken link checker: relative files, heading anchors and external URLs."""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

from .models import Issue
from .reader import MarkdownDoc, read_markdown

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:")
USER_AGENT = "docqa-link-checker/0.1"

RULES = {
    "LNK001": "Relative link target does not exist",
    "LNK002": "Heading anchor does not exist",
    "LNK003": "External URL is broken (404, 410 or DNS failure)",
    "LNK004": "External URL could not be verified (timeout, 403, 429 or 5xx)",
    "LNK005": "Empty or undefined link target",
}

Probe = Callable[[str, float], Tuple[str, str]]


def _request(url: str, method: str, timeout: float) -> int:
    req = urllib.request.Request(
        url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def probe_url(url: str, timeout: float = 8.0, retries: int = 1) -> Tuple[str, str]:
    """Return ("ok" | "broken" | "unverified", detail)."""
    last: Tuple[str, str] = ("unverified", "unknown error")
    for _ in range(retries + 1):
        try:
            try:
                _request(url, "HEAD", timeout)
                return "ok", ""
            except urllib.error.HTTPError:
                pass  # some servers reject HEAD; confirm with GET below
            _request(url, "GET", timeout)
            return "ok", ""
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return "broken", f"HTTP {e.code}"
            if e.code in (401, 403, 429, 999):
                return "unverified", f"HTTP {e.code}"
            last = ("unverified", f"HTTP {e.code}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.gaierror):
                return "broken", "DNS lookup failed"
            last = ("unverified", str(e.reason))
        except (socket.timeout, TimeoutError):
            last = ("unverified", "timed out")
        except Exception as e:  # noqa: BLE001 - never crash a whole run on one URL
            last = ("unverified", str(e))
    return last


def _check_internal(doc: MarkdownDoc, url: str, line: int, root: Optional[Path]) -> List[Issue]:
    f = str(doc.path)
    target, _, anchor = url.partition("#")
    target = unquote(target.split("?", 1)[0])
    anchor = unquote(anchor).lower()

    if target == "":
        if anchor and anchor not in doc.anchors:
            return [Issue("links", "LNK002", "error", f, line,
                          f"Anchor '#{anchor}' not found in this document",
                          "Check the heading text or fix the anchor")]
        return []

    base = (root or doc.path.parent) if target.startswith("/") else doc.path.parent
    path = (base / target.lstrip("/")).resolve()
    if not path.exists():
        return [Issue("links", "LNK001", "error", f, line,
                      f"Broken relative link: '{target}' does not exist",
                      "Fix the path or restore the file")]
    if anchor and path.is_file() and path.suffix.lower() in (".md", ".markdown"):
        if anchor not in read_markdown(path).anchors:
            return [Issue("links", "LNK002", "error", f, line,
                          f"Anchor '#{anchor}' not found in '{target}'",
                          "Check the heading text in the target file")]
    return []


def check_links(
    doc: MarkdownDoc,
    check_external: bool = True,
    timeout: float = 8.0,
    cache: Optional[Dict[str, Tuple[str, str]]] = None,
    probe: Probe = probe_url,
    root: Optional[Path] = None,
) -> List[Issue]:
    f = str(doc.path)
    issues: List[Issue] = []
    cache = {} if cache is None else cache
    external: Dict[str, List[int]] = {}

    for link in doc.links:
        url = link.url.strip()
        if link.undefined_ref:
            issues.append(Issue("links", "LNK005", "error", f, link.line,
                                f"Reference link '[{link.undefined_ref}]' has no definition",
                                "Add a '[label]: url' definition"))
            continue
        if not url:
            issues.append(Issue("links", "LNK005", "error", f, link.line,
                                "Link has an empty target", "Add a URL or remove the link"))
            continue
        if url.lower().startswith(SKIP_SCHEMES):
            continue
        if re.match(r"^https?://", url, re.I):
            external.setdefault(url, []).append(link.line)
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
            continue  # other schemes (ftp:, ssh:, ...)
        issues.extend(_check_internal(doc, url, link.line, root))

    if check_external and external:
        todo = [u for u in external if u not in cache]
        if todo:
            with ThreadPoolExecutor(max_workers=min(8, len(todo))) as pool:
                for u, result in zip(todo, pool.map(lambda u: probe(u, timeout), todo)):
                    cache[u] = result
        for url, line_numbers in external.items():
            status, detail = cache[url]
            if status == "broken":
                rule, sev, msg = "LNK003", "error", f"Broken link: {url} ({detail})"
            elif status == "unverified":
                rule, sev, msg = "LNK004", "warning", f"Could not verify link: {url} ({detail})"
            else:
                continue
            for line in line_numbers:
                issues.append(Issue("links", rule, sev, f, line, msg,
                                    "Update or remove the link" if sev == "error"
                                    else "Open it manually to confirm it still works"))
    return issues
