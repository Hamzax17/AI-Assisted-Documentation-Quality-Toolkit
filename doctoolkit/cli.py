"""Command-line interface: ``doccheck [paths...]``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple

from . import __version__
from .links import ExternalChecker, check_links, is_external
from .models import SEVERITY_RANK, Issue
from .reader import Doc, load
from .report import build_report, to_markdown, write_json
from .rewrite import ProviderError, build_rewrites, get_provider
from .sections import check_sections, load_sections
from .style import check_style
from .terminology import check_terminology, load_glossary

MD_SUFFIXES = {".md", ".markdown"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "site-packages"}


def discover(paths: List[str], ignore: List[str]) -> List[Tuple[Path, Path]]:
    """Return (file, root) pairs for every Markdown file under the given paths."""
    found: List[Tuple[Path, Path]] = []
    seen = set()
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {raw}")
        root = p if p.is_dir() else p.parent
        candidates = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in candidates:
            if not f.is_file() or f.suffix.lower() not in MD_SUFFIXES:
                continue
            rel = f.relative_to(root) if p.is_dir() else Path(f.name)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            rel_posix = PurePosixPath(rel.as_posix())
            if any(rel_posix.match(pat) for pat in ignore):
                continue
            key = f.resolve()
            if key not in seen:
                seen.add(key)
                found.append((f, root))
    return found


def load_config(path: str | None) -> dict:
    p = Path(path) if path else Path("doccheck.json")
    if not p.exists():
        if path:
            raise FileNotFoundError(f"Config not found: {path}")
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{p}: invalid JSON ({e})") from e


def build_parser(cfg: dict) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doccheck",
        description="AI-assisted documentation quality toolkit: links, style, terminology, structure, rewrites.",
    )
    p.add_argument("paths", nargs="*", default=cfg.get("paths", ["."]), help="Markdown files or folders (default: .)")
    p.add_argument("--config", help="JSON config file (default: ./doccheck.json if present)")
    p.add_argument("--glossary", default=cfg.get("glossary"), help="Terminology glossary JSON")
    p.add_argument("--sections", default=cfg.get("sections"), help="Required-sections JSON")
    p.add_argument("--max-sentence-words", type=int, default=cfg.get("max_sentence_words", 30))
    p.add_argument("--ignore", action="append", default=list(cfg.get("ignore", [])), metavar="GLOB",
                   help="Glob of files to skip (repeatable)")
    p.add_argument("--disable", action="append", default=list(cfg.get("disable", [])), metavar="RULE",
                   help="Rule id to turn off (repeatable)")
    p.add_argument("--external", action="store_true", default=cfg.get("external", False),
                   help="Also check http(s) links over the network")
    p.add_argument("--timeout", type=float, default=cfg.get("timeout", 8.0), help="External link timeout (s)")
    p.add_argument("--rewrite", action="store_true", help="Ask an LLM for rewrite suggestions of flagged passages")
    p.add_argument("--provider", choices=["auto", "gemini", "anthropic", "mock"], default=None)
    p.add_argument("--model", default=None, help="Model name override (or DOCQ_MODEL)")
    p.add_argument("--max-rewrites", type=int, default=cfg.get("max_rewrites", 20))
    p.add_argument("--json", dest="json_out", metavar="FILE", help="Write JSON report")
    p.add_argument("--markdown", dest="md_out", metavar="FILE", help="Write Markdown report")
    p.add_argument("--quiet", action="store_true", help="Only print the summary line")
    p.add_argument("--fail-on", choices=["error", "warning", "never"], default=cfg.get("fail_on", "error"))
    p.add_argument("--fail-under", type=float, default=cfg.get("fail_under"), metavar="SCORE",
                   help="Exit non-zero if the average score is below this")
    p.add_argument("--version", action="version", version=f"doccheck {__version__}")
    return p


def run_checks(files: List[Tuple[Path, Path]], args, glossary: dict, sections: dict, ext: ExternalChecker | None):
    docs: List[Tuple[Doc, Path]] = [(load(f, root), root) for f, root in files]
    if ext is not None:
        urls = [l.target.strip() for d, _ in docs for l in d.links if is_external(l.target.strip())]
        ext.prefetch(urls)

    disabled = set(args.disable)
    doc_cache: Dict[Path, Doc] = {d.path.resolve(): d for d, _ in docs}
    usage: Dict[str, dict] = {}
    results = []
    for doc, root in docs:
        issues: List[Issue] = []
        issues += check_links(doc, root, ext, doc_cache)
        issues += check_style(doc, {"max_sentence_words": args.max_sentence_words})
        t_issues, t_usage = check_terminology(doc, glossary)
        issues += t_issues
        for term, u in t_usage.items():
            agg = usage.setdefault(term, {"preferred": 0, "variants": {}})
            agg["preferred"] += u["preferred"]
            for v, n in u["variants"].items():
                agg["variants"][v] = agg["variants"].get(v, 0) + n
        issues += check_sections(doc, sections)
        issues = [i for i in issues if i.rule not in disabled]
        results.append({"file": doc.name, "words": doc.words, "issues": issues})
    return results, usage


def main(argv: List[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    known, _ = pre.parse_known_args(argv)
    try:
        cfg = load_config(known.config)
    except (OSError, ValueError) as e:
        print(f"doccheck: {e}", file=sys.stderr)
        return 2
    args = build_parser(cfg).parse_args(argv)

    try:
        glossary = load_glossary(args.glossary)
        sections = load_sections(args.sections)
        files = discover(args.paths, args.ignore)
    except (OSError, ValueError) as e:
        print(f"doccheck: {e}", file=sys.stderr)
        return 2
    if not files:
        print("doccheck: no Markdown files found.", file=sys.stderr)
        return 2

    provider = None
    if args.rewrite:
        try:
            provider = get_provider(args.provider, args.model, glossary)
        except ProviderError as e:
            print(f"doccheck: {e}", file=sys.stderr)
            return 2

    ext = ExternalChecker(timeout=args.timeout) if args.external else None
    results, usage = run_checks(files, args, glossary, sections, ext)

    rewrites: List[dict] = []
    if provider:
        all_issues = [i for r in results for i in r["issues"]]
        try:
            rewrites = build_rewrites(all_issues, provider, [t["preferred"] for t in glossary["terms"]],
                                      max_items=args.max_rewrites)
        except ProviderError as e:
            print(f"doccheck: rewrite step failed: {e}", file=sys.stderr)
            return 2

    report = build_report(
        results, usage, rewrites,
        options={"external_links": bool(args.external), "rewrite": bool(args.rewrite),
                 "max_sentence_words": args.max_sentence_words, "disabled_rules": sorted(args.disable)},
    )
    if args.json_out:
        write_json(report, args.json_out)
    if args.md_out:
        Path(args.md_out).write_text(to_markdown(report), encoding="utf-8")

    s = report["summary"]
    if not args.quiet:
        flat = [(f["file"], i) for f in report["files"] for i in f["issues"]]
        for name, i in sorted(flat, key=lambda x: (x[0], x[1]["line"], SEVERITY_RANK[x[1]["severity"]])):
            print(f"{name}:{i['line']}: {i['severity']} [{i['rule']}] {i['message']}")
        if rewrites:
            print(f"\n{len(rewrites)} AI rewrite suggestion(s) written to the report.")
    sev = s["by_severity"]
    print(f"\n{s['files']} file(s), {s['issues']} issue(s) "
          f"({sev['error']} error, {sev['warning']} warning, {sev['info']} info); "
          f"average score {s['average_score']}/100")
    if args.json_out:
        print(f"JSON report: {args.json_out}")
    if args.md_out:
        print(f"Markdown report: {args.md_out}")

    if args.fail_on == "error" and sev["error"]:
        return 1
    if args.fail_on == "warning" and (sev["error"] or sev["warning"]):
        return 1
    if args.fail_under is not None and s["average_score"] < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
