# letters-training: training data, training, fine-tuning and benchmarks of the letter reader

`scripts/letters/` holds the scripts that make the Greek letter reader's synthetic training lines, train and fine-tune its weights, fetch the public PHerc. 1667 and PHerc. 172 data, and run the benchmarks and control checks behind its published numbers.

| Field | Value |
| --- | --- |
| Id | `letters-training` |
| Status | Current |
| Kind | script folder |
| Area | Letters and titles |
| Run | `python scripts/letters/gen_dataset.py`, `python scripts/letters/realforms.py`, `python scripts/letters/train_linenet.py`, `python scripts/letters/finetune_maps.py`, `python scripts/letters/p1667_fetch.py`, `python scripts/letters/p1667_groups.py`, `python scripts/letters/p1667_mapcrops.py`, `python scripts/letters/p1667_text.py`, `python scripts/letters/p1667_align.py`, `python scripts/letters/eval_p1667.py`, `python scripts/letters/eval_p1667_text.py`, `python scripts/letters/eval_p172.py`, `python scripts/letters/compare_p172.py`, `python scripts/letters/eval_pages.py`, `python scripts/letters/eval_photos.py`, `python scripts/letters/eval_controls.py`, `python scripts/letters/demo_p1667.py` |
| Code | `scripts/letters/` |
| Tests | `tests/test_letter_scripts.py`, `tests/test_letterdata.py`, `tests/test_letterread.py`, `tests/test_letterdemo.py`, `tests/test_letterlines.py` |
| Needs | Python 3.10 or newer, numpy, from a clone with the `reader` extra (`python -m pip install -e ".[reader]"`: numpy, Pillow, tifffile, imagecodecs). Pillow to draw lines and pages. torch only for `train_linenet.py` and `finetune_maps.py train` (the CPU build on Linux without a GPU). scipy and zarr (the `all` extra) for `p1667_groups.py` and `p1667_mapcrops.py`. `pdftotext` (poppler) for `eval_p172.py` and `p1667_text.py`. Data you fetch yourself: Hell-Char and ICDAR 2023 letter crops for `realforms.py`, a clone of Bodillium/Herculaneum-Scroll-Labels for the PHerc. 172 scripts, a PDF of arXiv 2606.29085 for `p1667_text.py`, Perseus TEI texts for decoys |
| Runs on | Any CPU for data, benchmarks and checks; training a release-size model wants a GPU. 20 synthetic lines took 2.2 s with one process (measured 2026-10-16, 4-core 2.8 GHz Xeon cloud container). The guide measured about 137 s per 1,000 synthetic lines per process, a CPU training run of 25 minutes on 4 threads, the `letters-v2-real` recipe at about 8 minutes on one B200, and fine-tuning at 3.1 s a step on 4 threads (about 80 minutes for 1,500 steps), all on 14 October 2026 ([Train your own](../letter-reader.md#train-your-own)) |
| Network | `p1667_fetch.py` and `demo_p1667.py`: the open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`, anonymous HTTPS (the maps are about 1.9 GB; the demo's JPEG about 3.5 MB). Any script given a released weights name: one download from `github.com`, redirected to GitHub's release file host. The others read local files only; Hell-Char, ICDAR, the Bodillium labels and the paper are fetched by you |
| Writes | Only where you point them, by convention under the ignored `work/` folder: shards (`OUT/PREFIX-SEED-NNNN.npz`), glyph banks, `OUT_DIR/linenet.pt`, `linenet.npz`, `train.json`, `ckpt/`, `finetune.json`, fetched maps and labels, group crops and `.npy` windows, reference and decoy JSON, and each benchmark's `--out` JSON. `demo_p1667.py` defaults to `work/letters/demo`. Reruns overwrite |
| Go-ahead | Not needed for CPU runs on public data. Needed for any rented GPU or Modal run (the go-ahead rule, hard rule 8, and the Modal rule, hard rule 11), and for posting weights or numbers |
| Released | Public `main` since 2026-10-14 ([PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57)), with the letter reader release (`letter-reader`) |
| Guide | [letter-reader.md](../letter-reader.md): [Reproduce the benchmarks](../letter-reader.md#reproduce-the-benchmarks), [Train your own](../letter-reader.md#train-your-own), [Fine-tune on your own lines](../letter-reader.md#fine-tune-on-your-own-lines) |
| Checked | 2026-10-16 against commit `e49ec32` |

## What it does

The letter reader ([letterread](letterread.md)) is a small CTC line reader: a convolutional network that turns one band of text into letters, trained from line strings alone (CTC, connectionist temporal classification, needs no letter boxes). Its weights were made and measured with these scripts. They fall into four groups:

1. **Training data.** `letterdata.py` draws synthetic lines of uniform random Greek capitals (24 letters with lunate sigma) from a hand-coded bookhand skeleton, installed fonts and, after `realforms.py` builds a glyph bank, real letter crops from papyrus photographs (Hell-Char, ICDAR 2023). Each line is degraded to look like an ink map or a drawn ink label. `gen_dataset.py` writes them to shards. Random letters teach shapes, not Greek; Greek enters only through the optional language model of [greeklm](greeklm.md).
2. **Training.** `train_linenet.py` trains the network with torch and exports `linenet-v1` numpy weights (BatchNorm folded) that the reader loads. `finetune_maps.py` fine-tunes any exported or released model on real lines of known text.
3. **Public benchmark data.** `p1667_fetch.py`, `p1667_groups.py`, `p1667_mapcrops.py`, `p1667_text.py` and `p1667_align.py` fetch PHerc. 1667's public ink maps and labels, cut the labels into letter groups by a model-free rule, cut the same places from the maps, parse the published text and place published lines on the maps.
4. **Benchmarks and checks.** `eval_p1667.py`, `eval_p1667_text.py`, `eval_p172.py` with `compare_p172.py`, `eval_pages.py`, `eval_photos.py` and `eval_controls.py` score the reader against references, decoys, nulls and blank pages; `demo_p1667.py` reads one public map in minutes.

Every string these scripts read is Model output: a letter hypothesis, never a reading. Their references are machine or community transcriptions of drawings, not a papyrologist's reading. They are for public data only; never run them on a prize-eligible scroll in public work.

## When to use it

- Making training lines and training or fine-tuning reader weights.
- Reproducing a row of the guide's [How well it reads](../letter-reader.md#how-well-it-reads) table, or comparing two weights on the same rows with a paired bootstrap.
- Checking that the reader's controls still fail when they should (`eval_controls.py`, `eval_pages.py` blank pages, `eval_photos.py` blank pages).
- Choosing a checkpoint on the PHerc. 172 dev half (`eval_p172.py --split dev`), never on the data you report.

Do not use it:

- To read an image: use [letterread](letterread.md).
- To check an install: use [letterdemo](letterdemo.md), which needs no clone.
- To cut training lines from your own transcriptions or score weights on lines kept apart: use [letterlines](letterlines.md) (its lines feed `finetune_maps.py`).
- To build the letter language model: use [greeklm](greeklm.md).
- On maps of a prize-eligible scroll in public: reads there are possible findings and stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).

## The scripts

| Script | What it does | Needs |
| --- | --- | --- |
| `letterdata.py` | Library, no command line: synthetic lines (`make_sample`), whole pages (`make_page`, looks `map`, `mask`, `photo`), the skeleton hand, font search (`font_roots`, `LETTER_FONT_DIRS`) | numpy, Pillow |
| `gen_dataset.py` | Writes synthetic line bands to `.npz` shards (uint8 images, texts, letter boxes); `--bank` draws a share of lines from real letter crops | numpy, Pillow |
| `realforms.py` | Builds a glyph bank from Hell-Char and ICDAR 2023 crops (`build`), prints its stats (`stats`), draws a preview sheet (`preview`) | numpy, Pillow |
| `train_linenet.py` | Trains the CTC line reader on shards and exports `linenet.npz` | torch |
| `finetune_maps.py` | Fine-tunes exported or released weights on real lines (`train`), mixing in synthetic shards | torch |
| `p1667_fetch.py` | Fetches PHerc. 1667's 19 maps at 2.4 um and the six labelled segments' ink labels from the open-data bucket; resumable | Standard library |
| `p1667_groups.py` | Cuts the six ink labels into letter groups by a fixed rule, with a PNG per group for blind transcription | numpy, scipy, zarr, Pillow |
| `p1667_mapcrops.py` | Cuts the same windows from the maps (`--wide`: taller; `--region`: whole labelled regions), with an alignment check | numpy, tifffile, zarr |
| `p1667_text.py` | Parses the published transcription (arXiv 2606.29085, columns 5 to 22) into one string per papyrus line, `?` for restored or illegible letters | pdftotext |
| `p1667_align.py` | Places published lines on whole maps (`read`, `align`, `crops`, `show`), tested against shifted decoy texts | numpy |
| `eval_p1667.py` | Reads the letter groups from the labels or the maps and scores character error (`read`); paired bootstrap of two results (`compare`) | numpy |
| `eval_p1667_text.py` | Reads unlabelled PHerc. 1667 maps whole and scores the reads against the published text and decoys (`cut`, `read`, `decoys`, `score`, `compare`) | numpy |
| `eval_p172.py` | Reads the PHerc. 172 hand-drawn labels and scores them against the labeller's preliminary transcription, with a dev and test split | numpy, Pillow, pdftotext |
| `compare_p172.py` | Paired bootstrap of two `eval_p172.py` results | numpy |
| `eval_pages.py` | End-to-end check on synthetic pages (letter size, deskew, lines and reading together) and on blank pages | numpy, Pillow |
| `eval_photos.py` | Photograph-like pages: polarity, tilt and a quarter turn, and blank pages | numpy, Pillow |
| `eval_controls.py` | Counts each status on map windows as stored and tile-shuffled (`windows`), and on blank pages (`blanks`) | numpy |
| `demo_p1667.py` | Reads one PHerc. 1667 segment's small public map JPEG and writes the result and an overlay | numpy, Pillow |

## Quick start

```bash
python scripts/letters/gen_dataset.py OUT --n 20 --shard 10 --procs 1 --seed 0
```

- `OUT`: a folder for the shards, such as `work/letters/data/try`.

On 2026-10-16 (synthetic lines only, 4-core cloud container) it printed:

```
1/2 OUT/shard-0000-0000.npz 1s
2/2 OUT/shard-0000-0001.npz 2s
```

Each shard holds 10 lines: uint8 bands 36 rows tall (the network's band at a 16 px letter height), their texts (such as `ΑΝΒ`, `ΔΩΧ`) and each letter's horizontal extent; `gen_dataset.load_shard(path)` reads one back. It worked when the exit code is 0 and `OUT` holds `n / shard` files. The whole recipes, from data to a chosen checkpoint, and every benchmark command are in the guide's [Train your own](../letter-reader.md#train-your-own) and [Reproduce the benchmarks](../letter-reader.md#reproduce-the-benchmarks).

## Checks and controls

Every benchmark script carries a control that can fail:

- **Chance floors.** `eval_p1667.py` scores each read against references permuted across groups as well as the true ones; `eval_p172.py` and `eval_pages.py` match read lines to true lines in order. A real error must sit below the permuted one.
- **Nulls.** Every read reports letters kept on its own tile-shuffled and phase-randomised copies; a read whose letters are not well above its nulls is noise.
- **Decoy texts.** `eval_p1667_text.py` scores reads of unlabelled maps against the published text and against 99 (`N_DECOYS`) decoys each of four kinds (`shifted`, `words`, `corpus`, `shuffled`). Its test U1 passes only with at least 3 (`PAIR_FLOOR`) ordered pairs of lines matching the text, more than every decoy. On the thirteen PHerc. 1667 segments without labels it found no such pairs (Model output, a test with little power; [How well it reads](../letter-reader.md#how-well-it-reads)). `p1667_align.py` accepts a placed column only at p 0.01 or less (`P_ACCEPT`) against 99 shifted decoys.
- **Blank inputs.** `eval_controls.py blanks` and the blank pages of `eval_pages.py` and `eval_photos.py` must give `none` or `too_few`. Measured 14 October 2026 with `letters-v2-real`: 47 of 48 blank-page reads were `none` and one was `weak`; on 60 tile-shuffled windows of the w013 map the old verdict passed 17, all `too_few` under the 10-letter floor (`letter_reader_checks` in [`results.json`](../results.json)).
- **Held-out choice.** Checkpoints are chosen on the PHerc. 172 dev half and reported once on the test half; `finetune_maps.py` keeps the last step of a fixed schedule, so nothing is chosen on test lines.
- **Paired intervals.** `compare_p172.py` and `eval_p1667.py compare` resample lines, groups or segments (20,000 draws by default) and report B minus A with a 95 % interval; a difference whose interval includes 0 is not resolved.
- **What a result looks like** (Model output, 14 October 2026, [benchmarks](../letter-reader.md#benchmarks-letters-v2-ccby-against-letters-v2-real)). `letters-v2-ccby` against `letters-v2-real`: 0.043 against 0.017 on the PHerc. 1667 drawings (+0.026, interval -0.018 to +0.079, not resolved) and 0.462 against 0.376 free-ends error on the same groups from the maps (+0.085, interval +0.017 to +0.155, worse). The six labelled PHerc. 1667 segments are in `ink_9um`'s training labels, so their maps may be cleaner than maps of new text.
- **Alignment check.** `p1667_mapcrops.py` writes the mean map value under labelled ink against the rest, also for the label shifted by up to 3 grid pixels; the unshifted label should score best.

Claim label: Model output, for every read, character error and status these scripts produce; Null, for the unlabelled-map text test that found no ordered pairs.

## Commands and options

Run every script from the repository root. Options a script does not list here it refuses with a usage error. `--weights` everywhere takes a released name (`letters-v2-ccby`, `letters-v2-real`, downloaded once and SHA-256 checked) or a `linenet-v1` `.npz` path.

### `python scripts/letters/gen_dataset.py`

```
usage: gen_dataset.py [-h] [--n N] [--shard SHARD] [--seed SEED]
                      [--domain {None,map,mask}] [--procs PROCS] [--bank BANK]
                      [--bank-split {train,val}] [--p-bank P_BANK]
                      [--prefix PREFIX]
                      out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Folder for the shards, made if missing |
| `--n N` | `20000` | Lines to write; `n // shard` shards are written |
| `--shard SHARD` | `1000` | Lines per shard file |
| `--seed SEED` | `0` | Seed; shard i uses seed x 100003 + i, and the file name carries the seed |
| `--domain DOMAIN` | none | `map` (ink-map look) or `mask` (drawn-label look); by default each line's look is drawn at random. The usage line lists `None`, but `--domain None` is refused (`invalid choice: 'None'`, seen 2026-10-16): leave the option out instead |
| `--procs PROCS` | the number of CPUs (`os.cpu_count()`) | Worker processes |
| `--bank BANK` | none | A `realforms.py` bank: draw a share of lines from real letter crops |
| `--bank-split BANK_SPLIT` | `train` | `train`, or `val` (the 21 held-out papyri) |
| `--p-bank P_BANK` | `0.6` | Share of lines (styles) drawn from the bank |
| `--prefix PREFIX` | `shard` | Shard file name prefix: files are `PREFIX-SEED-NNNN.npz` |

### `python scripts/letters/realforms.py`

```
usage: realforms.py build [-h] [--hellchar HELLCHAR] [--icdar ICDAR]
                          [--icdar-optional]
                          out
usage: realforms.py stats [-h] bank
usage: realforms.py preview [-h] [--n N] [--split {train,val}] bank out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `build out` | required | The bank `.npz` to write (its folder is made first); prints the bank's stats as JSON |
| `--hellchar HELLCHAR` | none | Hell-Char data folder (`hellchar.csv` and `cliplets/`); give it, `--icdar` or both |
| `--icdar ICDAR` | none | Extracted ICDAR 2023 Greek letters dataset (COCO JSON and images) |
| `--icdar-optional` | off | Skip unreadable ICDAR photographs and boxes, and drop ICDAR if it fails as a whole |
| `stats bank` | required | Print a bank's stats JSON |
| `preview bank out` | required | Draw a PNG of lines made from the bank alone to `out`, for a person to look at |
| `--n N` | `12` | Lines of each look (`map` and `mask`) in the preview |
| `--split SPLIT` | `train` | Draw from the `train` or `val` papyri |

### `python scripts/letters/train_linenet.py`

Usage (from the docstring; `--help` needs torch): `python scripts/letters/train_linenet.py DATA_DIR OUT_DIR --val VAL_DIR [options]`.

| Option | Default | Meaning |
| --- | --- | --- |
| `data` | required | Folder of shards to train on (every `.npz` in it) |
| `out` | required | Output folder: `linenet.pt`, `linenet.npz`, `train.json`, and `ckpt/` with `--keep` |
| `--val VAL` | none | Folder of synthetic validation shards, scored every `--eval-every` steps |
| `--steps STEPS` | `4000` | Training steps |
| `--batch BATCH` | `48` | Lines per batch |
| `--lr LR` | `2e-3` | Peak learning rate of the one-cycle schedule (AdamW) |
| `--threads THREADS` | `4` | torch CPU threads |
| `--seed SEED` | `0` | torch and numpy seed |
| `--resume RESUME` | none | A `linenet.pt` state to start from |
| `--eval-every EVAL_EVERY` | `500` | Steps between validations (and kept checkpoints) |
| `--device DEVICE` | `cpu` | `cpu` or `cuda` |
| `--amp` | off | bfloat16 autocast on CUDA (CTC loss stays float32) |
| `--channels CHANNELS` | `32,64,96,128,192` | 2D convolution channels; the released models use `48,96,160,192,256` |
| `--dilations DILATIONS` | `1,2` | Dilations of the 1D residual layers; the released models use `1,2,4` |
| `--workers WORKERS` | `0` | DataLoader worker processes; keep 0 on macOS and Windows |
| `--val-real VAL_REAL` | none | Second validation folder of real-letter lines from held-out papyri (`real_val_cer`) |
| `--keep` | off | Also keep each evaluation's weights as `OUT_DIR/ckpt/linenet-stepNNNNNN.npz` |

### `python scripts/letters/finetune_maps.py`

```
usage: finetune_maps.py train [-h] --weights WEIGHTS --out OUT [--steps STEPS]
                              [--batch BATCH] [--p-map P_MAP] [--lr LR]
                              [--seed SEED] [--threads THREADS]
                              [--device DEVICE]
                              lines shards
```

| Option | Default | Meaning |
| --- | --- | --- |
| `lines` | required | `LINES.npz` from `p1667_align.py crops` or `python -m kit letterlines build` |
| `shards` | required | Folder of `gen_dataset.py` shards mixed into every batch |
| `--weights WEIGHTS` | required | The model to start from: a released name or a `linenet-v1` `.npz` |
| `--out OUT` | required | Output folder: `linenet.npz` and `finetune.json` |
| `--steps STEPS` | `1500` | Steps of the fixed schedule; at least 20; the last step is the model |
| `--batch BATCH` | `24` | Lines per batch |
| `--p-map P_MAP` | `0.5` | Share of each batch taken from `lines`; the rest are synthetic |
| `--lr LR` | `3e-4` | Peak learning rate (AdamW, one-cycle, a tenth of the steps warming up) |
| `--seed SEED` | `0` | Seed |
| `--threads THREADS` | `4` | torch CPU threads |
| `--device DEVICE` | `cpu` | `cpu` or `cuda` |

### `python scripts/letters/p1667_fetch.py`

```
usage: p1667_fetch.py [-h] [--labels-only] out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Folder for `maps/wNNN.tif` and `labels/wNNN/z/1/`, such as `work/p1667` |
| `--labels-only` | off | Fetch the six label sets alone (under 1 MB, no maps): enough for the drawings row |

### `python scripts/letters/p1667_groups.py`

```
usage: p1667_groups.py [-h] labels_dir out_dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `labels_dir` | required | `p1667_fetch.py`'s `OUT/labels`: `wNNN/z/1` of each `inklabels.zarr` |
| `out_dir` | required | Where `groups.json`, `png/` and `npy/` go, such as `work/p1667/groups` |

### `python scripts/letters/p1667_mapcrops.py`

```
usage: p1667_mapcrops.py [-h] [--wide | --region] groups_dir maps_dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `groups_dir` | required | `p1667_groups.py`'s output folder |
| `maps_dir` | required | `p1667_fetch.py`'s `OUT/maps`, holding `wNNN.tif` |
| `--wide` | off | Windows 2 letter heights (`WIDE_PAD_Y`) taller above and below, for `eval_p1667.py --source map-wide` |
| `--region` | off | Each segment's whole labelled region, padded by 1 letter height (`REGION_PAD`), for `--source map-region` |

### `python scripts/letters/p1667_text.py`

```
usage: p1667_text.py [-h] pdf out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `pdf` | required | A local copy of arXiv 2606.29085 (v1) |
| `out` | required | The reference JSON to write, such as `work/p1667/text.json` (177 lines, 1,752 visible letters for the v1 PDF, per the guide) |

### `python scripts/letters/p1667_align.py`

```
usage: p1667_align.py read [-h] --weights WEIGHTS --out OUT npy_dir
usage: p1667_align.py align [-h] --out OUT read text
usage: p1667_align.py crops [-h] --columns COLUMNS [--best] --out OUT
                            align npy_dir
usage: p1667_align.py show [-h] align
```

| Option | Default | Meaning |
| --- | --- | --- |
| `read npy_dir` | required | Folder of whole maps on the 38 um grid (`eval_p1667_text.py cut`); reads each map's columns |
| `--weights WEIGHTS` | required | The reader, recorded as given |
| `--out OUT` | required | `READ.json`, `ALIGN.json` or `LINES.npz`, by action |
| `align read text` | required | `READ.json` and the published text JSON; writes the alignment with each column's decoy p value |
| `crops align npy_dir` | required | Cut bands of the accepted published lines at the reader's working scale |
| `--columns COLUMNS` | required | Published columns to cut, such as `9,10,12` |
| `--best` | off | One segment per column: the one with the most anchor lines, then points |
| `show align` | required | Print an alignment's per-column summary (`align` prints it too, with the alignment's digest) |

### `python scripts/letters/eval_p1667.py`

```
usage: eval_p1667.py read [-h] --weights WEIGHTS [--lm LM]
                          [--source {label,map,map-wide,map-region}]
                          [--letter-px {given,auto}] [--out OUT]
                          groups_dir refs
usage: eval_p1667.py compare [-h] [--key {ink_only,with_lm}]
                             [--level {group,segment}]
                             [--metric {plain,free_ends,free_ends_any}]
                             [--n N]
                             a b
```

| Option | Default | Meaning |
| --- | --- | --- |
| `read groups_dir refs` | required | `p1667_groups.py`'s folder and the references JSON `{"agreed": {"w013-g000": "ΚΑΙ", ...}}` |
| `--weights WEIGHTS` | required | The reader, recorded as given |
| `--lm LM` | none | Language model `.npz`; adds the `with_lm` decode (not with `map-region`) |
| `--source SOURCE` | `label` | `label` (drawings), `map`, `map-wide` (the reader finds the line) or `map-region` (whole regions) |
| `--letter-px LETTER_PX` | `given` | `given`: the segment's measured height; `auto`: the scale search |
| `--out OUT` | none | Full result JSON; its folder is made first |
| `compare a b` | required | Two `read` results on the same groups; prints B minus A |
| `--key KEY` | `ink_only` | `ink_only` or `with_lm` |
| `--level LEVEL` | `group` | Resample `group`s or whole `segment`s |
| `--metric METRIC` | `plain` | `plain`, `free_ends` (the maps' measure) or `free_ends_any` |
| `--n N` | `20000` | Bootstrap resamples |

### `python scripts/letters/eval_p1667_text.py`

```
usage: eval_p1667_text.py cut [-h] maps_dir out_dir [segments ...]
usage: eval_p1667_text.py read [-h] --weights WEIGHTS --letter-px LETTER_PX
                               --out OUT
                               npy_dir
usage: eval_p1667_text.py decoys [-h] --out OUT reference corpus [corpus ...]
usage: eval_p1667_text.py score [-h] --out OUT read decoys
usage: eval_p1667_text.py compare [-h] a b
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cut maps_dir out_dir` | required | Cut whole 2.4 um maps to the 38 um grid (block 16) as `.npy` |
| `segments` | all | Segments to cut, such as `w030` |
| `read npy_dir` | required | Read each cut map once, columns and lines found |
| `--weights WEIGHTS` | required | The reader, recorded as given |
| `--letter-px LETTER_PX` | required | `86`, `auto`, or a `groups.json` whose per-segment letter heights are used |
| `--out OUT` | required | The output JSON of `read`, `decoys` or `score` |
| `decoys reference corpus` | required | The `p1667_text.py` reference and one or more Greek TEI texts for the `corpus` decoys |
| `score read decoys` | required | Score a read against the text and every decoy |
| `compare a b` | required | Compare two `score` results |

### `python scripts/letters/eval_p172.py`

```
usage: eval_p172.py [-h] --weights WEIGHTS [--lm LM] [--lm-weight LM_WEIGHT]
                    [--down DOWN] [--split {all,dev,test}]
                    [--columns {off,auto}] [--out OUT]
                    repo
```

| Option | Default | Meaning |
| --- | --- | --- |
| `repo` | required | A local clone of Bodillium/Herculaneum-Scroll-Labels |
| `--weights WEIGHTS` | required | The reader |
| `--lm LM` | none | Language model `.npz` (`python -m kit greeklm build`) |
| `--lm-weight LM_WEIGHT` | `0.5` | Its weight |
| `--down DOWN` | `4` | Downsample the label grid by this factor before reading (speed only) |
| `--split SPLIT` | `all` | `dev` (first half of segments sorted by id, rounded up: for choosing), `test` (the rest: for reporting) or `all` |
| `--columns COLUMNS` | `off` | `off` or `auto`; the guide's row 5 uses `auto` |
| `--out OUT` | none | Full result JSON; keep it in `work/` |

### `python scripts/letters/compare_p172.py`

```
usage: compare_p172.py [-h] [--key {ink_only,with_lm}]
                       [--level {line,segment}] [--n N]
                       a b
```

| Option | Default | Meaning |
| --- | --- | --- |
| `a`, `b` | required | Two `eval_p172.py --out` results; prints B minus A |
| `--key KEY` | `ink_only` | `ink_only` or `with_lm` |
| `--level LEVEL` | `line` | Resample reference `line`s or whole `segment`s |
| `--n N` | `20000` | Bootstrap resamples |

### `python scripts/letters/eval_pages.py`

```
usage: eval_pages.py [-h] --weights WEIGHTS [--pages PAGES] [--seed SEED]
                     [--lm LM] [--lm-weight LM_WEIGHT] [--text TEXT]
                     [--columns {off,auto}] [--out OUT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--weights WEIGHTS` | required | The reader |
| `--pages PAGES` | `24` | Synthetic pages (every third in the drawn-label look); 6 blank pages are always added |
| `--seed SEED` | `11` | Page seed |
| `--lm LM` | none | Language model `.npz`; adds `cer_with_lm` |
| `--lm-weight LM_WEIGHT` | `0.5` | Its weight |
| `--text TEXT` | none | Greek TEI `.xml` or plain text for the line texts (at least 1,000 letters); default random letters |
| `--columns COLUMNS` | `off` | `off` (as the recorded numbers) or `auto` |
| `--out OUT` | none | Full result JSON |

### `python scripts/letters/eval_photos.py`

```
usage: eval_photos.py [-h] --weights WEIGHTS [--pages PAGES] [--blanks BLANKS]
                      [--seed SEED] [--nulls NULLS] [--out OUT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--weights WEIGHTS` | required | The reader |
| `--pages PAGES` | `12` | Photograph-like pages |
| `--blanks BLANKS` | `12` | Pages with no letters of each kind |
| `--seed SEED` | `31` | Page seed |
| `--nulls NULLS` | `4` | Null copies per read |
| `--out OUT` | none | Full result JSON |

### `python scripts/letters/eval_controls.py`

```
usage: eval_controls.py windows [-h] --weights WEIGHTS [--letter-px LETTER_PX]
                                [--window H W] [--copies COPIES] [--out OUT]
                                map
usage: eval_controls.py blanks [-h] --weights WEIGHTS [--pages PAGES]
                               [--seeds SEEDS [SEEDS ...]] [--out OUT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `windows map` | required | A map image the reader loads, such as w013 averaged 16 by 16 |
| `--weights WEIGHTS` | required | The reader |
| `--letter-px LETTER_PX` | `86.0` | Letter height in map pixels |
| `--window H W` | `520 1000` | Window size in pixels |
| `--copies COPIES` | `3` | Tile-shuffled copies of the whole map |
| `--out OUT` | none | Full result JSON |
| `blanks` | none | Read `eval_pages.py`'s blank pages |
| `--pages PAGES` | `12` | Blank pages per seed |
| `--seeds SEEDS ...` | `21 22` | Page seeds |

### `python scripts/letters/demo_p1667.py`

```
usage: demo_p1667.py [-h] [--segment SEGMENT] [--weights WEIGHTS] [--out OUT]
                     [--crop Y0 Y1 X0 X1] [--letter-px LETTER_PX] [--lm LM]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--segment SEGMENT` | `w013` | PHerc. 1667 segment id, w011 to w041 |
| `--weights WEIGHTS` | `letters-v2-ccby` (`DEFAULT_WEIGHTS`) | The reader |
| `--out OUT` | `work/letters/demo` | Folder for the map, `SEGMENT.json` and `SEGMENT-overlay.png` |
| `--crop Y0 Y1 X0 X1` | none | Rows and columns on the 38 um grid |
| `--letter-px LETTER_PX` | `86.0` (`LETTER_PX`) | Letter height in grid pixels, or `auto` |
| `--lm LM` | none | Language model `.npz`, shown beside the ink-only read |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `LETTER_FONT_DIRS` | unset | Extra font folders for `letterdata.py`, separated by `:` (`;` on Windows), searched before the system ones |
| `WINDIR`, `SystemRoot`, `LOCALAPPDATA` | as the system sets them | Windows font folders `letterdata.py` searches |
| `KIT_LETTER_WEIGHTS` | unset | Where released weights names are cached, as for [letterread](letterread.md) |

## Python API

Not applicable: these are command-line scripts; `letterdata.py`, `realforms.py` and `gen_dataset.load_shard` are imported by the other scripts and the tests, not a supported library.

## Inputs

| Input | Where from | Notes |
| --- | --- | --- |
| Fonts | Installed TrueType or OpenType fonts with the Greek capitals | Monospaced fonts are left out; different fonts give different lines from one seed |
| Hell-Char crops | [ipavlopoulos/diachronic-greek-letterforms](https://github.com/ipavlopoulos/diachronic-greek-letterforms) at the commit the guide names | CC BY 4.0; 21 papyri held out as `val` (id hash mod 10, `VAL_MOD`) |
| ICDAR 2023 crops | The Zenodo record the guide names | CC BY-NC 4.0; weights trained on them inherit it |
| PHerc. 1667 maps and labels | The open-data bucket, via `p1667_fetch.py` | CC BY-NC 4.0; 19 maps (about 1.9 GB) and 6 label sets |
| Published PHerc. 1667 text | A PDF of arXiv 2606.29085 you download | Columns 5 to 22 |
| Group references | Your own blind transcriptions of the group PNGs | `{"agreed": {GROUP: LETTERS}}`, the reader's 24 capitals only |
| PHerc. 172 labels | A clone of [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) | CC BY-NC-SA 4.0; nothing is copied into this repository |
| Training lines | `gen_dataset.py` shards, `p1667_align.py crops` or `kit letterlines build` | Bands 36 rows tall at a 16 px letter height |

Every text scored must be in the reader's alphabet `ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ` (lunate sigma), with `?` only where a script allows it; a Latin look-alike or a final sigma stops the run with the alphabet printed.

## Outputs

| Script | Prints | Files |
| --- | --- | --- |
| `gen_dataset.py` | One progress line per shard | `OUT/PREFIX-SEED-NNNN.npz`: `flat`, `widths`, `height`, `texts` (JSON), `boxes` (JSON) |
| `realforms.py` | The bank's stats JSON | The bank `.npz`; a preview PNG |
| `train_linenet.py` | Losses and `EVAL ...` lines | `linenet.pt`, `linenet.npz` (`linenet-v1`), `train.json` (settings, losses, validation numbers including `real_val_cer`), `ckpt/` |
| `finetune_maps.py` | Progress | `linenet.npz`, `finetune.json` (file names and SHA-256 of start and result, the lines' record, settings) |
| `p1667_fetch.py` | Each file fetched | `maps/`, `labels/` |
| `p1667_groups.py` | Stats JSON | `groups.json`, `png/`, `npy/` |
| `p1667_mapcrops.py` | Alignment check | `map-npy/` and `map-check.json`; `map-wide-npy/` and `map-wide.json`; `map-region-npy/` and `map-region.json` |
| `eval_p1667.py read` | The guide row it reproduces and its measure first, the summary JSON last | `--out` JSON |
| `eval_p172.py` | Its row and error first, one line per segment, the summary JSON last (`\| tail -1`) | `--out` JSON with `weights` and `weights_sha256` |
| `compare_p172.py`, `eval_p1667.py compare` | One JSON line: `cer_a`, `cer_b`, `diff_b_minus_a`, `ci95`, `share_b_worse`, `units`, `level`, `resamples` | None |
| `eval_pages.py`, `eval_photos.py`, `eval_controls.py` | One JSON line per page or window, the summary JSON last | `--out` JSON |
| `demo_p1667.py` | The reader's text summary | `OUT/SEGMENT-ds8.jpg` and its `.json` note, `OUT/SEGMENT.json`, `OUT/SEGMENT-overlay.png` |

| Exit code | Meaning |
| --- | --- |
| `0` | The script finished. A benchmark exits 0 whatever its score: read the summary |
| `1` | A stop with a message (a `SystemExit` text under Failure modes), or an uncaught error with a traceback, such as torch missing |
| `2` | A usage error from the argument parser, including the scripts' own `--steps` and `--hellchar` checks |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the script's table under Commands and options |
| `finetune_maps.py: error: --steps: give at least 20 (the one-cycle schedule warms up over a tenth of them)` | `--steps` under 20 (seen 2026-10-16) | Use 20 or more; the default is 1500 |
| `realforms.py: error: give --hellchar and/or --icdar` | `build` with no source (seen 2026-10-16) | Give a source folder |
| `ModuleNotFoundError: No module named 'torch'` | `train_linenet.py` or `finetune_maps.py train` without torch | Install torch as the guide says |
| `SHARDS: no shard .npz files; make the synthetic lines with scripts/letters/gen_dataset.py` | `finetune_maps.py` found no shards and `--p-map` is below 1 | Make shards first |
| A message naming a character outside the alphabet, with the alphabet printed | A reference or training line holds a Latin look-alike, a `Σ`, a final `ς` or other text | Write the reader's 24 capitals, lunate `Ϲ` for every sigma |
| `REFS: no such file. Write the references first: docs/letter-reader.md, the References paragraph under the PHerc. 1667 tests, says how ({"agreed": {"w013-g000": "ΚΑΙ", ...}})` | `eval_p1667.py read` without a references file | Write the references as the guide says |
| `GROUP: line centre Y is outside its crop (N rows)` | A group's centre does not fall in its crop | Rerun `p1667_groups.py` and `p1667_mapcrops.py` |
| `the two results score different groups` | `eval_p1667.py compare` on results from different references or sources | Compare reads of the same groups |
| `no matched lines in either result` | `compare_p172.py` on results with no matched lines (a traceback) | Check both `--out` files |
| `corpus too short: N letters for 99 decoys of V` | `eval_p1667_text.py decoys` with too little corpus text (a traceback) | Give more Perseus texts |
| `reference lines longer than 60 letters would overflow the int8 scores` | A reference line over 60 letters (a traceback) | Check the reference |
| `no transcription PDF under REPO/Transcriptions & Readings` | `eval_p172.py` given a clone without the transcription | Clone the full Bodillium repository |
| `PATH: too little Greek text` | `eval_pages.py --text` with under 1,000 letters | Give a longer text |
| `wNNN: N segment folders in the bucket` | `p1667_fetch.py` or `demo_p1667.py` found no folder, or several, for a segment | Check the segment id; the bucket may have changed |
| `wNNN: N 2.4 um maps` | `p1667_fetch.py` found no map, or several | The bucket may have changed; report it |
| `wNNN: N small 2.4 um maps in the bucket` | `demo_p1667.py` found no small JPEG, or several | Try another `--segment` |
| `KEY: N bytes received, M expected; nothing kept` | A cut-off download | Rerun; finished files are kept |
| `p1667_groups.py reads the ink labels with zarr (ERROR): python -m pip install -e ".[all]" (Python 3.11 or newer), or python -m pip install zarr` | zarr is missing | Install it |
| `no CSV in ROOT` | `--hellchar` names a folder without `hellchar.csv` | Point it at the data folder |
| `size (W, H) does not match the record's (W, H)` | An ICDAR photograph differs from its record (two are truncated) | Add `--icdar-optional` |
| `no usable crops` | No letter survived the bank build | Check the source folders |
| `bank split SPLIT has no LETTERS` | A bank split lacks some letters | Build the bank from more papyri |
| A benchmark exits 0 with a high error or a status of `none` | The weights or settings read badly, or a reference is wrong | Read the controls first; a score is meaningful only beside them |

## How it works

- **Synthetic lines** (`letterdata.make_sample`): letters 16 px tall (`H_PX`) in a band from 1.1 letter heights above the centre to 1.15 below (`BAND_TOP`, `BAND_BOT`), drawn at 3 times supersampling (`SS`), 3 to 18 letters, about 7 % of lines blank (`p_blank` 0.07), degraded to the `map` or `mask` look.
- **Glyph bank** (`realforms.py`): crops scaled so each papyrus's median plain letter is 48 px (`BANK_H`), papyri hashing to 0 mod 10 (`VAL_MOD`) kept for validation.
- **Network** (`train_linenet.py`): 2D convolutions with BatchNorm over the band, a collapse to one row, dilated 1D residual convolutions and a 25-way CTC head (24 letters and the blank), stride 4; exported with BatchNorm folded into `linenet-v1`. AdamW with a one-cycle schedule.
- **Fine-tuning** (`finetune_maps.py`): a published `?` is a wildcard that may be any letter or none, so the loss never asks for a letter in a hole; each batch mixes `--p-map` real lines with synthetic ones.
- **PHerc. 1667 groups** (`p1667_groups.py`): label level 1 block-averaged by 8 (`D`) to about 38 um, ink pieces of at least 500 px (`MIN_AREA`), pieces joined when their centres differ by under 0.5 letter heights and their gap is under 0.6.
- **Text test** (`eval_p1667_text.py`): Smith-Waterman local alignment (match +1, mismatch -1, gap -1, `?` 0) of every read line against every published line, against 99 decoys of each kind; the ordered-pair test U1 uses `PAIR_MIN` 5, `PAIR_STEP` 2 and `PAIR_FLOOR` 3.
- **Alignment** (`p1667_align.py`): gutters at least 0.15 below neighbouring peaks (`GUTTER_DEPTH`), local alignment with `FLOOR` 3 and `ANCHOR` 5, a fitted row and margin per published column, crops with a 0.6 letter-pitch margin (`MARGIN`), accepted at p 0.01 or less against 99 shifted decoys.

The method's reasons are in the guide's [How it works](../letter-reader.md#how-it-works) and the [letter reader log](../logs/2026-10-14-letter-reader.md).

## Cost and time

From the guide (14 October 2026, 4-core cloud container unless named): synthetic lines about 137 s per 1,000 per process and about 10 MB per 1,000 lines; bank lines about 70 s per 1,000; the CPU recipe's data about 30 minutes with 4 processes and 0.65 GB; the CPU training run 25 minutes on 4 threads; the `letters-v2-real` recipe's 600,000 lines extrapolate to about 17 process-hours and 5.7 GB, and its training took about 8 minutes on one B200; fine-tuning 3.1 s a step on 4 threads, about 80 minutes for the default 1,500 steps; `p1667_fetch.py` about 1.9 GB of maps. On 2026-10-16 here, 20 synthetic lines took 2.2 s; an `eval_pages.py` run of 2 pages was stopped after more than 3 minutes on a shared container, so its time is Not measured.

GPU training, and any CPU job over about an hour (such as the default fine-tune), runs on Modal under the Modal rule (hard rule 11): write a run spec in `docs/compute/modal-specs/` and give Chase a prompt; Claude cloud sessions cannot reach Modal. Renting compute needs Chase's go-ahead first.

## For agents

- **Command:** `python scripts/letters/gen_dataset.py OUT --n N --seed S` for lines; the benchmark commands are copied exactly from the guide's [Reproduce the benchmarks](../letter-reader.md#reproduce-the-benchmarks); every benchmark takes `--out FILE.json` and prints its summary JSON as its last line (`| tail -1`).
- **Parse:** the last stdout line of each benchmark (its summary JSON, such as `ink_only` `cer_matched_lines` for `eval_p172.py`); `diff_b_minus_a`, `ci95` and `share_b_worse` from the compare scripts; `real_val_cer` in `train.json`.
- **Rerun:** Safe; outputs are overwritten. `p1667_fetch.py` keeps finished files and resumes. `gen_dataset.py` with the same seed on the same machine repeats its lines; other fonts change them.
- **Success:** Exit code 0 and a summary whose controls pass: the error below the permuted-reference error, letters above the nulls, blank pages `none` or `too_few`.
- **Not a pass:** A checkpoint chosen on the data it is reported on; a difference whose interval includes 0; a fine-tune judged on its own training lines; PHerc. 1667 map numbers read as performance on new text (those segments are in `ink_9um`'s training labels); a `weak` status.
- **Go-ahead:** Renting a GPU or running on Modal, and posting weights or numbers, need Chase's yes.
- **Never:** Call a read or a score a reading; commit weights, shards, maps or banks to git; run these on a prize-eligible scroll's maps in public work; train for hours on a laptop CPU instead of a Modal spec.

## Tests

```bash
python -m unittest tests.test_letter_scripts tests.test_letterdata -v
```

`tests/test_letterdata.py` (7 tests, 5.8 s on 2026-10-16) covers the skeleton glyphs, line shapes and boxes, blank lines, seeded repeats, pages, the photo look and a shard round trip. `tests/test_letter_scripts.py` checks that the guide's commands and options exist in the scripts and run when pasted, that the benchmark scripts print their guide row first and refuse letters outside the alphabet (the fine-tune before importing torch), the font search, and the citation file. `tests/test_letterread.py` runs `eval_controls.py` and `eval_photos.py` on small inputs, and `tests/test_letterdemo.py` holds the demo's copy of the skeleton hand equal to `letterdata.py`'s. Training is not run by the tests (no torch there), and no test downloads the PHerc. 1667 or PHerc. 172 data.

## History

- 2026-10-14: `letters-v2-ccby` (CC BY 4.0, trained without ICDAR data) becomes the default weights the benchmark and demo scripts use (`0366ed7`).
- 2026-10-14: fine-tuning on your own lines (`finetune_maps.py` takes `letterlines` output) (`33a0ad3`).
- 2026-10-14: the guide's commands run as written, with benchmark script checks (`e30ff76`).
- 2026-10-14: `eval_photos.py` for photographs, polarity and turns (`c502445`); `eval_controls.py` for the status codes (`05c59cc`).
- 2026-10-14: first public release with the guide, model card, benchmarks and demo (`19d2f95`, [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57)).

## Related

- [letterread](letterread.md): the reader these weights run in.
- [letterlines](letterlines.md): training lines from your own transcriptions, for `finetune_maps.py`, and scores on lines kept apart.
- [greeklm](greeklm.md): the optional letter language model used with `--lm`.
- [letterdemo](letterdemo.md): the offline install check, drawn with the same skeleton hand.
- [letter-reader.md](../letter-reader.md): the guide, with the model cards, benchmark tables and full recipes.
- [The letter reader log](../logs/2026-10-14-letter-reader.md) and `letter_reader_checks` in [`results.json`](../results.json): every measured number with its conditions.
