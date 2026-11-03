"""Streamlit UI for the documentation quality toolkit.

Run with:  streamlit run app.py
"""
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

from doctoolkit.cli import discover, run_checks
from doctoolkit.links import ExternalChecker
from doctoolkit.report import build_report, to_markdown
from doctoolkit.rewrite import ProviderError, build_rewrites, get_provider
from doctoolkit.sections import load_sections
from doctoolkit.terminology import load_glossary

st.set_page_config(page_title="Docs Quality Toolkit", page_icon="📝", layout="wide")
st.title("📝 Documentation Quality Toolkit")
st.caption("Check Markdown docs for broken links, style problems, inconsistent terms and missing sections.")

SEV_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Settings")
    max_words = st.slider("Max sentence length (words)", 15, 60, 30)
    external = st.checkbox("Check external links (slower)", value=False)
    disabled = st.multiselect(
        "Turn off rules",
        ["passive-voice", "weasel-word", "wordy-phrase", "trailing-whitespace",
         "code-fence-language", "too-short", "missing-section"],
    )
    st.divider()
    st.subheader("AI rewrite suggestions")
    use_ai = st.checkbox("Generate rewrites for flagged passages", value=False)
    provider_name = st.selectbox("Provider", ["mock (offline demo)", "gemini", "anthropic"], disabled=not use_ai)
    api_key = st.text_input("API key", type="password", disabled=not use_ai or provider_name.startswith("mock"),
                            help="Used only for this session; never saved.")
    model = st.text_input("Model (optional)", disabled=not use_ai or provider_name.startswith("mock"))
    max_rewrites = st.number_input("Max passages to rewrite", 1, 50, 10, disabled=not use_ai)
    st.divider()
    glossary_file = st.file_uploader("Custom glossary (JSON)", type="json")
    sections_file = st.file_uploader("Custom sections (JSON)", type="json")

# ---------------- input ----------------
tab_upload, tab_paste, tab_sample = st.tabs(["Upload files", "Paste text", "Try the sample docs"])
inputs = {}  # filename -> text

with tab_upload:
    ups = st.file_uploader("Markdown files", type=["md", "markdown"], accept_multiple_files=True)
    for u in ups or []:
        inputs[u.name] = u.getvalue().decode("utf-8", errors="replace")
    st.caption("Links between uploaded files are resolved, so upload them together.")

with tab_paste:
    pasted = st.text_area("Markdown", height=250, placeholder="# My doc\n\nPaste Markdown here...")
    if pasted.strip():
        inputs["pasted.md"] = pasted

with tab_sample:
    sample_dir = Path(__file__).parent / "examples" / "docs"
    if sample_dir.exists() and st.checkbox("Use the bundled sample docs (planted mistakes)"):
        for f in sorted(sample_dir.glob("*.md")):
            inputs[f.name] = f.read_text(encoding="utf-8")

run = st.button("Run checks", type="primary", disabled=not inputs)


def _load_json(upload, loader, default_loader):
    if not upload:
        return default_loader()
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as t:
        t.write(upload.getvalue())
    try:
        return loader(t.name)
    finally:
        os.unlink(t.name)


# ---------------- run ----------------
if run:
    try:
        glossary = _load_json(glossary_file, load_glossary, load_glossary)
        sections = _load_json(sections_file, load_sections, load_sections)
    except (ValueError, json.JSONDecodeError, KeyError) as e:
        st.error(f"Could not read your custom JSON file: {e}")
        st.stop()

    with tempfile.TemporaryDirectory() as tmp:
        for name, text in inputs.items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        files = discover([tmp], [])
        args = SimpleNamespace(disable=disabled, max_sentence_words=max_words)
        ext = ExternalChecker() if external else None
        with st.spinner("Checking..."):
            results, usage = run_checks(files, args, glossary, sections, ext)

    rewrites = []
    if use_ai:
        try:
            if api_key:
                os.environ["GEMINI_API_KEY" if provider_name == "gemini" else "ANTHROPIC_API_KEY"] = api_key
            provider = get_provider(provider_name.split()[0], model or None, glossary)
            all_issues = [i for r in results for i in r["issues"]]
            with st.spinner("Asking the model for rewrites..."):
                rewrites = build_rewrites(all_issues, provider, [t["preferred"] for t in glossary["terms"]],
                                          max_items=int(max_rewrites))
        except ProviderError as e:
            st.warning(f"AI rewrite step skipped: {e}")

    st.session_state["report"] = build_report(
        results, usage, rewrites,
        options={"external_links": external, "rewrite": use_ai, "max_sentence_words": max_words,
                 "disabled_rules": sorted(disabled)},
    )

# ---------------- results ----------------
report = st.session_state.get("report")
if report:
    s = report["summary"]
    st.divider()
    c = st.columns(5)
    c[0].metric("Average score", f"{s['average_score']}/100")
    c[1].metric("Files", s["files"])
    c[2].metric("Errors", s["by_severity"]["error"])
    c[3].metric("Warnings", s["by_severity"]["warning"])
    c[4].metric("Info", s["by_severity"]["info"])

    t_files, t_issues, t_terms, t_ai, t_dl = st.tabs(
        ["Files", "Issues", "Terminology", f"AI rewrites ({len(report['rewrites'])})", "Download"])

    with t_files:
        st.dataframe(
            [{"File": f["file"], "Score": f["score"], "Errors": f["counts"]["error"],
              "Warnings": f["counts"]["warning"], "Info": f["counts"]["info"], "Words": f["words"]}
             for f in report["files"]],
            use_container_width=True, hide_index=True,
        )

    with t_issues:
        rows = [{"File": f["file"], "Line": i["line"], "Severity": f"{SEV_ICON[i['severity']]} {i['severity']}",
                 "Check": i["check"], "Rule": i["rule"], "Message": i["message"],
                 "Suggestion": i.get("suggestion") or ""}
                for f in report["files"] for i in f["issues"]]
        if not rows:
            st.success("No issues found.")
        else:
            sev = st.multiselect("Severity", ["error", "warning", "info"], default=["error", "warning", "info"])
            chk = st.multiselect("Check", sorted({r["Check"] for r in rows}), default=sorted({r["Check"] for r in rows}))
            shown = [r for r in rows if r["Severity"].split()[1] in sev and r["Check"] in chk]
            st.dataframe(shown, use_container_width=True, hide_index=True)

    with t_terms:
        mixed = {k: v for k, v in report["terminology_usage"].items() if v["variants"]}
        if not mixed:
            st.info("No inconsistent terminology found.")
        for k, v in mixed.items():
            st.write(f"**{k}** used {v['preferred']}×; variants: " +
                     ", ".join(f"“{b}” ×{n}" for b, n in v["variants"].items()))

    with t_ai:
        if not report["rewrites"]:
            st.info("Turn on “Generate rewrites” in the sidebar and run again.")
        else:
            st.caption("Suggestions only. Review each one before copying it into your file.")
        for r in report["rewrites"]:
            with st.expander(f"{r['file']} · line {r['line']}"):
                st.write("**Problems:** " + "; ".join(r["problems"]))
                a, b = st.columns(2)
                a.markdown("**Original**")
                a.code(r["original"], language="markdown")
                b.markdown("**Suggested**")
                b.code(r["rewrite"], language="markdown")
                for w in r["warnings"]:
                    st.warning(w)

    with t_dl:
        st.download_button("Download Markdown report", to_markdown(report), "docs-quality-report.md", "text/markdown")
        st.download_button("Download JSON report", json.dumps(report, indent=2, ensure_ascii=False),
                           "docs-quality-report.json", "application/json")
