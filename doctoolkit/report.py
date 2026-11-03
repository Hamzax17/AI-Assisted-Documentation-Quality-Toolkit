"""Quality report generation (JSON and Markdown)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .models import SEVERITIES, SEVERITY_RANK, Issue

WEIGHTS = {"error": 5.0, "warning": 2.0, "info": 0.5}


def score(issues: List[Issue], words: int) -> float:
    """100 minus a penalty scaled to document length (300 words = reference size)."""
    penalty = sum(WEIGHTS[i.severity] for i in issues)
    return max(0.0, round(100 - penalty * 300 / max(words, 300), 1))


def build_report(
    results: List[dict],
    terminology_usage: Optional[Dict[str, dict]] = None,
    rewrites: Optional[List[dict]] = None,
    options: Optional[dict] = None,
) -> dict:
    """results: [{"file", "words", "issues": [Issue]}]"""
    files = []
    all_issues: List[Issue] = []
    for r in sorted(results, key=lambda r: r["file"]):
        issues = sorted(r["issues"], key=lambda i: (i.line, SEVERITY_RANK[i.severity], i.rule))
        all_issues.extend(issues)
        files.append({
            "file": r["file"],
            "words": r["words"],
            "score": score(issues, r["words"]),
            "counts": {s: sum(1 for i in issues if i.severity == s) for s in SEVERITIES},
            "issues": [i.to_dict() for i in issues],
        })
    scores = [f["score"] for f in files]
    usage = {
        k: v for k, v in (terminology_usage or {}).items() if v["preferred"] or v["variants"]
    }
    return {
        "tool": "doc-quality-toolkit",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "options": options or {},
        "summary": {
            "files": len(files),
            "words": sum(f["words"] for f in files),
            "issues": len(all_issues),
            "by_severity": {s: sum(1 for i in all_issues if i.severity == s) for s in SEVERITIES},
            "by_check": dict(Counter(i.check for i in all_issues)),
            "by_rule": dict(Counter(i.rule for i in all_issues).most_common()),
            "average_score": round(sum(scores) / len(scores), 1) if scores else 100.0,
        },
        "files": files,
        "terminology_usage": usage,
        "rewrites": rewrites or [],
    }


def write_json(report: dict, path: Path | str) -> None:
    Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _fence(text: str) -> str:
    n = 3
    while "`" * n in text:
        n += 1
    return "`" * n


def to_markdown(report: dict) -> str:
    s = report["summary"]
    out = [
        "# Documentation Quality Report",
        "",
        f"_Generated {report['generated_at']} by {report['tool']} v{report['version']}_",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Files checked | {s['files']} |",
        f"| Words | {s['words']} |",
        f"| Average score | **{s['average_score']}** / 100 |",
        f"| Errors | {s['by_severity']['error']} |",
        f"| Warnings | {s['by_severity']['warning']} |",
        f"| Info | {s['by_severity']['info']} |",
        "",
    ]
    if s["by_rule"]:
        out += ["**Most common rules:** " + ", ".join(f"`{k}` ({v})" for k, v in list(s["by_rule"].items())[:8]), ""]

    out += ["## Files", "", "| File | Score | Errors | Warnings | Info |", "| --- | ---: | ---: | ---: | ---: |"]
    for f in report["files"]:
        c = f["counts"]
        out.append(f"| `{f['file']}` | {f['score']} | {c['error']} | {c['warning']} | {c['info']} |")
    out.append("")

    out += ["## Issues", ""]
    any_issue = False
    for f in report["files"]:
        if not f["issues"]:
            continue
        any_issue = True
        out += [f"### `{f['file']}` (score {f['score']})", "", "| Line | Severity | Rule | Message |", "| ---: | --- | --- | --- |"]
        for i in f["issues"]:
            msg = _esc(i["message"])
            if i.get("suggestion"):
                msg += f" _{_esc(i['suggestion'])}_"
            out.append(f"| {i['line']} | {i['severity']} | `{i['rule']}` | {msg} |")
        out.append("")
    if not any_issue:
        out += ["No issues found. 🎉", ""]

    usage = report.get("terminology_usage") or {}
    mixed = {k: v for k, v in usage.items() if v["variants"]}
    if mixed:
        out += ["## Terminology consistency", "", "| Preferred term | Uses | Variants found |", "| --- | ---: | --- |"]
        for k, v in mixed.items():
            variants = ", ".join(f"\"{b}\" ×{n}" for b, n in v["variants"].items())
            out.append(f"| {k} | {v['preferred']} | {variants} |")
        out.append("")

    if report.get("rewrites"):
        out += ["## AI-assisted rewrite suggestions", "",
                "_Suggestions only; review each one before applying. Files are never modified automatically._", ""]
        for r in report["rewrites"]:
            out += [f"### `{r['file']}` line {r['line']}", "",
                    "**Problems:** " + "; ".join(_esc(p) for p in r["problems"]), ""]
            for label, key in (("Original", "original"), ("Suggested", "rewrite")):
                fence = _fence(r[key])
                out += [f"**{label}**", "", f"{fence}markdown", r[key], fence, ""]
            for w in r.get("warnings", []):
                out += [f"> ⚠️ {w}", ""]
    return "\n".join(out).rstrip() + "\n"
