# segzoo: modern segmentation models next to nnU-Net, with licenses, trainers and controls

`python -m kit segzoo` lists twelve segmentation model families (nnU-Net, MedNeXt, Swin UNETR, Auto3DSeg, SegFormer, DINOv2 and v3, SAM 2, MedSAM2, Mamba) with license and fit; `scripts/segzoo/` trains them inside nnU-Net and scores them against controls.

| Field | Value |
| --- | --- |
| Id | `segzoo` |
| Status | Experimental |
| Kind | kit command,script folder |
| Area | Training |
| Run | `python -m kit segzoo`, `python scripts/segzoo/segzoo_nnunet.py`, `python scripts/segzoo/segzoo_sam2.py`, `python scripts/segzoo/segzoo_probe.py` |
| Code | `kit/segzoo.py`, `scripts/segzoo`, `kit/cli.py` (`cmd_segzoo`) |
| Tests | `tests/test_segzoo.py`, `tests/test_segzoo_models.py` |
| Needs | `kit segzoo`: Python 3.10 or newer, standard library only. `scripts/segzoo/`: torch (checked with 2.14.1, CPU build), numpy, and per family nnunetv2 2.8.1, monai 1.6.1, transformers 5.20.1, Pillow; `segzoo_sam2.py` needs the `sam2` package (1.1.0) or MedSAM2's fork. `kit segzoo env` says which are present |
| Runs on | `kit segzoo`: any CPU, under a second. Training and inference: a CUDA GPU for real data (Modal, AGENTS.md rule 11); CPU works for smoke runs. Measured 2026-10-17 on a 4-core Xeon cloud container: the model tests take about 81 s; an SS2DUNet forward pass on one 128 x 128 slice about 5 s |
| Network | `kit segzoo`: none. `segzoo_probe.py features` and `segzoo_nets.FrozenFeatures` download the named model from `huggingface.co` once (DINOv3 needs a logged-in account with approved access); `segzoo_sam2.py follow` downloads its checkpoint from `huggingface.co` when given a Hugging Face id |
| Writes | `kit segzoo datalist`: `datalist.json` and `task.yaml` in `--out`. `segzoo_nnunet.py shim`: `segzoo_shim.py` in nnU-Net's trainer folder (or `--target`). `segzoo_sam2.py` and `segzoo_probe.py`: the `--out` file only. Otherwise it prints only |
| Go-ahead | Not needed for the code; Needed before any paid GPU run (Modal budget) and before releasing weights trained from a family whose weights are research only |
| Released | Public `main` from the PR that adds this page (17 October 2026); not a Progress Prize release |
| Checked | 2026-10-17 against commit `fa6e640` and the datalist validation fix |

## What it does

Chase asked on 17 October 2026 to add nnU-Net "where needed", plus NVIDIA Auto3DSeg, MedSAM2, DINOv3, MedNeXt, Swin UNETR, SegFormer and SS2DNet or other Mamba-based models. "Where needed" here means: where a family could plausibly beat what a tool uses now, on known-answer data, and where its license allows what we would do with it. This tool is the place where those families live, so that a benchmark can swap one in with one change and everything else held fixed.

It has two parts:

- **`kit segzoo`** (standard library) is a registry. For each family it records the package and version, the code and weights licenses, whether the weights are gated, whether a tool trained from it could be released under a permissive license (`release_ok`), the devices it runs on, how it would fit this repository's work (surfaces, ink, sheet following, letters), the published evidence for it, and a verdict: `baseline`, `benchmark`, `control`, `probe`, `private benchmark`, `private probe` or `not now`. `kit segzoo env` reports which families this Python can run, without importing anything. `kit segzoo datalist` turns an nnU-Net v2 raw dataset into the datalist and task file NVIDIA's Auto3DSeg (MONAI AutoRunner) reads, with the same fold split every time.
- **`scripts/segzoo/`** (torch) holds the code that runs them: nnU-Net v2 trainer classes that swap in MedNeXt, Swin UNETR, SegResNet, SegFormer or an SS2D U-Net while keeping nnU-Net's data, loss, ignore label and inference; a pure-PyTorch selective scan and SS2D block (the Mamba-style layer, no CUDA extension needed); a SAM 2 or MedSAM2 sheet follower with a scorer and a copy-seed control; and a frozen-feature probe that puts a logistic head on DINOv2 or DINOv3 features.

It does not ship trained weights, it does not decide that a family is better, and it does not run anything on scroll data by itself. Every number a model here produces is model output, and an ink map made with any of them is model output, not a reading.

Terms: **nnU-Net** is the self-configuring U-Net framework the community's surface model m7 is built with (ResEnc L preset). **MedNeXt** is a U-Net built from ConvNeXt blocks. **Swin UNETR** is a U-Net with a Swin transformer encoder. **Auto3DSeg** is MONAI's automatic pipeline that trains SegResNet, DiNTS and Swin UNETR and ensembles them. **SegFormer** is a 2D transformer segmenter with a light MLP decoder. **DINOv2** and **DINOv3** are self-supervised image backbones from Meta. **SAM 2** is Meta's promptable video segmenter; **MedSAM2** is its fine-tune on 3D medical images. **SS2D** is VMamba's 2D selective scan, four scan directions over an image; **SS2DNet** and **U-Mamba** are networks built from such Mamba layers. See [GLOSSARY.md](../../GLOSSARY.md).

## When to use it

- Before adding a new segmentation model anywhere: `kit segzoo show ID` says whether its license allows a release and what evidence exists.
- To train a challenger to an nnU-Net model on the same dataset and plans: `segzoo_nnunet.py shim`, then `nnUNetv2_train ... -tr nnUNetTrainer_SZMedNeXtB` (or another class from `segzoo_nnunet.py list`).
- To run NVIDIA Auto3DSeg on a dataset already in nnU-Net form: `kit segzoo datalist RAW --out DIR`, then point AutoRunner at `DIR/task.yaml`.
- To ask whether SAM 2 or MedSAM2 can follow labeled sheets through a CT cube from one seeded slice: `segzoo_sam2.py follow`, then `score`, which compares it with copying the seed to every slice.
- To ask, on a CPU, whether a frozen DINOv2 or DINOv3 backbone helps a small 2D task (single letters, triage windows): `segzoo_probe.py features`, then `fit`.

Do not use it:

- To score a surface prediction against labels: use the surface scorers named on the [AutoPipeline page](autopipeline.md).
- To score an ink map: use [`auc`](auc.md), with the reversed-depth control.
- To run m7 or the released ink models as they are: the [AutoPipeline](autopipeline.md) runs them.
- To release a model trained from SegFormer, DINOv3 or MedSAM2 weights: their licenses are not permissive (`release_ok` is false); the prize requires a permissive license for released tools.

## Quick start

```bash
python -m kit segzoo list
python -m kit segzoo show mednext
python -m kit segzoo env
python -m kit segzoo datalist RAW --out AUTO --folds 5
python scripts/segzoo/segzoo_nnunet.py list
```

`RAW` is an nnU-Net v2 raw dataset folder (`dataset.json`, `imagesTr/`, `labelsTr/`); `AUTO` is a new folder for Auto3DSeg's files. Run on 17 October 2026 with a six-case synthetic dataset, it printed (excerpts):

```
id          verdict            dims                 weights        name
nnunet      baseline           2D, 3D               release ok     nnU-Net v2 (ResEnc M, L, XL presets)
primus      benchmark          3D                   release ok     Primus V2 (transformer, ships in nnunetv2 2.8.1)
mednext     benchmark          2D, 3D               release ok     MedNeXt (ConvNeXt U-Net), sizes S, B, M, L
...
segformer   private benchmark  2D                   research only  SegFormer (Mix Transformer encoder, MLP decoder)
dinov3      private probe      2D                   research only  DINOv3 (ViT S/B/L/H/7B with patch 16, ...)
...
mednext     ready    monai 1.6.1
medsam2     missing  sam2 missing
umamba      missing  mamba_ssm missing, causal_conv1d missing
wrote AUTO/datalist.json and task.yaml: 6 cases, folds [0, 1, 1, 2, 2]
note: label value 2 is nnU-Net's ignore label; Auto3DSeg treats every label as a class, so mask it out of the loss or relabel it before AutoRunner
nnUNetTrainer_SZMedNeXtB       mednext-b      2D/3D  adamw lr 0.001 wd 0.0001
```

It worked when `list` shows twelve families, `env` shows `ready` for the families you mean to run, and `datalist` writes both files (the `folds` list counts cases per fold).

## Checks and controls

Each runnable part carries a control that can fail:

- **Trainers:** a challenger trained with a `nnUNetTrainer_SZ...` class differs from the nnU-Net baseline only in the network (and the optimizer its paper used), so a preregistered comparison has one change per arm. The comparison itself, with its held-out data and the null arm (the baseline retrained the same way), is set in the preregistration, not here.
- **SAM 2 follower:** `score` reports, per labeled sheet, Dice on each slice, whether the sheet kept its identity, the first slice where it hopped to another sheet, and coverage, and the same numbers for the copy-seed control (the seed slice repeated through the cube). `beats_control` is true only when the follower's mean Dice is above the control's. On the tests' two flat sheets the control keeps identity on every slice, so a follower that hops loses to it.
- **Frozen probe:** `fit` trains 20 heads on shuffled training labels and reports their accuracy on the test set (`control_shuffled_labels`); a probe has no signal unless its lower 95% bound is above that control's maximum. With `--against`, it also gives the paired difference against another method on the same items, with a bootstrap interval and a verdict (better, worse, no clear difference).
- **Selective scan:** the chunked scan is checked against a step-by-step loop, values and gradients (tests, about 4e-5 and 3e-6).
- **Dataset conversion:** malformed metadata, fewer than two folds, an empty dataset, duplicate case/channel files, and a label with the wrong file ending fail before either output is written. Synthetic regression tests check exit code 2 and preservation of existing output files. Valid datasets keep the same hash folds and paths.

The registry's evidence lines are sourced: each family lists its paper or repository, and the margins quoted from them (such as MedNeXt L above ResEnc L on six of six datasets in the nnU-Net Revisited table, arXiv:2404.09556) are the papers' numbers. None of them was measured on scroll CT.

Claim label: Sourced fact for the registry's licenses and published numbers; Interpretation for its fit and verdict fields; Model output for anything a model here predicts.

## Commands and options

### `python -m kit segzoo`

```
usage: python -m kit segzoo [-h] [--out OUT] [--folds FOLDS]
                            [--modality {CT,MRI}] [--json]
                            {list,show,env,datalist} [name]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `action` | required | `list` the families, `show` one, `env` (which can run here), `datalist` (Auto3DSeg files) |
| `name` | none | show: a family id; datalist: the nnU-Net raw folder |
| `--out OUT` | none | datalist: folder for datalist.json and task.yaml |
| `--folds FOLDS` | `5` | datalist: number of folds, at least 2; hash splits can leave a fold empty |
| `--modality MODALITY` | none | datalist: Auto3DSeg modality (default CT when dataset.json names a CT channel, else MRI) |
| `--json` | off | print JSON |

### `python scripts/segzoo/segzoo_nnunet.py`

| Option | Default | Meaning |
| --- | --- | --- |
| `action` | required | `list` the trainer classes, or write the `shim` module so `nnUNetv2_train -tr` finds them |
| `--target` | nnU-Net's `training/nnUNetTrainer` folder | shim: folder to write `segzoo_shim.py` into |

### `python scripts/segzoo/segzoo_sam2.py follow CUBE --seed SEED --key K --out OUT`

| Option | Default | Meaning |
| --- | --- | --- |
| `cube` | required | CT cube, `.npy` (Z, Y, X) |
| `--seed` | required | `.npy` (Y, X) labels on the key slice, one id per sheet, 0 background |
| `--key` | required | index of the seeded slice along `--axis` |
| `--axis` | `0` | axis to step along: 0, 1 or 2 |
| `--model` | `sam2` | `sam2` (Apache-2.0) or `medsam2` (research-only weights) |
| `--config` | `configs/sam2.1/sam2.1_hiera_t.yaml` | the SAM 2 model config |
| `--checkpoint` | `facebook/sam2.1-hiera-tiny` | a Hugging Face id or a local checkpoint file |
| `--prompt` | `box` | `box` (each sheet's bounding box) or `mask` (the seed mask itself) |
| `--device` | `cuda` | torch device |
| `--out` | required | output `.npz` with `labels`, `seed` and `info` |

`python scripts/segzoo/segzoo_sam2.py score RESULT TRUTH [--json]`: `RESULT` is the `.npz` from `follow`, `TRUTH` a `.npy` (Z, Y, X) of instance labels; `--json` prints one line.

### `python scripts/segzoo/segzoo_probe.py`

| Option | Default | Meaning |
| --- | --- | --- |
| `features IMAGES` | required | `.npz` with `images` (n, H, W) or (n, 3, H, W), uint8 or float in [0, 1]; `labels`, `groups`, `ids` copied through |
| `--model` | `facebook/dinov2-small` | Hugging Face id of a DINOv2 or DINOv3 model |
| `--revision` | none | model commit to pin |
| `--size` | `224` | input side in pixels |
| `--device` | `cpu` | torch device |
| `fit TRAIN TEST` | required | two feature `.npz` files from `features` |
| `--against` | none | JSON `{"name": ..., "hits": {id: 0 or 1}}` of another method on the same test items |
| `--seed` | `0` | bootstrap and control seed |
| `--out` | required | output `.npz` (features) or `.json` (fit) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `family(name)` | The registry dict of one family | `KeyError` for an unknown id | Fields are `segzoo.FIELDS`; ids are `segzoo.IDS` |
| `installed(module)` | Version string, `''` when importable without metadata, or `None` | Nothing | Uses `importlib.util.find_spec`; never imports the package |
| `env_report()` | `{family id: {"ready": bool, "packages": {import name: version or None}}}` | Nothing | For this Python |
| `fold_of(case, folds)` | Fold number of a case id | `ValueError` when folds is not an integer of at least 2 | From the sha256 of the id: fixed, independent of file order and machine |
| `build_datalist(raw, folds=5, modality=None)` | `(datalist, task, summary)` dicts | `ValueError` for any problem in the raw folder (see Failure modes) | Reads an nnU-Net v2 raw dataset folder |
| `task_yaml(task)` | `task.yaml` text | Nothing | Flat `key: value` lines AutoRunner reads; no yaml package needed |
| `write_datalist(raw, out, folds=5, modality=None)` | The summary dict | `ValueError` as `build_datalist`, `OSError` when `out` cannot be written | Writes `datalist.json` and `task.yaml` |
| `cmd_segzoo(args)` | Exit code 0 or 2 | Nothing | The `kit segzoo` command |
| `build_parser(p)` | The parser | Nothing | Adds the options to an `argparse` parser |
| `main(argv=None)` | Exit code | Nothing | Runs `kit segzoo` from a list of arguments |

The scripts are imported by adding `scripts/segzoo` to `sys.path`:

```python
from segzoo_nets import build, names, multiple_of, FrozenFeatures   # build("mednext-b", 1, 2, dims=3)
from segzoo_nnunet import TRAINERS, write_shim                     # TRAINERS["nnUNetTrainer_SZMedNeXtB"]
from segzoo_ss2d import selective_scan, selective_scan_ref, SS2D, VSSBlock, SS2DUNet
from segzoo_sam2 import follow, score, load_predictor
from segzoo_probe import run_fit, fit_softmax, paired, permutation_control
```

`build(name, in_ch, out_ch, dims=3)` knows `mednext-s|b|m|l`, `swinunetr`, `swinunetr-v2`, `segresnet`, `segformer-b0` to `segformer-b5` (2D) and `ss2dunet` (2D); `multiple_of(name)` gives the patch side each needs to divide (Swin UNETR and SegFormer 32, MedNeXt 16, SegResNet and SS2DUNet 8). `FrozenFeatures(model_id).features(images)` returns the class token joined to the mean patch token. `follow(predictor, cube, seed, key, ...)` returns `(labels, info)`; `score(labels, truth, seed, key, axis)` returns the per-sheet scores and the control. `run_fit(train, test, against=None)` returns the probe's result dict.

## Inputs

- **`kit segzoo datalist`:** an nnU-Net v2 raw folder: `dataset.json` with `channel_names`, `labels`, `numTraining` and `file_ending`; `imagesTr/CASE_0000.nii.gz` (one file per channel, `_0000`, `_0001`, ...) and `labelsTr/CASE.nii.gz`. `channel_names` keys must be `"0"`, `"1"`, ... with no gaps. Only names are read, never the images. Supported endings are `.nii.gz`, `.nii`, `.nrrd`, `.mha`, `.tiff`, `.tif` and `.png`; this converter does not support `.b2nd`. Both images and labels must use the declared ending. Older datasets may omit `file_ending` and use `modality` instead of `channel_names`; duplicate case/channel files still fail. At least one case and two folds are required; check the printed fold counts before training because hashing does not guarantee nonempty folds.
- **Trainers:** a dataset nnU-Net has planned and preprocessed (`nnUNetv2_plan_and_preprocess`). Patch sides must divide by the network's `multiple_of`; 2D-only networks need a `2d` configuration.
- **`segzoo_sam2.py`:** a CT cube as `.npy` (Z, Y, X), any dtype (scaled to 0 to 255 per cube); a seed slice `.npy` (Y, X) of integer sheet ids; for `score`, the full instance labels of the cube, same shape. The tests use flat synthetic sheets; real known-answer cubes are instance-labeled public surface cubes.
- **`segzoo_probe.py`:** images as above; `labels` (class names), `groups` (for example a papyrus id, so cross-validation never splits one), `ids`.

## Outputs

- `kit segzoo list` prints one line per family (`--json`: a list of the registry dicts); `show` prints one family's fields; `env` prints `ready` or `missing` per family with versions.
- `datalist.json`: `{"training": [{"image", "label", "fold", "case"}], "testing": []}`; `image` is a list when the dataset has more than one channel. `task.yaml`: `name`, `task`, `modality`, `datalist`, `dataroot`, `num_fold`.
- `segzoo_sam2.py follow`: `.npz` with `labels` (uint16, the cube's shape), `seed`, `info` (JSON: key, axis, prompt, empty slices, model). `score` prints JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `objects` | dict | Per seeded sheet: `dice` (mean over slices), `identity_kept` (fraction of slices where the best-overlapping true sheet is the seeded one), `first_hop` (first slice index away from the key where it is not, or null), `coverage` |
| `control` | dict | The same for the copy-seed control |
| `mean`, `control_mean` | number | Mean Dice over sheets, follower and control |
| `beats_control` | bool | Follower mean above control mean |

- `segzoo_probe.py fit` writes JSON: `accuracy`, `low`, `high` (95% bootstrap), `per_class`, `l2` and `cv_accuracy` (penalty chosen by grouped cross-validation), `control_shuffled_labels` (`mean`, `max`, `reps`), `predictions`, `hits`, and with `--against`, `paired_against` (`difference`, `low`, `high`, `verdict`, `name`).

| Exit code | Meaning |
| --- | --- |
| `0` | Done: listed, shown, reported or written |
| `2` | Bad input or arguments: an unknown family or action, a raw folder that fails a check, a missing package for a script; the reason is on stderr |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `unknown segzoo action` | An action other than list, show, env, datalist reached `cmd_segzoo` from Python | Use one of the four |
| `unknown family` | `show` or `family()` got an id not in the registry | `kit segzoo list` for the ids |
| `segzoo show needs a family id` | `show` without a name | Add an id |
| `unsupported file type:` or `unsupported dataset file_ending` | The ending is outside this converter's supported list | Convert the dataset to one of the formats listed under Inputs |
| `folds must be an integer of at least 2` | Zero, one, a negative count or a non-integer Python value was supplied | Use at least two folds and inspect the fold counts before training |
| `dataset.json must contain an object`, `dataset.json labels must be an object` or `dataset.json numTraining must be a positive integer` | Metadata has the wrong JSON type or count | Correct dataset.json before converting |
| `dataset.json channel_names keys must be consecutive integers starting at 0` | A channel key is missing or renamed | Use `"0"`, `"1"`, ... and matching `_000N` image suffixes |
| `duplicate image for case` or `duplicate label for case` | More than one file maps to the same case/channel or label, often two formats of one image | Keep the intended file; the converter will not choose for you |
| `imagesTr contains no training cases` | The dataset has no visible image files | Supply the training images before exporting a plan |
| `no dataset.json in` | RAW is not an nnU-Net raw dataset folder | Point at the `DatasetNNN_Name` folder |
| `dataset.json has no channel_names` | An nnU-Net v1 or hand-written dataset.json | Add `channel_names` as nnU-Net v2 expects |
| `needs imagesTr/ and labelsTr/` | A folder is missing | Check the dataset layout |
| `cases without labels: ... ; labels without images:` | Image and label case names do not pair up | Fix the names; each case needs both |
| `dataset.json says numTraining` | The count in dataset.json differs from the images found | Fix `numTraining` or the files |
| `segzoo datalist needs RAW (an nnU-Net raw dataset folder) and --out DIR` | One of the two is missing | Give both |
| `does not end with the dataset's file_ending` | A file with another ending sits in imagesTr or labelsTr | Remove it or convert it |
| `channel ... but dataset.json names` | An image's channel suffix is beyond the channels dataset.json lists | Fix the suffix or `channel_names` |
| `channels ..., expected 0..` | A case is missing one of its channel files | Add the missing `_000N` file |
| `segzoo datalist:` | Prefix of any of the dataset errors above, from the command | Read the rest of the line |
| `lacks nnU-Net's _0000 channel suffix` | An image name has no `_0000` channel suffix | Rename to `CASE_0000.EXT` |
| `unknown network` | `build()` got a name it does not know | Use one of `segzoo_nets.names()` |
| `dims must be 2 or 3, got` | `build()` with another dims | Use 2 or 3 |
| `segformer is 2D only: give the depth layers as channels (2.5D)` | SegFormer asked for in 3D | Use a 2D configuration, depth layers as channels |
| `ss2dunet is 2D only` | SS2DUNet asked for in 3D | Use a 2D configuration |
| `images need 1 or 3 channels, got` | `FrozenFeatures` given another channel count | Give gray or RGB images |
| `could not write the shim:` | nnU-Net's trainer folder is not writable (or nnunetv2 is missing) | Use `--target` on a writable folder that nnU-Net searches, or install nnunetv2 into a virtual environment |
| `builds ..., which has no ... D form; use a` | A 2D-only trainer was run with a 3D configuration | Use the `2d` configuration |
| `needs every patch side divisible by` | The nnU-Net plans' patch size does not divide by the network's multiple (for example SegFormer or Swin UNETR with a 48 patch) | Edit the plans' patch size to a multiple, or use another network |
| `float images must lie in [0, 1]` | Float images outside [0, 1] | Scale them, or pass uint8 |
| `paired hits must cover the same items` | The two hit lists differ in length | Pass hits for the same items |
| `test labels never seen in training:` | A test class has no training example | Add training examples or drop the class |
| `--against lacks ... test items, such as` | The other method's hits do not cover every test item | Give hits for every test id |
| `segzoo_probe` | Prefix of a probe error printed by the script, exit 2 | Read the rest of the line |
| `model must be sam2 or medsam2` | `load_predictor` got another model name | Use one of the two |
| `the seed must be one 2D slice of labels, got shape` | The seed `.npy` is not 2D | Save one slice of labels |
| `the seed has no labeled pixel (0 is background)` | The seed slice is all zero | Label at least one sheet |
| `the cube must be 3D, got shape` | The cube `.npy` is not 3D | Save a (Z, Y, X) cube |
| `key slice ... is outside 0..` | `--key` beyond the cube along `--axis` | Use an index inside the cube |
| `seed shape ... does not match a slice,` | The seed's shape differs from a slice of the cube along `--axis` | Cut the seed from the same cube and axis |
| `prompt must be box or mask` | Another `--prompt` | Use box or mask |
| `mode must be video_path or tensor` | `follow` called from Python with another mode | Use one of the two (MedSAM2 uses tensor) |
| `seed object ... covers no labeled sheet on the key slice` | `score` found a seeded id with no true sheet under it | Check that the seed and the truth come from the same cube and key slice |
| `prediction shape ... differs from truth` | `score` got labels and truth of different shapes | Score against the cube's own labels |
| `segzoo_sam2 ... needs torch, Pillow and the sam2 package (...); pip install sam2==1.1.0, or MedSAM2's fork from github.com/bowang-lab/MedSAM2` | A package is missing | Install as the message says |
| `delta shape ... must equal u shape` | `selective_scan` inputs disagree | Pass delta with the shape of u |
| `A has ... rows, u has ... channels` | `selective_scan` state matrix and input disagree | Give A one row per channel |
| `B and C must be (batch, groups, d_state, L)` | `selective_scan` B or C has another rank | Reshape them |
| `channels do not split into ... groups` | Channel count not a multiple of the group count | Pick a group count that divides it |
| `chunk must be at least 1` | `selective_scan` with chunk 0 | Use 16 (the default) |
| `SS2DUNet needs H and W divisible by` | Input sides not a multiple of the network's downsampling | Pad or crop to a multiple of 8 |

## How it works

**Registry.** `REGISTRY` in `kit/segzoo.py` is a list of dicts with the fields in `FIELDS`. A family is `release_ok` only when both its code and its weights licenses are permissive; SegFormer (NVIDIA source code license, non-commercial), DINOv3 (DINOv3 License, gated) and MedSAM2 (weights for research and education) are not. `env` checks each family's import names with `importlib.util.find_spec` and reads versions from `importlib.metadata`, so it never loads torch.

**Datalist.** Cases are the label file names; each image's channel comes from its `_000N` suffix. `fold_of(case, folds)` is the sha256 of the case id modulo the fold count, so the same case always lands in the same fold. When `dataset.json` has an `ignore` label, the summary notes that Auto3DSeg will treat it as a class.

**Trainers.** Each `nnUNetTrainer_SZ...` subclasses `nnUNetTrainer` and overrides only `build_network_architecture` (a class method, as nnU-Net calls it at inference), `set_deep_supervision_enabled` (a no-op; the zoo's networks have one output) and `configure_optimizers`. The class checks dims and patch divisibility before building. Data loading, augmentation, Dice plus cross-entropy loss with the ignore label, and sliding-window inference stay nnU-Net's. nnU-Net finds trainers by searching its own `training/nnUNetTrainer` package, so `shim` writes a small module there that imports the classes.

**SS2D.** `selective_scan` computes the Mamba S6 recurrence h_t = exp(delta A) h_(t-1) + delta B x_t, y_t = C h_t in chunks of 16 steps: within a chunk it builds the cumulative decay matrix and does one matrix product, between chunks it carries the state. Each chunk is gradient-checkpointed, which keeps 2D training on a GPU within memory. It uses `mamba_ssm`'s CUDA kernel when asked (`fast=True`) and present. `SS2D` scans an image in four directions (rows, columns and both reversed), as VMamba does; `SS2DUNet` is a U-Net whose full-resolution stage is convolutions and whose lower stages are VSS blocks.

**SAM 2 follower.** The cube's slices along the axis become video frames; each seeded sheet is prompted on the key slice by its box or mask; the predictor propagates forward and backward; each pixel takes the sheet with the highest logit above the threshold. The scorer matches each predicted sheet to the true sheet it overlaps most on every slice.

**Probe.** Features are standardized on the training set. A multinomial logistic head is fitted by L-BFGS in float64, with the L2 penalty chosen from `L2_GRID` (1e-4 to 1) by five-fold cross-validation over groups, then refitted on all training items and applied once to the test set. Intervals are 10,000 bootstrap resamples.

## Cost and time

Measured 2026-10-17 on a 4-core Xeon cloud container (shared), CPU only: `kit segzoo` under a second; `tests/test_segzoo_models.py` about 81 s; an SS2DUNet forward pass on a 128 x 128 slice about 5 s; nnU-Net smoke training of MedNeXt-S and SegResNet on a 48-cube synthetic dataset, one tiny epoch each, finished in minutes. Real training needs a GPU: by the repository's estimates a from-scratch nnU-Net surface run costs on the order of 100 USD or more on Modal (Interpretation, not measured here). Any GPU run needs a written spec and the user's budget decision (AGENTS.md rule 11).

## For agents

- **Command:** `python -m kit segzoo list --json` for the registry; `python -m kit segzoo env --json` before running any family.
- **Parse:** `release_ok` (bool) decides whether a tool trained from that family can be released; `gated` means the weights need a logged-in, approved account; `verdict` says the planned use. For a follow, read `beats_control`; for a probe, compare `low` with `control_shuffled_labels.max` and read `paired_against.verdict`.
- **Rerun:** Safe; `datalist` and the scripts overwrite only their `--out` file or folder; `shim` overwrites `segzoo_shim.py`.
- **Success:** Exit 0. A follower result counts only with `beats_control` true; a probe only with `low` above the shuffled-label maximum.
- **Not a pass:** A trainer that runs is not a better model: only a preregistered comparison on held-out known-answer data with a null arm says that. A probe accuracy without its control, or a follow score without the copy-seed control, is not evidence.
- **Go-ahead:** Needed before any paid GPU run, before downloading gated weights with Chase's account, and before releasing anything trained from a family with `release_ok` false.
- **Never:** Never release weights trained from SegFormer, DINOv3 or MedSAM2 under a permissive license; never run these models on target-scroll data in this public repository; never call an ink map made with them a reading.

## Tests

`python -m unittest tests.test_segzoo tests.test_segzoo_models -v`. `test_segzoo` (standard library) covers the registry's fields, ids and licenses, `env` without imports, and the datalist: hash folds, several channels, every refusal, and the command writing both files. `test_segzoo_models` skips without torch (and per package without monai, nnunetv2 or transformers): the chunked scan against the loop (values and gradients), every `build` name forward, the trainer checks for dims and divisibility, the SAM 2 follower and scorer with a stand-in predictor and the copy-seed control, and the probe's fit, control and paired verdict. Not covered: real SAM 2 weights, a real nnU-Net training run (done by hand on 17 October 2026 with a synthetic dataset), and any scroll data.

## History

- 2026-10-17: Added: the registry and `kit segzoo`, nnU-Net trainers, the SS2D scan, the SAM 2 follower and the frozen probe ([public PR](https://github.com/ChaseHendrick/Scrolls/pulls?q=head%3Aclaude%2Fmodern-seg-models-txtw1n))

## Related

- [AutoPipeline](autopipeline.md): runs the community's current surface and ink models; any challenger from here is compared against what it uses.
- [`auc`](auc.md): scores ink maps with the reversed-depth control.
- [`letterread`](letterread.md): the letter reader, the baseline a frozen-feature probe on letters is compared with.
- [The docs index](../README.md): where each topic's notes live.
