# sheethug: sheet surfaces through pressed and touching sheets

Makes synthetic 3D sheet stacks whose contacts are fused islands like real pressed sheets, trains a two-scale 3D net on them, and scores sheet lines inside contact zones with a merge-sensitive split recall.

| Field | Value |
| --- | --- |
| Id | `sheethug` |
| Status | Experimental |
| Kind | kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit.sheethug block OUT.npz --seed S`, `python -m kit.sheethug bank DIR --n N --seed S --workers W`, `python -m kit.sheethug train DIR OUT.pt --arm ARM --seed S` (ARM wide or local), `python -m kit.sheethug gate DIR --weights W.pt ... --out F.json`, `python -m kit.sheethug info` |
| Code | `kit/sheethug.py` |
| Tests | `tests/test_sheethug.py` |
| Needs | Python 3.10 or newer, numpy, scipy; scikit-image for scoring; torch for the net; the `synthetic_slices` package at commit `bf8d26f502ed38c188c409d7f3011a7a11c4cf89` (`--no-deps`) for NMS 2. No scroll data |
| Runs on | CPU for blocks: about 12 s for one 192^3 block on one core of a 4-core cloud container (25 Nov 2026). Training on a GPU (about 0.55 s a step at batch 8 on an RTX Pro 6000; CPU about 2 s a step at batch 2) |
| Network | None |
| Writes | `block`: one `.npz`; `bank`: `DIR/block-SEED-I.npz`; `train`: one `.pt` (state and meta); `gate --out`: JSON |
| Go-ahead | Not needed |
| Released | Public, with the November 2026 Progress Prize entry (pending) |
| Checked | 2026-11-25 against commit `bd011dc` |

## What it does

Tracers merge neighbouring windings where two sheets are pressed together. Simulators that draw a pressed contact as a wider band or with a dark line between the sheets teach a local net a cue real scans lack: in our October 2026 measurements on PHerc0139 public open data, local nets reached 0.89 to 0.92 on simulated contacts and 0.49 to 0.52 on real ones. Real pressed bands are about as wide as one sheet (median 7.75 voxels at 9.362 um, IQR 5 to 14.6, against 6.25 where sheets are apart), and most contact area keeps a free face, so the evidence of which sheet is which often lies outside the contact.

`Stack` builds offset sheet height fields in a rotated, bent frame (sheet normals within 0.45 rad of the axial plane, as in a scroll). Fused islands press one to three neighbouring pairs to zero gap over a patch (radius lognormal about 60 voxels), thin both sheets and let them overlap, so the fused band is about 1.2 times a lone sheet, inside the spread of lone-sheet widths. `render` takes the brighter of the two nearest sheets' profiles, so a fused face shows only the dip its drawn edge leaves.

The net reads a 64^3 crop at full resolution and a 256^3 context box at a quarter of the resolution, and predicts papyrus, each sheet's centre surface and the interface between touching sheets. Arm `local` is the same net with the context zeroed, so a test can ask whether context, not band width, separates fused sheets.

Scoring is in 2D axial slices: truth lines by Synthetic-Slices' benchmark rule (skeleton of the labelled papyrus with boundaries between sheets removed), predicted lines by Synthetic-Slices' NMS 2, and a contact zone of papyrus within 3 px of another sheet. Plain F1 at 2 px cannot see a merge when two lines sit 3 to 4 px apart, so **split recall** counts a truth pixel only when a predicted pixel assigned to its own sheet (by nearest truth line) lies within 2 px. The score works on any 2D line map with a sheet-id label image, synthetic or real (for example the organizers' volumetric instance labels).

Everything the generator makes is synthetic. A score on its blocks is model output on synthetic data and says nothing about a real scroll; sheet lines are not a reading.

## When to use it

- To make 3D training or test blocks with exact sheet ids, centres and fused contacts.
- To train and compare surface nets on pressed sheets, with or without wide context.
- To score any line map in contact zones with split recall (synthetic blocks or real instance labels).

Do not use it:

- for whole rolled scrolls with windings, ink and a scan model: use [scrollsim2](scrollsim2.md);
- for 2D hard-case tiles (folds, cracks, edges): use [hardcases](hardcases.md);
- as evidence about real CT on its own: a real claim needs a test on labelled real contacts.

## Quick start

```bash
pip install scipy scikit-image torch
pip install --no-deps git+https://github.com/vincentl065/Synthetic-Slices@bf8d26f502ed38c188c409d7f3011a7a11c4cf89
python -m kit.sheethug bank TRAIN --n 8 --seed 11 --workers 4 --shape 128,128,128
python -m kit.sheethug bank HELD --n 2 --seed 12 --shape 128,128,128
python -m kit.sheethug train TRAIN wide.pt --arm wide --seed 1 --steps 20 --batch 2 --device cpu
python -m kit.sheethug gate HELD --weights wide.pt --out gate.json
```

TRAIN and HELD are any empty scratch folders. This is a smoke run of a few minutes on a CPU: 20 steps teach the net nothing, so read only that every name has finite scores and that the controls sit where they should (oracle near 1, merged well below it). Success: exit 0 and `gate.json` with `wide.pt`, `ridge-sato` and the three controls.

## Checks and controls

`gate` scores three controls beside every map, and each can fail: the oracle (truth lines through the same NMS 2 path) should reach about 0.95 contact split F1 or more; the merge control (papyrus skeleton with sheet ids dropped, a perfect segmenter that never splits) should sit well below the oracle, or the metric cannot see merges; the flip control (the first weights' map mirrored left to right) should score far below its unmirrored F1 over all lines. Treat a read whose controls fail as void.

Tests check that a merged line between two touching sheets loses split recall, that a non-finite map is refused, and that the local arm's context is zero.

Claim label: Model output

## Result so far (Model output, synthetic data only)

25 Nov 2026, a test fixed before it ran: 96 training and 24 held-out blocks of 192^3, three seeds per arm, 4,000 steps at batch 8, axial slices every 16 voxels.

| Arm | Contact split F1 (seeds 1, 2, 3) | Contact split recall | F1, all lines |
| --- | --- | --- | --- |
| wide (256^3 context) | 0.6930, 0.7101, 0.7223 | 0.60 to 0.63 | 0.962 to 0.966 |
| local (context zeroed) | 0.6969, 0.7062, 0.7043 | 0.60 to 0.61 | 0.962 to 0.964 |
| ridge-sato (no learning) | 0.5552 | 0.43 | 0.916 |
| merge control | 0.4395 | 0.33 | |
| oracle | 0.9963 | 0.99 | |

The wide context did **not** help: the lowest wide seed did not beat the highest local seed, so the test failed for the net, while every control passed. What the run does show: the split score separates a merging map (0.44) from a perfect one (0.996), both nets beat a ridge filter by about 0.15 in contact zones, and split recall tops out near 0.62, so most of the gap is still open even in simulation. Simulated contacts have beaten real ones before, so none of this is evidence about real CT.

## Commands and options

### `python -m kit.sheethug`

| Option | Default | Meaning |
| --- | --- | --- |
| `block OUT` | required | Write one block to `OUT` (.npz) |
| `bank DEST` | required | Write N blocks into `DEST` |
| `train BANK OUT` | required | Train one arm on the blocks in `BANK`, weights to `OUT` (.pt) |
| `gate BANK` | required | Score weights, ridge-sato and the controls on the blocks in `BANK` |
| `info` | | Print the constants as JSON |
| `--seed` | required for block and bank; 1 for train | Seed of the block, the bank (block seeds SEED*100000 + i) or the training run |
| `--shape` | `192,192,192` | Block shape z,y,x in voxels |
| `--n` | required | Blocks in a bank |
| `--workers` | 1 | Processes for a bank |
| `--arm` | required | `wide` (with context) or `local` (context zeroed) |
| `--steps` | 3000 | Training steps |
| `--batch` | 4 | Crops per step |
| `--width` | 16 | Channels at the first level |
| `--device` | `auto` | `cuda`, `mps`, `cpu` or `auto` |
| `--weights` | required | One or more `.pt` files from `train` |
| `--out` | none | Gate JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `HugError()` | exception | Nothing | Raised on a refused input: unknown arm, off-grid context centre, non-finite map, over 255 sheets |
| `Stack(seed, shape=SHAPE)` | a Stack (H, T, F, P maps; raster(), describe()) | HugError from raster over 255 sheets | One random sheet stack with fused islands, a function of position. Sheets are offset height fields |
| `render(r, seed)` | uint8 CT, the shape of R["e1"] | Nothing | CT (uint8) of a raster R. Each voxel takes the brighter of its two nearest sheets' profiles (two plies, a |
| `interface(owner)` | bool array, the shape of OWNER | Nothing | Papyrus voxels with a 6-neighbour of another sheet (the face where two sheets touch). |
| `block(seed, shape=SHAPE)` | dict ct, owner, centre, fusion, interface, info | HugError | One synthetic block: dict of ct (uint8), owner (uint8), centre (bool), fusion (float16), interface (bool), |
| `band_widths(b, step=4)` | {"apart": (median, n), "fused": (median, n)} | Nothing | Run lengths along z, not along the sheet normal: a rough check only |
| `save_block(b, path)` | None; writes PATH atomically | OSError | Compressed .npz with info as JSON |
| `load_block(path)` | dict as block() | OSError, KeyError | Reads a block written by save_block |
| `bank(dest, n, seed, shape=SHAPE, workers=1, progress=print)` | list of the N paths | OSError | N blocks with seeds SEED*100000 + i into DEST/block-SEED-i.npz (skips blocks already written). |
| `pooled(ct, ds=CTX_DS)` | (2, Z/DS, Y/DS, X/DS) float32 | Nothing | CT (uint8 0 to 255, or float 0 to 1) mean pooled by DS after padding each axis to a multiple of DS, and the |
| `context_box(pool_, centre, size=CONTEXT, ds=CTX_DS)` | (2, SIZE/DS, SIZE/DS, SIZE/DS) float32 | HugError off the DS grid | The SIZE^3 context box centred on CENTRE (z, y, x; each a multiple of DS) cut from POOL_ (the output of |
| `targets(b, sl)` | (3, *crop) float32: papyrus, centre dilated by 1, interface | Nothing | The training targets of one crop |
| `Sampler(paths, arm, seed, fused_share=0.5)` | a sampler; batch(n) gives (x, context, targets) arrays | HugError for an unknown arm | Random training samples from a bank: a LOCAL^3 crop (half of them centred on a fused voxel when the block |
| `make_net(width=16)` | a torch module; forward(x, context) gives (N, 3, 64, 64, 64) logits | ImportError without torch | Two-scale 3D U-Net. Local path: LOCAL^3 crop, levels at strides 1, 2, 4, 8. Context path: the context box at |
| `pick_device(device='auto')` | "cuda", "mps" or "cpu", or the name given | Nothing | auto picks cuda, then mps, then cpu |
| `train(paths, arm, seed=1, steps=3000, batch=4, lr=0.002, device='auto', width=16, progress=print, log_every=50)` | (net on CPU, meta dict) | HugError on a non-finite loss | Train one arm on bank PATHS; the last step is kept (nothing selects on held-out blocks). Loss: BCE on the |
| `save_net(net, meta, path)` | None; writes PATH atomically | OSError | torch.save of state and meta |
| `load_net(path, device='cpu')` | (net in eval mode on DEVICE, meta) | OSError | weights_only=False: load only files this tool wrote |
| `predict(net, ct, arm, device='cpu', stride=48, batch=4)` | (3, Z, Y, X) float32 probabilities | HugError for a stride off the context grid | Probabilities (3, Z, Y, X) float32 over a whole volume CT (uint8 or float 0 to 1), by LOCAL^3 tiles at |
| `contact_zone(owner, r=CONTACT_R)` | bool array | Nothing | Labelled papyrus pixels within R pixels (8-connected steps) of a pixel of another sheet, in a 2D slice. |
| `truth_lines(owner)` | bool array | Nothing | True centre lines: skeleton of the labelled papyrus with boundaries between sheets removed (Synthetic-Slices' benchmark rule) |
| `ridge_map(img, sigmas=(1.0, 1.5, 2.0, 2.5, 3.0))` | float32 array | Nothing | Sato bright-ridge response, the no-learning baseline (`ridge-sato` in the gate) |
| `nms_lines(prob, mask)` | bool array | HugError (non-finite map, package missing) | Synthetic-Slices' NMS 2 lines of PROB inside MASK (bool); a non-finite map raises HugError. |
| `split_counts(pred, ref_lines, owner, mask, tol=2)` | dict tp_p, n_p, tp_r, n_r, tp_s | Nothing | Counts inside MASK: tp_p and n_p (predicted pixels within TOL of any truth line), n_r (truth line pixels), |
| `scores_of(c)` | dict precision, recall, split_recall, f1, split_f1 | Nothing | Precision, recall, split recall, F1 and split F1 from pooled counts. |
| `slice_eval(prob2d, owner2d, foot2d, tol=2)` | {"contact": counts, "all": counts} | HugError | One axial slice: counts in the contact zone ('contact') and the whole footprint ('all'). |
| `control_probs(owner2d)` | {"oracle": map, "merged": map} | Nothing | Control maps of a slice: 'oracle' (truth lines), 'merged' (skeleton of the papyrus with sheet ids dropped: |
| `axial_slices(Z, step=SLICE_STEP, margin=SLICE_MARGIN)` | list of z indices | Nothing | Every SLICE_STEP from SLICE_MARGIN |
| `pool(counts)` | {zone: counts and scores} | Nothing | Sums counts over slices and blocks, then scores |
| `gate(paths, weights, device='cpu', progress=print, ridge=True)` | {name: {arm, seed, zones}} | HugError | Score each weights file, the ridge filter and the controls on held-out blocks PATHS, in axial slices every |
| `build_parser(ap=None)` | argparse parser | Nothing | The command line |
| `main(argv=None)` | exit code 0 | SystemExit on bad arguments | The command line |

## Inputs

`block` and `bank` take a seed and a shape (z, y, x voxels, default 192^3, voxel 9.362 um nominal). `train` takes a bank folder of `block-*.npz`. `predict` takes a CT volume (uint8 0 to 255 or float 0 to 1, z y x). Scoring takes a 2D map, a 2D sheet-id label image (0 off papyrus) and a bool footprint.

## Outputs

Block `.npz`: `ct` uint8, `owner` uint8 (sheet id plus 1), `centre` bool, `fusion` float16 (0 apart to 1 fused), `interface` bool, `info` JSON (seed, shape, sheets, compact, islands with k0, run, centre, radii, kappa, c; bends). Weights `.pt`: `state` and `meta` (arm, seed, steps, batch, lr, width, device, seconds, final_loss). Gate JSON, per name: `arm`, `seed`, and `zones.contact` and `zones.all` with counts `tp_p`, `n_p`, `tp_r`, `n_r`, `tp_s` and `precision`, `recall`, `split_recall`, `f1`, `split_f1` (fractions 0 to 1).

| Exit code | Meaning |
| --- | --- |
| `0` | Done |
| `1` | A refused input or a failed step (HugError) |
| `2` | Bad arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `stride ... is not a multiple of` | predict's stride is off the context grid | Use a stride that is a multiple of CTX_DS (4) |
| `non-finite map refused before scoring` | NaN or Inf in a probability map | Treat it as the arm's failure; never score it |
| `unknown arm` | an arm other than wide, local or both | Use `--arm wide` or `--arm local` |
| `more than 255 sheets in one block` | owner is uint8 | Use a smaller block |
| `context centre ... is not on the ...-voxel grid` | a crop centre off the pooling grid | Use centres that are multiples of CTX_DS |
| `non-finite loss at step` | training diverged | Lower the learning rate or check the bank; the run is a failure |
| `needs the synthetic_slices package (pip install --no-deps git+https://github.com/vincentl065/Synthetic-Slices@bf8d26f502ed38c188c409d7f3011a7a11c4cf89)` | NMS 2 comes from Synthetic-Slices | Install it at that commit with `--no-deps` |
| `: non-finite probabilities on` | a net produced NaN or Inf on a block | The arm fails; nothing is scored |

## How it works

1. `Stack`: thickness lognormal about THICK_P50 = 6.5 voxels (sigma 0.25, 3.5 to 12); gaps lognormal about GAP_P50 = 8.5 (sigma 0.5, at least 1.5), compact stacks (30 percent) 1.5 to 4; maps every 2 voxels with smooth variation; 0 to 3 islands (none in 15 percent), runs of 1 to 3 pairs, KAPPA 0.15 to 0.5, C 0.55 to 1.0; sheets stacked from the bottom so order holds.
2. `raster`: each voxel's frame position, every nearby sheet's height and thickness by bilinear lookup, the nearest sheet by normalised distance; centre where the owner's distance is at most 0.5 voxel.
3. `render`: two plies and a core per sheet, a soft edge, gap fill and debris, fibre texture, point spread, phase rim, noise and gain, randomized per block.
4. Net: local U-Net (16, 32, 64, 64 channels) with the context branch (64^3 at stride 4, to stride 32 and back to stride 8) cropped to the local footprint and joined at stride 4. BCE (positive weight 3 on centre and interface) plus soft Dice on centre, AdamW 2e-3, OneCycle, flips and y-x swaps, gain, offset and gamma; the last step is kept.
5. `predict`: 64^3 tiles at stride 48 with a sine-squared blend.
6. Score as in "What it does"; CONTACT_R = 3, slices every SLICE_STEP = 16 from SLICE_MARGIN = 8, tolerance 2 px.

## Cost and time

Block 192^3: about 12 s on one CPU core (25 Nov 2026, cloud container). Net 1.2 M parameters at width 16. CPU training about 2 s a step at batch 2; on one RTX Pro 6000, six training runs side by side took 2,209 s for 4,000 steps each (about 0.55 s a step).

## For agents

- **Command:** `python -m kit.sheethug gate HELD_DIR --weights W.pt ... --out F.json`
- **Parse:** `zones.contact.split_f1` and `zones.contact.split_recall` per name in the JSON
- **Rerun:** safe: banks already written are skipped; gate output is overwritten
- **Success:** exit 0 and every name present with finite scores
- **Not a pass:** any synthetic score as evidence about real CT; a read whose controls failed
- **Go-ahead:** not needed for CPU runs; paid GPU training follows your own compute rules
- **Never:** call a sheet line a reading

## Tests

`python -m unittest tests.test_sheethug` (about 10 s with every dependency): determinism and sub-box agreement, sheet order and kept gaps, zero gap in fully fused pairs, centres inside papyrus, context box centring and padding, split recall against a merged line, the non-finite refusal, net shapes and the local arm's context, the gate's names and controls. Tests skip cleanly without scipy, scikit-image, torch or synthetic_slices. Not covered: GPU training.

## History

- 2026-11-25: built and tested on synthetic blocks; released on top of public `bd011dc`.

## Related

[hardcases](hardcases.md) (2D and 3D hard-case layouts), [scrollsim2](scrollsim2.md) (whole scrolls), [Synthetic-Slices](https://github.com/vincentl065/Synthetic-Slices) (vincentl065, MIT code: the truth rule and NMS 2 line extraction this score reuses).
