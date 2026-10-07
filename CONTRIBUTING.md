# Contributing

Thanks for your interest in **Scrolls**. Please read [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md) and [`docs/QUALITY.md`](docs/QUALITY.md) first.

## Ground rules

1. **No claimed letters**, and no candidate images or descriptions in this public repository. See [`docs/WORKFLOW.md`](docs/WORKFLOW.md).
2. **Cite URLs and dates** for prize facts and published results.
3. **`kit/` changes need tests** (`docs/TESTING.md`).
4. **One engine.** villa is the engine. General fixes go upstream to [ScrollPrize/villa](https://github.com/ScrollPrize/villa); link the PR here.
5. **No scroll data in Git**: volumes, renders, ink maps and checkpoints stay out.

## Practical workflow

```bash
python -m unittest discover -s tests -v
python -m kit prizes
```

- Docs-only PRs: keep `prizes.md` and `state-of-play.md` dated, sourced and conservative.
- Speculative notes belong in `docs/logs/YYYY-MM-DD.md`.
- CLI expectations: `docs/UI-UX.md`.

## Scope that fits

- Tested helpers for planning, recording and checking runs.
- Sourced updates to prizes, the state of play, and costs.
- Published null reports with commands, controls and costs.

## Scope that does not fit

- "I found letters" commits, screenshots or hints.
- Vendored copies of villa, VC3D or model weights.
