# Phantoms and the static viewer (lane E)

Two tools, both numpy only, both runnable without any scroll data.

## `kit phantom`: synthetic carbon ink with known truth

A phantom is a small surface volume (depth, height, width) built to look, to a detector, like a flattened papyrus sheet: a recto fibre layer and a verso fibre layer at right angles, a smooth brightness field across the sheet, per-voxel noise, and carbon ink strokes (random lines and arcs in rows of letter-sized cells) on the top surface. The ink adds a small density step in the top layers and a small thickness bump, both below the noise by default, because carbon ink is close to papyrus in density. The stroke mask is the label, so the truth of every pixel is known.

The strokes are not letters of any script. A score on a phantom says nothing about a scroll (label: Model output on synthetic data).

```bash
python3 -m kit phantom make OUT --shape 256 256 --depth 16 --seed 7 --letter-px 64   # volume.npy ink.npy mask.npy meta.json
python3 -m kit phantom stress --n 4 --shape 256 256 --depth 16 --letter-px 64          # baseline detector, forward and depth-reversed
python3 -m kit phantom calibrate --n 10 --shape 256 256 --letter-px 64 --quality 0.3 --block-px 32  # AUC spread between phantoms vs block bootstrap
```

- `stress` runs `surface_detector`, a transparent baseline (top-surface band minus sheet interior). On the depth-reversed volume it should fall to or below 0.5: the same control rule as `kit auc`. Plug any detector in by scoring its map on `ink.npy` and `mask.npy` with `kit.auc.score_array`.
- `calibrate` draws N phantoms, scores a simulated reader of one fixed quality (blurred truth plus correlated noise) on each, and compares the between-phantom 95 % half width of AUC with the mean block-bootstrap half width that `kit auc --bootstrap` would report on one phantom. A ratio near 1 says the one-segment interval is honest for that geometry; well below 1 says it is too narrow.

Prior art checked: `docs/NOVELTY.md`, `docs/tricks.md`, `docs/logs/2026-10-07-literature.md` and `docs/papers.json` hold no synthetic phantom with known ground truth. Organizer and community ink work trains and scores on hand labels of real segments. Untested idea: tune phantom contrast so the baseline matches a real reader's AUC, then use it to size how many segments a ranking needs.

## `kit view`: one HTML file, no server

```bash
python3 -m kit view OUT.html A=a.npy B=b.npy C=c.tif --labels ink.npy --mask mask.npy --png OUT.png
```

Each map is percentile ranked inside the mask (readers on different scales compare), embedded as a PNG data URI. The page switches reader, overlays the disagreement (per-pixel standard deviation of the ranks) or a reader minus the first reader, toggles label outlines and the mask, and reads values under the cursor. It also prints rank correlations and the AUC of each map on the (downsampled) view. `--png` writes the same panels side by side. Maps from a target scroll must never be committed or shared; the page header says the content is model output, not a reading.

## Demo

`bash scripts/phantom-demo.sh` (writes to `/tmp/phantom-demo`, logs commands in `commands.log`). Results: [`logs/2026-10-07-phantom-demo.md`](logs/2026-10-07-phantom-demo.md); panels: [`assets/phantom-viewer-demo.png`](assets/phantom-viewer-demo.png).
