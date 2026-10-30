# Parting

Parting tells the same papyrus layer from the next one where two layers touch in a CT scan of a Herculaneum scroll or fragment. At a contact it takes a point `a` on one layer, a second point `a2` on the same layer and a point `b` on the next layer at the same distance, and scores the pair (a, a2) and the pair (a, b); a higher score means "same layer". Tracers switch sheets at exactly such places, where two layers press into one thick band.

It is a small classifier (a soft vote of gradient boosting and a one-layer MLP) on 669 numbers per point pair: the Vesuvius Challenge's base dinovol tokens (`scrollprize/dinovol_ps8_9.6um_101626`) at the points, CT profiles along their normals and along the segment between them, and base dinovol's own token cosine. That cosine alone is the control every result is compared against. Parting scores given point pairs; it does not trace and does not read ink. Its scores are model output, not a reading.

Full page: [`docs/tools/parting.md`](../../docs/tools/parting.md).

## What it has shown, and what it has not

Each test below was frozen before any of its 3D CT was read, on fragments Parting and base dinovol never trained on, against the Vesuvius Challenge team's traced layer segments (Model output; [log](../../docs/logs/2026-10-29-parting-fragment-contact.md)):

| Fragment (scroll) | Touching sites, layer pairs | Parting AUC | Base dinovol cosine AUC | Gain (2.5 % bound) | Rule: gain at least +0.05, bound above 0 |
| --- | --- | --- | --- | --- | --- |
| PHerc1667Cr1Fr3 (PHerc1667) | 203, 7 | 0.960 | 0.915 | +0.045 (+0.020) | FAIL |
| PHercParis1Fr34, Frag3 (PHerc. Paris 1) | 150, 5 | 0.8952 | 0.8392 | +0.0560 (+0.0368) | PASS |
| PHercParis2Fr143 (PHerc. Paris 2) | 270, 9 | 0.9754 | 0.9651 | +0.0103 (-0.0005) | FAIL |

So: one pass in three fragments tried. On Frag3 the gain was positive on all five layer pairs, but three of them gained less than +0.05 alone. Where base dinovol is already near 0.97 there is little room left. At fused contacts (under 3 voxels apart) Parting adds little (0.633 against 0.611 on 38 Frag3 sites). The fragments are flat layer stacks, not rolled scrolls.

## This release

Code under the Apache License 2.0 ([LICENSE](LICENSE)). The trained model file used for the results above, `parting-v1.joblib` (sha256 `f0684ab2...`), is on Hugging Face as [`SharpMeow/parting-v1`](https://huggingface.co/SharpMeow/parting-v1) under CC BY-NC 4.0, like the scans it was trained on; it is not stored in this repository. You can also fit the same recipe on your own feature runs with `fit`, and score with `--trust-model`; `frag3 --sites-only` rebuilds the published Frag3 site list from public data and checks it against its hash.

Parting does not copy anyone else's code or weights. At run time it downloads, each pinned by sha256: the base dinovol checkpoint from Hugging Face (its model page states no license, so it is never redistributed here), and villa's dinovol model code (MIT, Vesuvius Challenge) in the copy that [hercUNet](https://github.com/jimmylomro/hercUNet) vendors (MIT, Jaime Lomeli-Rodriguez) at commit `de4acb7`. Scans and traced layers are the Vesuvius Challenge open data (CC BY-NC 4.0), read live.

## Run it headless

```bash
pip install numpy scipy scikit-learn==1.9.1 joblib torch timm einops huggingface_hub
# 1. contact sites from traced layers, in stack order (geometry only)
python3 scripts/parting/parting.py sites --layer L0.vcps --layer L1.vcps --shape Z Y X --out SITES.json
# 2. features (a CUDA GPU is much faster; --resample 3.24:7.91 for a fine scan)
python3 scripts/parting/parting.py features --sites SITES.json --volume ZARR_LEVEL_URL --device cuda --out RUN
# 3. fit on other layers, then score with the gate
python3 scripts/parting/parting.py fit --run TRAIN_RUN --out MY.joblib
python3 scripts/parting/parting.py score --run RUN --model MY.joblib --trust-model --sites SITES.json --verdict --out READOUT.json
# the published Frag3 sites, rebuilt from public data (CPU, about 1 GB download, no CT read)
python3 scripts/parting/parting.py frag3 --model MODEL.joblib --out OUT --sites-only
```

Every command writes JSON; `score` prints `primary`, `permutation_gate` and `verdict` (PASS, FAIL or VOID). Exit code 0 means the command finished; read `verdict` for the result. Tests: `python3 -m unittest tests.test_parting`.

Measured 2026-10-30: features for 283 sites took about 4 minutes on one RTX PRO 6000; the Frag3 site rebuild took 4 minutes on a 4-core CPU.
