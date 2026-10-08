# Letter reader: full-scale synthetic training on Modal

Written 8 October 2026. Not run. Guide and plan: [`docs/letter-reader.md`](../../letter-reader.md). Code: [`scripts/letters/modal_letters.py`](../../../scripts/letters/modal_letters.py).

## 1. Goal

Train the CTC line reader of `kit/letterread.py` at full scale: about 600,000 synthetic Greek lines (17 times the CPU prototype's 36,000), a wider network (1,483,241 parameters against 593,849) and a third dilated block (each output frame sees about five letters instead of three). Plan stage 2. The job reads and writes synthetic data only: no scroll data, maps or labels, so no preregistration is needed (rule 3 covers target maps).

## 2. Inputs

None downloaded. Each container clones `https://github.com/ChaseHendrick/Scrolls.git` at the pushed commit and renders lines with fonts from Debian packages (DejaVu, FreeFont, Liberation always; Noto and the Greek Font Society packages when the image has them).

## 3. Code and commands

Branch `claude/project-thread-9o445w` (or `main` once merged). The entrypoint refuses to run without `--allow-gpu` and refuses uncommitted changes under `scripts/letters` or `kit`.

```bash
cd Scrolls && git checkout claude/project-thread-9o445w && git pull
# smoke run first: 4,000 lines, 200 steps, a few minutes
modal run scripts/letters/modal_letters.py --allow-gpu --run letters-smoke --train-lines 4000 --val-lines 1000 --containers 2 --steps 200
# full run
modal run scripts/letters/modal_letters.py --allow-gpu --run letters-v1
mkdir -p work/letters/letters-v1
for f in linenet.npz train.json train.log command.txt; do modal volume get scrolls-letters letters-v1/model/$f work/letters/letters-v1/; done
modal volume get scrolls-letters letters-v1/model/ckpt work/letters/letters-v1/
```

Defaults of the full run: 30 CPU containers make 20,000 training lines each (seeds 1 to 30) plus 4,000 validation lines (seed 9001), then one GPU trains 30,000 steps at batch 128, learning rate 0.002 (one-cycle), channels 48,96,160,192,256, dilations 1,2,4, bfloat16 autocast, 6 batch workers, keeping the weights at every evaluation (every 2,000 steps, 15 checkpoints of a few MB each).

## 4. Machine, time and cost

Rates from [modal-pricing.md](../modal-pricing.md) (Sourced fact, read 7 October 2026); the times are estimates (Interpretation).

| Step | Machine | Estimate | Cost estimate |
| --- | --- | --- | --- |
| Generation | 31 CPU containers, 8 cores and 8 GiB each | 600,000 lines at about 0.084 vCPU-seconds each (measured here: 36,000 lines in 758 s on 4 vCPUs), about 3 to 5 minutes per container | 0.40 to 1.50 USD |
| Training | one B200 (`LETTERS_GPU`, default B200 per the owner's GPU preference), 8 cores, 64 GiB | 30,000 steps; likely limited by batch assembly on the CPU, 10 to 40 minutes; hard timeout 60 minutes | 1.20 to 7.14 USD (container 7.14 USD/h) |
| Smoke run | same, tiny | a few minutes including image builds | under 0.75 USD |

Expected total about 2.5 to 4 USD; worst case with every timeout about 9.5 USD. **Stop and ask the owner before passing 10 USD.** This network is small, so an L4 (`LETTERS_GPU=L4`, container 1.24 USD/h) would cost less and may be nearly as fast; the default follows the owner's stated preference for B200s. Log every app in the compute ledger.

## 5. Outputs

Modal Volume `scrolls-letters`, folder `letters-v1/` (data shards about 4.3 GB, model folder a few MB). Copy back only `model/linenet.npz`, `model/ckpt/`, `train.json`, `train.log` and `command.txt` into `work/letters/letters-v1/` (ignored by git). Weights never go in git (rule 6). Delete the data shards from the Volume after the checks if storage matters (0.09 USD per GiB-month beyond the free tier).

## 6. Checks

The run worked only if all of these hold. Each can fail.

1. `train.log` shows `params 1483241`, the loss falls, and `train.json` has an `evals` list ending at step 30000.
2. Synthetic validation character error rate at the last eval is below the CPU prototype's 0.112 at step 4,000 (see [the log](../../logs/2026-10-08-letter-reader.md); the validation sets differ in seed and size, so treat a gap under 0.01 as a tie).
3. On a CPU, choose the checkpoint on the dev half of the PHerc. 172 drawings, then score that one checkpoint on the test half. It passes only if its test character error rate, ink only, is below the prototype's 0.760 (step 1,000, chosen the same way) and the null control still holds (letters kept on the drawings well above both nulls). On the prototype, synthetic error kept falling while error on the drawings rose, so never choose by synthetic validation.
   ```bash
   git clone --depth 1 https://github.com/Bodillium/Herculaneum-Scroll-Labels work/bodillium
   for w in work/letters/letters-v1/ckpt/*.npz; do
     python scripts/letters/eval_p172.py work/bodillium --weights $w --split dev --out ${w%.npz}-dev.json | tail -1
   done
   # pick the lowest dev ink_only cer_matched_lines, then once:
   python scripts/letters/eval_p172.py work/bodillium --weights BEST.npz --split test --out work/letters/letters-v1/p172-test.json
   ```
4. `python -m unittest tests.test_letterread` passes, and `python -m kit letterread` loads the new weights.

If check 3 fails while 2 passes, the synthetic data is the bottleneck, not scale: report it as a null and move to plan stage 3 (real letterforms).

## 7. Prompt for the runner

> In ChaseHendrick/Scrolls, check out branch claude/project-thread-9o445w and follow docs/compute/modal-specs/2026-10-08-letter-reader-training.md exactly: smoke run first, then the full run, stopping to ask before total Modal spend passes 10 USD. Copy back only linenet.npz, the ckpt folder, train.json, train.log and command.txt into work/letters/letters-v1/, run the checks in section 6 on CPU, and report the final synthetic validation error, letters per blank line, the checkpoint chosen on the PHerc. 172 dev half, its test-half character error rate with its null counts, the app IDs and the total cost. Commit nothing from work/.

## Outcome

Not run yet.
