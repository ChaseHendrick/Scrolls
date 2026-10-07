# Job v8in-ag896: partial results (2026-10-07)

The committed `results.json` contains only two baseline rows: ink_9um seed 42 and d9v2
on the PHerc0841 ag896 crop, both with reverse controls. These are pipeline checks,
not completed v8in results. Their measurements have not been changed.

No scored v8in forward, reversed, or depth-shuffled row and no v8in ensemble row is
recorded here. The branch alone cannot establish whether those maps were computed,
interrupted, or lost with the original container. No inference was run for this fix.

`status.json` records that coverage explicitly. `score.py` refreshes it from the scored
rows and prints missing rows and controls. `run.sh` now scores after each completed
step, including resumable steps that already have maps. Even a full set of recorded
rows is not proof of inference completion or validation: the status keeps completion
unknown, and the historical v8in controls use stride 64 against forward stride 42.
Those v8in direction/shuffle comparisons remain provisional until controls are rerun
with matching stride; baseline models have matched settings.

## Script validation

Run `python -m unittest discover -s scripts/experiments/2026-10-07-cloud/v8in-ag896 -p 'test_*.py' -v` from the checkout. The six tests use synthetic map
files and mocked scoring; they verify selection/reporting and do not claim real-data
validation. Scorer exit success means available maps were scored, not that a matched
control passed or inference completed. Read the recorded status fields.
