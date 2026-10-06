# Local experiments

Each experiment lives in `experiments/<slug>/run.json`, created by `python -m kit run init`. Everything in this folder except this README is gitignored, because a possible finding must stay private until the prize is announced. Put large outputs under `work/` (also gitignored).

Format: [`../templates/experiment.json`](../templates/experiment.json). Workflow: [`../docs/WORKFLOW.md`](../docs/WORKFLOW.md).

To share a **null**, write a report (commands, control, costs, what it does and does not show) in `docs/logs/YYYY-MM-DD-<slug>.md` or its own repository. Never move a `candidate` or `submitted` record out of this folder.
