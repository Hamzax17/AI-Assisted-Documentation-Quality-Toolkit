"""Command-line interface: `python -m docqa check docs/`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import __version__
from .links import check_links
from .models import FileResult, Issue
from .reader import MarkdownDoc, find_markdown_files, read_markdown
from .report import build_report, grade, write_reports
from .rewriter import DEFAULT_MODELS, PROVIDERS, LLMError, make_provider, rewrite_issues
from .sections import check_sections, load_section_config
from .style import check_style
from .terminology import check_terminology, find_variant_inconsistencies, load_terms

ALL_CHECKS = ("links", "style", "terminology", "sections")
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SEV = {"error": "E", "warning": "W", "info": "I"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docqa", description="AI-assisted documentation quality toolkit")
    p.add_argument("--version", action="version", version=f"docqa {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Check Markdown files and write a quality report")
    c.add_argument("paths", nargs="+", help="Markdown files or directories")
    c.add_argument("-o", "--output", default="reports", help="Report directory (default: reports)")
    c.add_argument("-f", "--format", choices=["json", "md", "both"], default="both")
    c.add_argument("--checks", default=",".join(ALL_CHECKS),
                   help="Comma-separated checks to run (default: all)")
    c.add_argument("--no-external", action="store_true", help="Skip external URL checks (offline)")
    c.add_argument("--timeout", type=float, default=8.0, help="External link timeout in seconds")
    c.add_argument("--terminology", default=str(CONFIG_DIR / "terminology.json"))
    c.add_argument("--sections", default=str(CONFIG_DIR / "required_sections.json"))
    c.add_argument("--rewrite", action="store_true", help="Add AI-assisted rewrite suggestions")
    c.add_argument("--provider", choices=list(PROVIDERS), default="gemini")
    c.add_argument("--model", help="Model name (provider default if omitted)")
    c.add_argument("--max-rewrites", type=int, default=10, help="Paragraphs to rewrite per file")
    c.add_argument("--fail-under", type=int, metavar="SCORE",
                   help="Exit 1 if the overall score is below SCORE (for CI)")
    c.add_argument("--fail-on-error", action="store_true", help="Exit 1 if any error-level issue exists")
    c.add_argument("-q", "--quiet", action="store_true")
    return p


def run_checks(docs: List[MarkdownDoc], checks: Sequence[str], args: argparse.Namespace
               ) -> Tuple[List[FileResult], Dict[str, List[Issue]]]:
    terms = load_terms(Path(args.terminology)) if "terminology" in checks else []
    sections_cfg = load_section_config(Path(args.sections)) if "sections" in checks else None
    cache: Dict = {}
    per_file: Dict[str, List[Issue]] = {str(d.path): [] for d in docs}

    for doc in docs:
        issues = per_file[str(doc.path)]
        if "links" in checks:
            issues += check_links(doc, not args.no_external, args.timeout, cache)
        if "style" in checks:
            issues += check_style(doc)
        if "terminology" in checks:
            issues += check_terminology(doc, terms)
        if "sections" in checks:
            issues += check_sections(doc, sections_cfg)
    if "terminology" in checks:
        for issue in find_variant_inconsistencies(docs):
            per_file[issue.file].append(issue)

    results = [FileResult(str(d.path), d.word_count(), per_file[str(d.path)]) for d in docs]
    return results, per_file


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    checks = [c.strip() for c in args.checks.split(",") if c.strip()]
    bad = [c for c in checks if c not in ALL_CHECKS]
    if bad:
        print(f"error: unknown check(s): {', '.join(bad)}. Choose from {', '.join(ALL_CHECKS)}",
              file=sys.stderr)
        return 2
    try:
        files = find_markdown_files(args.paths)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not files:
        print("error: no Markdown files found", file=sys.stderr)
        return 2

    docs = [read_markdown(f) for f in files]
    results, per_file = run_checks(docs, checks, args)

    rewrites = []
    meta: Dict = {"paths": args.paths, "checks": checks, "external_links_checked": not args.no_external}
    if args.rewrite:
        try:
            provider = make_provider(args.provider, args.model)
        except LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        meta.update(provider=provider.name, model=provider.model)
        for doc in docs:
            rewrites += rewrite_issues(doc, per_file[str(doc.path)], provider, args.max_rewrites)

    report = build_report(results, rewrites, meta)
    written = write_reports(report, Path(args.output), args.format)

    if not args.quiet:
        for r in results:
            print(f"{r.file}  score {r.score} ({grade(r.score)})  "
                  f"{r.count('error')}E {r.count('warning')}W {r.count('info')}I")
            for i in sorted(r.issues, key=lambda i: (i.line, i.rule))[:8]:
                print(f"  {i.line:>4} {SEV[i.severity]} {i.rule} {i.message}")
            if len(r.issues) > 8:
                print(f"       ... and {len(r.issues) - 8} more")
        s = report["summary"]
        print(f"\nOverall: {s['score']}/100 (grade {s['grade']}), {s['issues']} issues in {s['files']} files")
        if args.rewrite:
            ok = sum(1 for w in rewrites if w.accepted)
            print(f"Rewrites: {ok} accepted, {len(rewrites) - ok} rejected")
        for p in written:
            print(f"Wrote {p}")

    s = report["summary"]
    if args.fail_under is not None and s["score"] < args.fail_under:
        print(f"FAIL: score {s['score']} is below {args.fail_under}", file=sys.stderr)
        return 1
    if args.fail_on_error and s["by_severity"]["error"]:
        print(f"FAIL: {s['by_severity']['error']} error-level issue(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
