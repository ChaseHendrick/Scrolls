# UI and CLI

The product is a terminal package and Markdown documentation. There is no web app. Command surface checked on 2026-10-06.

## Command surfaces

Use Python 3.10 or newer. Depending on the environment the executable is `python` or `python3`.

| Command | Result | Important inputs |
| --- | --- | --- |
| `python -m kit prizes` | Table of open prizes, days left, eligible scrolls | `--json`, `--today YYYY-MM-DD` |
| `python -m kit doctor` | pass / warn / fail per check; exit 1 on any fail; Apple Silicon without CUDA is a warn | `VILLA`, `VC_BIN` environment variables; `--disk PATH` |
| `python -m kit plan SCROLL` | Shell commands with comments: setup, control, target, rules | `--batch N`, `--mac`; exits 2 for an ineligible scroll |
| `python -m kit cost` | A dollar figure | `--gpu-hours`, `--rate`, optional CPU and storage |
| `python -m kit fetch PREFIX DEST` | Mirror of a public bucket prefix; resumes by size; `w035` is a shortcut for the control surface volume | `--workers N`; exit 2 on a failed or empty fetch |
| `python -m kit verify REF CAND` | Map agreement stats and a verdict: pass, pass-uncontrolled, fail, control-not-caught | `--control MAP`, `--tolerance`, `--max-fraction`, `--json`, `--slug`; exit 0/1/2/3 |
| `python -m kit run init/status/cost/record/check/list` | Ledger records under `experiments/` | `--root DIR`; `status ... --announced` only after an official announcement |

## Output rules

- Human-readable text by default; `prizes --json` for scripts.
- Every prize output names the snapshot date and says the live page wins.
- `plan` never executes anything. Comments explain each step; placeholders are never silently filled with guesses.
- Errors go to stderr with a one-line reason and a non-zero exit (2 for bad input, 1 for a failed check).
- Words: say "ink map" or "model output", never "reading", for predictions.

## Docs

- README first screen: what this is, what it does not claim, where to start.
- Tables for comparisons, short sentences, dated facts, links on first mention.
