# Novelty and claim labels

Every substantive claim in this repository should carry one of these labels (in prose or in a table cell). Do not upgrade a label without a new source.

| Label | Meaning | Allowed locations |
| --- | --- | --- |
| **Sourced fact** | Checkable against a cited organizer, archive, or peer-reviewed page, with a date | `prizes.md`, `state-of-play.md`, `pipeline.md`, `sources.md` |
| **Organizer result** | A reading, title or letters announced by the Vesuvius Challenge after papyrological review | `state-of-play.md` |
| **Community report** | Someone else's published run, null, or tool, cited to their repo | `state-of-play.md`, `external.md` |
| **Model output** | An ink or surface prediction from a model. Not a reading | Local `work/` and `experiments/`; summaries in reports |
| **Null** | A preregistered run whose readout rule found no ink, with control and costs | `docs/logs/`, published reports |
| **Candidate (private)** | A run that might show letters | **Only** local, gitignored files and the official submission |
| **Untested idea** | Speculation without a run or a cite | **Only** `docs/logs/YYYY-MM-DD.md` |

## Hard bans

- Do not label **Model output** as letters or as a reading.
- Do not commit, push or describe in public anything labeled **Candidate (private)**.
- Do not present a community report as an organizer result.
- Do not attribute a transcription to a model. Papyrologists transcribe.

See also [`QUALITY.md`](QUALITY.md) and [`AI-AGENTS.md`](AI-AGENTS.md).
