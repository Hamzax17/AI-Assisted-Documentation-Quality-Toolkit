# Documentation Quality Toolkit

A command-line toolkit that audits Markdown documentation and produces a quality report. It combines deterministic checks with optional LLM-suggested rewrites. It has no runtime dependencies beyond Python 3.9+.

## Features

| Capability | How it works |
| --- | --- |
| Markdown reader | Pure-Python parser. It reads headings, GitHub-style anchors, links, code blocks and front matter, and skips code and comments. |
| Broken link checker | Checks relative files, in-page and cross-file anchors, reference links and images. External URLs are checked with `--external`. |
| Grammar and style | Rule-based checks for long sentences, passive voice, weasel words, wordy phrases, repeated words, heading structure, missing alt text and placeholders. |
| Terminology consistency | A JSON glossary lists preferred and avoided terms. |
| Missing sections | JSON profiles for README, API, tutorial and contributing docs. They also detect empty sections and missing titles. |
| AI-assisted rewriting | Sends only flagged passages to Gemini or Claude and returns suggestions. Your files are never modified. |
| Quality report | JSON for tooling and Markdown for humans, with a 0-100 score per file. |
| Version control | Git, with a GitHub Actions workflow that tests the toolkit and checks its own docs. |

## Installation

```bash
git clone https://github.com/<your-user>/doc-quality-toolkit.git
cd doc-quality-toolkit
pip install -e ".[dev]"
pytest -q
```

## Usage

```bash
# Check a folder and print findings
doccheck docs/

# Write both reports
doccheck docs/ --json report.json --markdown report.md

# Include external URLs (needs network access)
doccheck docs/ --external

# Get AI rewrite suggestions for flagged passages
export GEMINI_API_KEY=...        # or ANTHROPIC_API_KEY
doccheck docs/ --rewrite --markdown report.md

# Try the rewrite step offline with the built-in rule-based provider
doccheck examples/docs --rewrite --provider mock
```

Try it on `examples/docs`, which contains deliberate problems. The generated output is in `examples/sample-report.md`.

### Options

| Option | Purpose |
| --- | --- |
| `--glossary FILE` | Use your own terminology glossary. |
| `--sections FILE` | Use your own required-section profiles. |
| `--max-sentence-words N` | Change the long-sentence limit (default 30). |
| `--disable RULE` | Turn off a rule, for example `passive-voice`. Repeatable. |
| `--ignore GLOB` | Skip matching files. Repeatable. |
| `--fail-on error\|warning\|never` | Set the severity that causes exit code 1 (default `error`). |
| `--fail-under SCORE` | Fail if the average score falls below this value. |
| `--provider`, `--model` | Choose `gemini`, `anthropic` or `mock`, and override the model name. |

Defaults can live in a `doccheck.json` file in the working directory. Its keys mirror the options, for example `{"ignore": ["drafts/*"], "disable": ["passive-voice"], "fail_under": 80}`.

## Customizing

**Glossary.** The default glossary is in `doctoolkit/data/default_glossary.json`:

```json
{"terms": [{"preferred": "GitHub", "avoid": ["Github", "github"], "note": "optional hint"}]}
```

**Sections.** Each profile lists groups of acceptable heading names, and any heading in a group satisfies it. Assign a profile by file name pattern, or put `doc_type: api` in the document's front matter.

```json
{"profiles": {"runbook": {"match": ["runbooks/*.md"], "required": [["Symptoms"], ["Mitigation", "Fix"]]}}}
```

## How the score works

Each issue has a weight: error 5, warning 2, info 0.5. The score is 100 minus the total weight, scaled to document length, where a 300-word document is the reference size. Long documents therefore lose fewer points per issue. Treat the score as a trend indicator, not an absolute grade.

## AI rewriting

- Only passages that the rule-based checks flagged are sent to the model. Nothing else leaves your machine.
- The prompt tells the model to preserve meaning, inline code, link text and URLs.
- Each suggestion is checked afterwards. If the model dropped inline code or a URL, the report shows a warning.
- Set `DOCQ_PROVIDER` and `DOCQ_MODEL` to change the defaults. Model names change over time, so override them if a default is retired.

## Project layout

```text
doctoolkit/
  reader.py        Markdown parsing
  links.py         link checking
  style.py         style rules
  terminology.py   glossary checks
  sections.py      structure checks
  rewrite.py       LLM providers and rewrite orchestration
  report.py        JSON and Markdown reports
  cli.py           the doccheck command
tests/             pytest suite
examples/          sample docs with planted problems
```

## Contributing

Open a pull request with tests for any new rule. Run `pytest -q` and `doccheck README.md` before you push.

## Publishing to GitHub

```bash
git remote add origin https://github.com/<your-user>/doc-quality-toolkit.git
git push -u origin main
```

## License

MIT
