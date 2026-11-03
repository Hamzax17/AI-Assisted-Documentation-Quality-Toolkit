"""Quality report generation: JSON and Markdown."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .models import SEVERITY_ORDER, FileResult, Issue, quality_score
from .rewriter import Rewrite

CHECKS = ["links", "style", "terminology", "sections"]


def grade(score: int) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def build_report(results: List[FileResult], rewrites: Optional[List[Rewrite]] = None,
                 meta: Optional[Dict] = None) -> Dict:
    all_issues: List[Issue] = [i for r in results for i in r.issues]
    total_words = sum(r.words for r in results)
    overall = round(sum(r.score for r in results) / len(results)) if results else 100
    by_rule = Counter(i.rule for i in all_issues)
    return {
        "tool": "docqa",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": meta or {},
        "summary": {
            "files": len(results),
            "words": total_words,
            "score": overall,
            "grade": grade(overall),
            "issues": len(all_issues),
            "by_severity": {s: sum(1 for i in all_issues if i.severity == s) for s in SEVERITY_ORDER},
            "by_check": {c: sum(1 for i in all_issues if i.check == c) for c in CHECKS},
            "top_rules": by_rule.most_common(5),
        },
        "files": [{
            "file": r.file, "words": r.words, "score": r.score, "grade": grade(r.score),
            "counts": {s: r.count(s) for s in SEVERITY_ORDER},
            "issues": [i.to_dict() for i in sorted(
                r.issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.line, i.rule))],
        } for r in results],
        "rewrites": [w.to_dict() for w in (rewrites or [])],
    }


def to_json(report: Dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def _esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def to_markdown(report: Dict) -> str:
    s = report["summary"]
    out: List[str] = ["# Documentation Quality Report", ""]
    out.append(f"Generated {report['generated_at']} by docqa {report['version']}.")
    out += ["", "## Summary", "",
            f"**Overall score: {s['score']}/100 (grade {s['grade']})**", "",
            "| Files | Words | Errors | Warnings | Info |", "|---:|---:|---:|---:|---:|",
            f"| {s['files']} | {s['words']} | {s['by_severity']['error']} | "
            f"{s['by_severity']['warning']} | {s['by_severity']['info']} |", ""]
    out += ["| Check | Issues |", "|---|---:|"]
    out += [f"| {c} | {n} |" for c, n in s["by_check"].items()]
    if s["top_rules"]:
        out += ["", "Most common rules: " + ", ".join(f"`{r}` x{n}" for r, n in s["top_rules"]) + "."]

    out += ["", "## Files", "", "| File | Score | Grade | Errors | Warnings | Info |",
            "|---|---:|:---:|---:|---:|---:|"]
    for f in report["files"]:
        c = f["counts"]
        out.append(f"| `{f['file']}` | {f['score']} | {f['grade']} | {c['error']} | {c['warning']} | {c['info']} |")

    out += ["", "## Findings"]
    for f in report["files"]:
        out += ["", f"### `{f['file']}` ({f['score']}/100)", ""]
        if not f["issues"]:
            out.append("No issues found.")
            continue
        out += ["| Line | Severity | Rule | Message | Suggestion |", "|---:|---|---|---|---|"]
        for i in f["issues"]:
            out.append(f"| {i['line']} | {i['severity']} | `{i['rule']}` | {_esc(i['message'])} | "
                       f"{_esc(i.get('suggestion') or '')} |")

    rewrites = report.get("rewrites") or []
    if rewrites:
        meta = report["meta"]
        out += ["", "## AI-assisted rewrites", "",
                f"Provider: `{meta.get('provider', '?')}`, model: `{meta.get('model', '?')}`. "
                "Review every suggestion before applying it."]
        for w in rewrites:
            status = "accepted" if w["accepted"] else f"rejected ({w['reason']})"
            out += ["", f"#### `{w['file']}` line {w['line']} ({status}; fixes {', '.join(w['issues'])})", "",
                    "Original:", "", f"> {w['original']}", ""]
            if w["rewritten"]:
                out += ["Suggested:", "", f"> {w['rewritten']}"]
    out.append("")
    return "\n".join(out)


def write_reports(report: Dict, out_dir: Path, fmt: str = "both") -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    if fmt in ("json", "both"):
        p = out_dir / "quality-report.json"
        p.write_text(to_json(report), encoding="utf-8")
        written.append(p)
    if fmt in ("md", "both"):
        p = out_dir / "quality-report.md"
        p.write_text(to_markdown(report), encoding="utf-8")
        written.append(p)
    return written
