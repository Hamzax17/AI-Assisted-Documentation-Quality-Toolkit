# Documentation Quality Report

_Generated 2026-11-03T20:50:38+00:00 by doc-quality-toolkit v0.1.0_

## Summary

| Metric | Value |
| --- | --- |
| Files checked | 3 |
| Words | 203 |
| Average score | **78.7** / 100 |
| Errors | 5 |
| Warnings | 16 |
| Info | 14 |

**Most common rules:** `inconsistent-term` (8), `passive-voice` (7), `missing-section` (4), `weasel-word` (2), `wordy-phrase` (2), `broken-anchor` (2), `broken-link` (2), `long-sentence` (1)

## Files

| File | Score | Errors | Warnings | Info |
| --- | ---: | ---: | ---: | ---: |
| `README.md` | 69.5 | 2 | 8 | 9 |
| `api.md` | 93.0 | 0 | 3 | 2 |
| `guide.md` | 73.5 | 3 | 5 | 3 |

## Issues

### `README.md` (score 69.5)

| Line | Severity | Rule | Message |
| ---: | --- | --- | --- |
| 1 | warning | `missing-section` | Missing required section (readme profile): "License". _Add a "## License" section._ |
| 1 | info | `missing-section` | Missing recommended section (readme profile): "Features", "Overview". _Add a "## Features" section._ |
| 3 | warning | `inconsistent-term` | Use "GitHub" instead of "Github". _Replace with "GitHub"._ |
| 3 | info | `passive-voice` | Possible passive voice: "is used". _Prefer an active construction with a clear actor._ |
| 3 | info | `passive-voice` | Possible passive voice: "is hosted". _Prefer an active construction with a clear actor._ |
| 3 | info | `weasel-word` | Vague intensifier "really". _Remove it or be specific._ |
| 3 | info | `wordy-phrase` | Wordy phrase "in order to". _Use "to"._ |
| 7 | warning | `inconsistent-term` | Use "JavaScript" instead of "Javascript". _Replace with "JavaScript"._ |
| 7 | warning | `inconsistent-term` | Use "Python" instead of "python". _Replace with "Python"._ |
| 7 | warning | `long-sentence` | Sentence has 37 words (limit 30). _Split it into two sentences._ |
| 7 | info | `passive-voice` | Possible passive voice: "be configured". _Prefer an active construction with a clear actor._ |
| 7 | info | `passive-voice` | Possible passive voice: "is made". _Prefer an active construction with a clear actor._ |
| 7 | info | `weasel-word` | Vague intensifier "very". _Remove it or be specific._ |
| 7 | info | `wordy-phrase` | Wordy phrase "utilize". _Use "use"._ |
| 11 | error | `broken-anchor` | Anchor #setup-steps not found in guide.md. _Did you mean #setup?_ |
| 11 | error | `broken-link` | Link target not found: missing-file.md |
| 11 | warning | `generic-link-text` | Non-descriptive link text "click here". _Say where the link goes._ |
| 13 | warning | `empty-section` | Section "Configuration" is empty. _Write the section or remove the heading._ |
| 17 | warning | `placeholder-text` | Placeholder text left in the document: "TODO". _Finish or remove it._ |

### `api.md` (score 93.0)

| Line | Severity | Rule | Message |
| ---: | --- | --- | --- |
| 1 | warning | `missing-section` | Missing required section (api profile): "Examples", "Example". _Add a "## Examples" section._ |
| 1 | info | `missing-section` | Missing recommended section (api profile): "Errors", "Error handling", "Error codes". _Add a "## Errors" section._ |
| 5 | warning | `inconsistent-term` | Use "API" instead of "api". _Replace with "API"._ |
| 5 | warning | `inconsistent-term` | Use "JSON" instead of "Json". _Replace with "JSON"._ |
| 15 | info | `passive-voice` | Possible passive voice: "is returned". _Prefer an active construction with a clear actor._ |

### `guide.md` (score 73.5)

| Line | Severity | Rule | Message |
| ---: | --- | --- | --- |
| 7 | warning | `inconsistent-term` | Use "email" instead of "e-mail". _Replace with "email"._ |
| 7 | warning | `repeated-word` | Repeated word "the". _Remove one "the"._ |
| 7 | info | `passive-voice` | Possible passive voice: "are stored". _Prefer an active construction with a clear actor._ |
| 11 | warning | `inconsistent-term` | Use "username" instead of "user name". _Replace with "username"._ |
| 11 | warning | `inconsistent-term` | Use "sign in" instead of "log in". Use "sign in" as the verb. _Replace with "sign in"._ |
| 11 | info | `passive-voice` | Possible passive voice: "is generated". _Prefer an active construction with a clear actor._ |
| 19 | info | `code-fence-language` | Code block has no language. _Add a language (e.g. ```python) for highlighting._ |
| 23 | error | `broken-link` | Link target not found: images/diagram.png |
| 23 | warning | `missing-alt-text` | Image images/diagram.png has no alt text. _Describe the image for screen readers._ |
| 25 | error | `broken-anchor` | Anchor #overveiw not found in this page. |
| 27 | error | `undefined-reference` | Reference link [nope] has no definition. |

## Terminology consistency

| Preferred term | Uses | Variants found |
| --- | ---: | --- |
| GitHub | 0 | "Github" ×1 |
| JavaScript | 0 | "Javascript" ×1 |
| Python | 0 | "python" ×1 |
| API | 4 | "api" ×1 |
| JSON | 0 | "Json" ×1 |
| email | 0 | "e-mail" ×1 |
| username | 0 | "user name" ×1 |
| sign in | 0 | "log in" ×1 |

## AI-assisted rewrite suggestions

_Suggestions only; review each one before applying. Files are never modified automatically._

### `README.md` line 3

**Problems:** passive-voice: Possible passive voice: "is used".; wordy-phrase: Wordy phrase "in order to".; passive-voice: Possible passive voice: "is hosted".; weasel-word: Vague intensifier "really".; inconsistent-term: Use "GitHub" instead of "Github".

**Original**

```markdown
Acme Widgets is a library that is used by developers in order to build dashboards. It is really easy to get started and the project is hosted on Github.
```

**Suggested**

```markdown
Acme Widgets is a library that is used by developers to build dashboards. It is easy to get started and the project is hosted on GitHub.
```

### `README.md` line 7

**Problems:** long-sentence: Sentence has 37 words (limit 30).; passive-voice: Possible passive voice: "be configured".; passive-voice: Possible passive voice: "is made".; weasel-word: Vague intensifier "very".; wordy-phrase: Wordy phrase "utilize".; inconsistent-term: Use "JavaScript" instead of "Javascript".; inconsistent-term: Use "Python" instead of "python".

**Original**

```markdown
Install the package with pip. Then import it in your Javascript or python project and the API will be configured automatically for you when the first request is made by the client, which is very convenient for teams that utilize many environments.
```

**Suggested**

```markdown
Install the package with pip. Then import it in your JavaScript or Python project and the API will be configured automatically for you when the first request is made by the client, which is convenient for teams that use many environments.
```

### `api.md` line 5

**Problems:** inconsistent-term: Use "API" instead of "api".; inconsistent-term: Use "JSON" instead of "Json".

**Original**

```markdown
The Widgets api lets you create, list and delete widgets over HTTP using Json payloads.
```

**Suggested**

```markdown
The Widgets API lets you create, list and delete widgets over HTTP using JSON payloads.
```

### `guide.md` line 7

**Problems:** repeated-word: Repeated word "the".; passive-voice: Possible passive voice: "are stored".; inconsistent-term: Use "email" instead of "e-mail".

**Original**

```markdown
Welcome to the the guide. You can e-mail the team if you get stuck, and the API keys are stored in `config.json`.
```

**Suggested**

```markdown
Welcome to the the guide. You can email the team if you get stuck, and the API keys are stored in `config.json`.
```

### `guide.md` line 11

**Problems:** passive-voice: Possible passive voice: "is generated".; inconsistent-term: Use "username" instead of "user name".; inconsistent-term: Use "sign in" instead of "log in". Use "sign in" as the verb.

**Original**

```markdown
First log in to your account, then create a user name. The token is generated by the server.
```

**Suggested**

```markdown
First sign in to your account, then create a username. The token is generated by the server.
```
