# Community standards

Short formats for Vesuvius Challenge work that anyone can follow and anyone can check. Each standard has a version,
a checker that can fail, and reference examples. One row per standard.

| Standard | Version | What it covers | Checker |
| --- | --- | --- | --- |
| [Scroll dataset card](dataset-card.md) | 0.1 draft (26 November 2026) | Datasets on Hugging Face: SHA256SUMS, `provenance.json`, license inheritance, caveats, spent seeds and truth | `python -m kit.datacard check` ([page](../tools/datacard.md)) |
| [Frozen-test protocol](frozen-test.md) | 0.1 draft (26 November 2026) | Test claims others can trust: preregister, freeze, an independent review pin before launch, a reviewer who is never the author, spent seeds and truth kept out, the arms tried reported; checklist and [template](../../templates/frozen-test.md) | No single checker yet: `python -m kit freeze`, `python -m kit reviewpin` and `python -m kit integrity` cover parts ([section 5](frozen-test.md#5-how-this-repository-runs-it)) |
