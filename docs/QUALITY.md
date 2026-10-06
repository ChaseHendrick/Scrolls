# Quality standard

## Claims

| Kind of claim | Required |
| --- | --- |
| Prize amount, deadline, eligibility | Source URL and the date checked; also in a dated `kit/data/` snapshot |
| Historical or published result (a scroll read, a title found) | Organizer or peer-reviewed source in the same doc, or in [`sources.md`](sources.md) with an in-doc pointer |
| Someone else's run or null | Link to their repository or report; say it is their report |
| Our run's outcome | A ledger record (`experiments/<slug>/run.json`) with readout rule, control, commands, costs |
| Possible letters | Label **Candidate (private)**; never in this repository |
| Untested idea | Mark as hypothesis; prefer `docs/logs/` |

## Kit

- Runtime: Python 3.10+, standard library only.
- `python -m unittest discover -s tests` must pass.
- `plan` output must match the official tutorial commands at the cited commit. When upstream changes, update the template and the citation together.
- Passing tests verifies the snapshot, the templates, the thresholds and the ledger rules. It does not verify that any GPU pipeline runs, or that any scroll contains ink.

## Docs

- Prize pages and the state of play stay sourced, dated and conservative.
- Distinguish **ink detected** (a model's map), **letters visible** (a human sees letterforms), and **legible** (papyrologists read them). Only the last wins prizes.
- AI assistance is disclosed when it shaped a result.

## Novelty labels

Use the vocabulary in [`NOVELTY.md`](NOVELTY.md).

## Binaries

- SVG for diagrams and hero art.
- No CT data, renders, ink maps or checkpoints in Git.
