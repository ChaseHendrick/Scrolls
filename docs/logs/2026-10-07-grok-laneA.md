# Lane A: cross-analysis of open PRs #6 to #10 (2026-10-07)

Every map behind these numbers is model output on public labelled PHerc0841 data, not a reading. No new inference was run and no map was opened: this lane reads only the JSON records committed on the open PR branches (read-only `git show`), so every number below is printed by `scripts/experiments/2026-10-07-grok-laneA/synth.py`.

Sources (branch heads at the time of the run): `tricks` a295168 (PR #8), `v8in1447-w00` c4a5ead (PR #7), `v8in1447-ag405` 97d26e7 (PR #9); main 9af26f6. PR #6 (`thresholds`) was read but its part 1 (threshold transfer) never ran and part 3 is already paired in its own notes, so it adds no row here. PR #10 (`v8in1447-ag896`) has no results file.

Command, from the repository root after `git fetch origin`:

```bash
python3 scripts/experiments/2026-10-07-grok-laneA/synth.py --json scripts/experiments/2026-10-07-grok-laneA/synth.json > scripts/experiments/2026-10-07-grok-laneA/synth.out
```

Full output: `synth.out`; machine-readable: `synth.json`.

## Noise yardstick, and its limits

`kit auc --bootstrap/--compare` needs the maps, and none are on this machine (they stayed in the cloud containers; no scroll data in git). So no new bootstrap was run. Instead the script uses the block-bootstrap 95 % intervals already measured on main (`docs/logs/2026-10-07-overlap-and-baseline.md`, section 5, team map): half-widths 0.0085 (w00), 0.0225 (ag896), 0.038 (ag405). A difference is called "clear" above twice the half-width, "marginal" above one, else "within noise". This is a rule of thumb, not a test: the intervals are for a different map, and paired differences on the same pixels usually vary less than an unpaired interval suggests. Interpretation throughout.

## Findings

### 1. The Reader v2 over d9v2 ranking flips between two traces of one sheet (novel)

w00 and ag896 trace the same papyrus (main, finding 5). On w00 Reader v2 beats d9v2 by +0.0275 (clear); on ag896 it trails by -0.0258 (marginal). Over the 24 maps scored on both crops, the reader ranking agrees only partly: Kendall tau-a 0.551 (214 concordant, 62 discordant pairs), and 20 discordant pairs have gaps above twice the noise on both crops. So a single-crop ranking of PHerc0841 readers does not carry to a second trace of the same sheet. Not found in any PR or log.

### 2. Depth windows tuned on one trace do not transfer to the other; the 4-window mean always beats the transferred window (novel)

Choosing the best window by AUC on one crop and applying it to the other (6 cases: three readers, both directions): for `ink_9um` seed 42 and its soup, w00 prefers z8-27 or z5-25 while ag896 prefers z0-20. Picking on ag896 costs -0.1206 (seed 42) and -0.1579 (soup) against the default window on w00. In all 6 cases the untuned 4-window mean scores above the transferred window (by +0.0074 to +0.1718). PR #8 compared the mean with the label-chosen window on the same crop; the cross-trace transfer was not done. This supports the 4-window mean over any tuned window for target runs.

### 3. Reader v2's raised controls hold on the second trace, but high reversed controls are not unique to it (partly novel)

Reader v2's depth-shuffled AUC is the highest of the shuffled maps on both crops: 0.5681 (w00) and 0.6170 (ag896); the others are 0.4762 to 0.5578. That extends the w00-only observation in `2026-10-07-cloud-partial.md` (reproduction on w00, new on ag896). But its reversed control on ag896 (0.5988) is ordinary, and d9v2 on the independent sheet ag405 has a reversed control of 0.6572, close to Reader v2's on w00. Within one reader the reversed control moves with the depth window (seed 42 on w00: 0.4547 at z0-20 to 0.6343 at z5-25). Interpretation: the reversed control alone is a noisy yardstick; the shuffle control separates Reader v2 more consistently.

### 4. Several w00 gains do not replicate on ag896 (novel as a set)

| Claim | w00 diff | ag896 diff |
| --- | ---: | ---: |
| `ink_9um` soup over seed 42 | +0.0265 clear | +0.0129 within noise |
| d9v2 4-window mean over default | +0.0204 clear | +0.0087 within noise |
| d9v2 mirror TTA over default | +0.0208 clear | -0.0099 within noise |
| seed 42 4-window mean over default | +0.0366 clear | +0.0627 clear |

Only the seed 42 4-window mean gain is clear on both traces.

### 5. Null: v8in-1447 adds nothing measurable to d9v2

The rank ensemble v8in-1447 + d9v2 over d9v2 on w00 is +0.0071, within noise (half-width 0.0085). Its control is also stride-mismatched (PR #7 notes). The mean ensemble is lower than d9v2 alone. Mixing Reader v2 into d9v2 (mean) over Reader v2 alone: +0.0008, within noise.

### 6. Reproductions

v8in-1447 over `ink_9um` seed 42 on w00 (+0.0320, clear) and mixing seed 42 into d9v2 lowering it (-0.0317, clear) reproduce what PRs #7 and #8 state, now checked against the noise band.

## Not done

- Threshold transfer across segments: PR #6 part 1 never ran and no maps exist here. Blocked, not a null.
- True paired bootstrap (`kit auc --bootstrap 300 --compare`) for the claims above: needs the maps on a machine that has them. That is the next check, and it may tighten or loosen every verdict above.
- ag405 has only d9v2 on its crop; no reader comparison is possible on the independent sheet yet.
