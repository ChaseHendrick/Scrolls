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
| `python -m kit run init/status/cost/check/list` | Ledger records under `experiments/` | `--root DIR`; `status ... --announced` only after an official announcement |

## Output rules

- Human-readable text by default; `prizes --json` for scripts.
- Every prize output names the snapshot date and says the live page wins.
- `plan` never executes anything. Comments explain each step; placeholders are never silently filled with guesses.
- Errors go to stderr with a one-line reason and a non-zero exit (2 for bad input, 1 for a failed check).
- Words: say "ink map" or "model output", never "reading", for predictions.

## Docs

- README first screen: what this is, what it does not claim, where to start.
- Tables for comparisons, short sentences, dated facts, links on first mention.
