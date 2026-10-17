# soup: average the weights of several checkpoints of one training run

`scripts/soup.py` writes a checkpoint soup, the uniform mean of the weights of two or more checkpoints from one training run (such as `ink_9um` seed 42 at steps 40k to 75k), and refuses checkpoints whose `config.seed` differs, because a cross-seed weight average breaks the model.

| Field | Value |
| --- | --- |
| Id | `soup` |
| Status | Current |
| Kind | script |
| Area | Ink maps and models |
| Run | `python scripts/soup.py` |
| Code | `scripts/soup.py` |
| Tests | None: no test in `tests/` runs it. The saved one-off check `scripts/experiments/2026-10-07-cloud/tricks/soup_check.py` compared its output with Nieuwlaar's published soup (see Checks and controls) |
| Needs | Python 3 and PyTorch (`torch`), which the script imports at the top, so even `--help` fails without it. The 2026-10-07 run used Python 3.14 and torch 2.14.1+cpu (`scripts/experiments/2026-10-07-cloud/tricks/notes.md`). Checkpoints saved with `torch.save` |
| Runs on | Any CPU; every tensor is loaded with `map_location="cpu"` and nothing uses a GPU. Wall time Not measured: the 2026-10-07 soup of four `ink_9um` checkpoints recorded no time |
| Network | None. Downloading the checkpoints is a separate step (Quick start) |
| Writes | The file `OUT` (replaced if it exists), nothing else |
| Go-ahead | Not needed to make a soup. Uploading one (such as to Hugging Face) needs Chase's yes first (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 (`ebd4ae3`) |
| Guide | [tricks.md](../tricks.md) (the community tricks, with the soup's measured numbers) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

A training run saves checkpoints along the way. A checkpoint soup is the plain mean of the weights of several of them: every floating-point tensor of the model is summed over the checkpoints and divided by their number. Within one run the late checkpoints sit in the same basin of the loss, so their mean is a working model, and it can be a little better than any one of them. Nieuwlaar's `soup42_last4`, the mean of the last four released `ink_9um` seed 42 checkpoints (steps 40,000, 50,000, 60,000 and 75,000), gained 0.03 to 0.06 AUC on PHerc0139 ([ink9um-dense-native](https://github.com/Nieuwlaar/ink9um-dense-native), Community report, in [tricks.md](../tricks.md)). This script follows his `make_soup.py` and rebuilds that soup bit for bit.

Different runs (different seeds) sit in different basins, and the mean of their weights is not a model at all: Nieuwlaar's cross-seed soup scored AUC 0.49, chance (Community report). So the script reads `config.seed` from every checkpoint and refuses when the values differ, unless `--allow-cross-seed` is given. To combine runs, average their ink maps instead, with [`ensemble`](ensemble.md).

The output is a checkpoint in the same layout as the first input: villa's `ink_9um` inference loads a soup of `ink_9um` checkpoints like any `ink_9um` checkpoint (`scripts/experiments/2026-10-07-tricks/tricks.sh` ran it that way). The script does not run the model, score anything or choose the checkpoints; which steps to average is the user's choice. A soup's ink maps are model output, not a reading, and a better AUC from a soup never means that letters were found.

## When to use it

- Making `soup42_last4` again, or a soup of the last few checkpoints of another single run, such as a fine-tune that saved several steps.
- Testing whether a soup helps on a held-out labelled segment, scored with [`auc`](auc.md) against the reverse-depth control.

Do not use it:

- To combine different seeds or different models: average their maps with [`ensemble`](ensemble.md). A cross-seed weight soup breaks the model.
- On checkpoints that keep their weights under a key other than `model`, `ema_model`, `model_state_dict`, `state_dict` or `network_weights`, or as a whole pickled model: the script either fails or silently copies the first checkpoint (Failure modes).
- On v8in (`YoussefMoNader/ink-8um-v8in`): its release has one `model.safetensors`, not a series of `.pth` checkpoints, so there is nothing to average.
- On checkpoints from a source you do not trust: it loads them with `weights_only=False`, which runs any code pickled in the file.

## Quick start

```bash
B=https://huggingface.co/scrollprize/ink_9um/resolve/main/hybrid_3d2d-seed42
mkdir -p CK
for s in 040000 050000 060000 075000; do curl -sSfL -o CK/step-$s.pth "$B/step-$s.pth"; done
python scripts/soup.py SOUP.pth CK/step-040000.pth CK/step-050000.pth CK/step-060000.pth CK/step-075000.pth
```

- `CK`: a folder for the four released `ink_9um` seed 42 checkpoints, 138,360,039 bytes each on Hugging Face (about 553 MB in all).
- `SOUP.pth`: the soup to write. This is `soup42_last4`.
- Order matters only for what is not averaged: the soup keeps the first input's `config` and `step` (Outputs).

The 2026-10-07 run of this command (Linux container, 4 CPUs, torch 2.14.1+cpu) printed (`scripts/experiments/2026-10-07-cloud/tricks/setup.log`):

```
soup of 4 -> /root/scrolls-cpu/tricks/soup42_last4.pth sha256 65563b45d4144a3fdf6cbdeda53b966bf0a7ee974f9881ce77905cc9755209e1
```

torch is not installed in the container these pages were written in (16 October 2026) and its CPU wheel is too large to fetch there, so the script was run against a small numpy stand-in for the few torch calls it makes, on synthetic checkpoints (`{"model": {...}, "config": {"seed": ...}, "step": ...}`). Four seed 42 checkpoints with a weight of 1, 2, 3 and 6 gave:

```
soup of 4 -> soup.pth sha256 8dcc8e68b5c281ffcc92b751b6ba1326757d69315608f9cbc8cb97d77aaf4ba9
['config', 'model', 'soup', 'step'] 39999 {'seed': 42} [[3. 3.]] float32 39999
```

that is, the mean weight 3; the first input's `step`, `config` and integer tensor (the last 39999, a stand-in for BatchNorm's `num_batches_tracked`); and a `soup` entry. A seed 42 and a seed 43 checkpoint gave `ValueError: checkpoints come from seeds [42, 43]: ...` and exit code 1.

It worked when the exit code is 0, the line `soup of N -> OUT sha256 ...` names the right N, and (for a checkpoint with a state key) the saved payload holds a `soup` entry listing every input with its SHA-256.

## Checks and controls

- **The seed guard can fail.** The released `ink_9um` checkpoints carry `config.seed`: read on 2026-10-16 from the pickle headers of `hybrid_3d2d-seed42/step-040000.pth` and `step-075000.pth` (seed 42) and `hybrid_3d2d-seed43/step-075000.pth` (seed 43) on Hugging Face, each with the keys `model` (508 tensors), `config` (48 entries) and `step` (39999 or 74999). A seed 42 and seed 43 pair is refused (stand-in run above). Checkpoints without `config.seed` all read as `None`, so the guard cannot tell their runs apart.
- **The rebuild matches the published soup.** On 2026-10-07 the soup above, written as a bare safetensors file, had SHA-256 `ab3f1bdefa53733f4d4c46da6c7713c142bc8c703df5098fe8641757d764849c`, equal to Nieuwlaar's published file, and all 508 tensors were bit-identical (`scripts/experiments/2026-10-07-cloud/tricks/soup_check.json`, made by `soup_check.py` in the same folder, commit `57289f3`). The `.pth` file's own SHA-256 is not a stable identity: it depends on the output file's name (the root folder inside the archive) and on the input paths stored in the `soup` entry.
- **Whether the soup helps is a scoring question**, answered with [`auc`](auc.md) and its reverse-depth control, plus the depth-shuffle control from [`layers`](layers.md), on a segment the run did not train on. On the PHerc0841 crops (640 px, 64 px edge left out, CPU, villa PR #1865), forward AUC with reversed in brackets (`scripts/experiments/2026-10-07-cloud/tricks/tables.md`):

| Map | w00 crop | ag896 crop | w00 depth-shuffled | ag896 depth-shuffled |
| --- | --- | --- | --- | --- |
| `ink_9um` seed 42, step 75,000 | 0.8061 (0.536) | 0.6594 (0.558) | 0.4996 | 0.5578 |
| `soup42_last4` | 0.8326 (0.504) | 0.6723 (0.556) | 0.4807 | 0.5026 |

The soup is ahead by +0.0265 on w00 and +0.0129 on ag896, with its reverse at 0.504 and 0.556 and its shuffled maps near 0.5; the letter-scale score (`hp_r`, [`hpscore`](hpscore.md)) moved from +0.029 to +0.032 on w00 and from -0.004 to +0.000 on ag896. No paired interval (`kit auc --compare`) was measured, so whether these differences exceed sampling noise is not known ([grok lane A log](../logs/2026-10-07-grok-laneA.md)), and w00 and ag896 are two patches of one sheet. The fail case for scale: a cross-seed soup at 0.49 (Nieuwlaar, Community report).

Claim label: Model output for the soup's AUCs on the PHerc0841 crops; Sourced fact for the bit-identical rebuild (`soup_check.json`); Community report for Nieuwlaar's PHerc0139 gains and the cross-seed 0.49.

## Commands and options

### `python scripts/soup.py`

```
usage: soup.py [-h] [--allow-cross-seed] out inputs [inputs ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Path of the soup to write with `torch.save`; replaced if it exists. It may be one of the inputs: all inputs are read before it is written |
| `inputs` | required | Two or more checkpoints of one training run, in any order; the first supplies everything that is not averaged. Fewer than two is a usage error |
| `--allow-cross-seed` | off | Average even when the checkpoints' `config.seed` values differ. Only for experiments: a cross-seed soup is expected to be broken |

The script reads no environment variables.

## Python API

The functions are importable for a test or a notebook with `sys.path.insert(0, "scripts")` and `import soup`.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `soup(paths, allow_cross_seed=False)` | `(payload, meta)`: the object to save and the `soup` entry (Outputs) | `ValueError` on a different state key, different tensor names, a different shape, or mixed seeds; `FileNotFoundError` for a missing file; anything `torch.load` raises | What `main` runs. With no state key, `payload` is the averaged state dict alone, without `meta` |
| `state_key(payload)` | The first of `STATE_KEYS` whose value in `payload` is a dict, or `None` | Nothing | `None` also for a payload that is not a dict |
| `seed(payload)` | `payload["config"]["seed"]`, or `None` when either is missing | Nothing | |
| `sha256(path)` | str, 64 hex digits | `OSError` for an unreadable file | Reads in 1 MiB blocks |
| `main(argv=None)` | `0` | `SystemExit(2)` on a usage error; the errors of `soup` | Saves the payload and prints one line |
| `STATE_KEYS` | tuple (a constant) | Nothing | `("model", "ema_model", "model_state_dict", "state_dict", "network_weights")`, searched in this order |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Checkpoints (`inputs`) | Files written by `torch.save` | Either a dict whose weights sit under one of `STATE_KEYS` as a name-to-tensor dict (the released `ink_9um` checkpoints use `model`, with `config` and `step` beside it), or a bare name-to-tensor dict. Loaded on the CPU with `weights_only=False`, one at a time after the first |
| `config.seed` | int (any value) in the payload's `config` dict | Read for the seed guard; missing reads as `None` |

Every input must have the same state key, the same tensor names and, for floating-point tensors, the same shapes as the first. Dtypes are not compared. A released `ink_9um` step checkpoint is 138,360,039 bytes.

## Outputs

It prints one line:

```
soup of N -> OUT sha256 HASH
```

`N` is the number of inputs and `HASH` the SHA-256 of the written file.

The file `OUT`, written with `torch.save`:

- **A checkpoint with a state key** (such as `ink_9um`'s `model`): the first input's whole payload, with that key replaced by the averaged state dict and a new top-level `soup` entry. Everything else comes from the first input unchanged: `config`, `step` (39999 when `step-040000.pth` is first), any optimizer state, and any second state dict. If a payload holds both `model` and `ema_model`, only `model` is averaged and `ema_model` stays the first input's.
- **A bare state dict**: the averaged state dict alone. No `soup` entry is stored; record the input hashes yourself.

In the averaged state dict, floating-point tensors are the mean over the inputs, cast back to the first input's dtype; integer tensors (such as BatchNorm's `num_batches_tracked`) and non-tensor values are the first input's.

| Field | Type | Meaning |
| --- | --- | --- |
| `soup.inputs` | list of objects | One per input, in the order given |
| `soup.inputs[].path` | str | The path as given on the command line |
| `soup.inputs[].sha256` | str | SHA-256 of that input file, 64 hex digits |
| `soup.n` | int | Number of inputs averaged |
| `soup.method` | str | Always `uniform weight mean` |

| Exit code | Meaning |
| --- | --- |
| `0` | The soup was written |
| `1` | An uncaught error with a Python traceback: a refusal (`ValueError`), a missing file, torch not installed, or an unreadable checkpoint |
| `2` | A usage error from the argument parser, including fewer than two inputs |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `soup.py: error: need at least two checkpoints`, exit code 2 | One input after `out` | Give two or more checkpoints |
| `ModuleNotFoundError: No module named 'torch'`, exit code 1, even for `--help` | torch is not installed in this Python | Run it in villa's environment, or install torch |
| `FileNotFoundError: [Errno 2] No such file or directory: 'PATH'`, exit code 1 | An input path that does not exist | Fix the path |
| `ValueError: checkpoints come from seeds [42, 43]: a cross-run weight soup breaks the model (Nieuwlaar: AUC 0.49). Average the maps instead, or pass --allow-cross-seed.`, exit code 1 | The inputs' `config.seed` values differ, or some have a seed and some none (`[42, None]`) | Use checkpoints of one run; to combine runs, average their maps with [`ensemble`](ensemble.md) |
| `ValueError: PATH: state key 'KEY', expected 'KEY'`, exit code 1 | That input keeps its weights under another key than the first (or has none) | Use checkpoints saved the same way |
| `ValueError: PATH: different tensor names from FIRST`, exit code 1 | That input's state dict has other tensor names than the first input's: another architecture, or a wrapper prefix such as `module.` | Use checkpoints of the same model saved the same way |
| `ValueError: PATH: NAME has shape (...), expected (...)`, exit code 1 | A floating-point tensor of another shape: another model size | Use checkpoints of one run |
| A traceback ending in `AttributeError: ... has no attribute 'items'`, exit code 1 | The first file holds a whole pickled model, not a dict | Save the model's `state_dict()` and soup those |
| Exit code 0 and `soup of N`, but the file has no `soup` entry and its weights equal the first input's | The payload keeps its weights under a key not in `STATE_KEYS` (such as `weights`), so it was read as a bare state dict whose values are not tensors, and nothing was averaged (seen with the stand-in on 2026-10-16) | Check the payload's keys first (`list(torch.load(PATH, map_location="cpu", weights_only=False))`); re-save the weights under `model` or `state_dict` |

## How it works

1. Load the first input on the CPU and find its state key: the first of `STATE_KEYS` (`model`, `ema_model`, `model_state_dict`, `state_dict`, `network_weights`) whose value is a dict; with none, the payload itself is the state dict.
2. Copy its floating-point tensors to float64 accumulators; keep everything else as it is. Note its `config.seed`.
3. For each further input: load it, check that the state key, the tensor names and every floating-point shape match the first, note its seed, and add its floating-point tensors to the accumulators. Only one further input is held at a time.
4. If more than one distinct seed was seen (counting a missing seed as `None`) and `--allow-cross-seed` is off, stop with the `ValueError` above. Nothing is written.
5. Divide each accumulator by the number of inputs and cast it back to the first input's dtype.
6. Hash every input with SHA-256, build the `soup` entry, put the averaged state dict (and the entry) into the first payload, and save it with `torch.save`. Print the count, the output path and its SHA-256.

The sum is taken in float64, so the order of the inputs does not change the averaged weights beyond float64 rounding. The method follows Nieuwlaar's `make_soup.py` ([ink9um-dense-native](https://github.com/Nieuwlaar/ink9um-dense-native)); the weight-averaging idea is also the subject of Armando Gaona's checkpoint-averaging Progress Prize ([tricks.md](../tricks.md)).

## Cost and time

Not measured. From the code: memory holds the first checkpoint, a float64 copy of its floating-point tensors (twice their float32 size) and one further checkpoint at a time; disk reads every input twice (once to load, once to hash). For four `ink_9um` checkpoints that means reading about 553 MB twice. It runs on any CPU and needs neither a GPU nor Modal. Inference with the soup is a separate job with its own cost: villa's `ink_9um` inference took about 60 to 75 s per two-direction map on a 640 px crop on 4 CPUs (`scripts/experiments/2026-10-07-cloud/tricks/notes.md`); a whole segment is longer, and work that needs a GPU or more than about an hour of CPU goes to Modal (the Modal rule, hard rule 11).

## For agents

- **Command:** `python scripts/soup.py SOUP.pth CK1.pth CK2.pth [CK3.pth ...]`, all from one training run, earliest first. There is no JSON output; read the payload back with `torch.load(SOUP.pth, map_location="cpu", weights_only=False)["soup"]`.
- **Parse:** the printed line `soup of N -> OUT sha256 HASH`; in the saved payload, `soup.n`, `soup.inputs[].path` and `soup.inputs[].sha256`.
- **Rerun:** Safe; it only reads the inputs and replaces `OUT`. The same inputs give the same tensors, but the file's SHA-256 changes with the output name and the input paths.
- **Success:** Exit code 0, `soup of N` with the expected N, and, for a checkpoint with a state key, a `soup` entry in the file.
- **Not a pass:** A soup with no `soup` entry whose weights equal the first input's (its weight key was not found); a soup made with `--allow-cross-seed`; a soup of checkpoints without `config.seed`, where the guard sees nothing; a higher AUC without its reverse control, without a paired interval, or on a segment the run trained on.
- **Go-ahead:** Nothing to make a soup. Uploading one, or posting its scores, needs Chase's yes.
- **Never:** Average different seeds or different models; load checkpoints from an untrusted source (`weights_only=False` runs pickled code); call the soup's map a reading or say letters were found.

## Tests

None: no module in `tests/` runs `scripts/soup.py`. What was checked, and how to check again:

```bash
python scripts/soup.py --help    # needs torch
python scripts/experiments/2026-10-07-cloud/tricks/soup_check.py SOUP.pth NIEUWLAAR.safetensors
```

`soup_check.py` (needs torch and safetensors) writes the soup's tensors as a bare safetensors file and compares its SHA-256 with Nieuwlaar's published one and every tensor with his file; `NIEUWLAAR.safetensors` is his released soup. On 2026-10-07 it printed `"bit_identical": true` for 508 tensors. On 2026-10-16 the refusals and the averaging were exercised on synthetic checkpoints with a numpy stand-in for torch (Quick start); that stand-in is not in the repository. Nothing tests other checkpoint layouts with real torch.

## History

- 2026-10-07: the rebuilt `soup42_last4` is bit-identical to Nieuwlaar's published file (508 tensors), and its maps were scored on the PHerc0841 w00 and ag896 crops (`57289f3`, `10f47c2`, `07e7dbe`).
- 2026-10-07: first version, after Nieuwlaar's `make_soup.py`, with the seed guard and the `soup` entry (`ebd4ae3`).

## Related

- [`ensemble`](ensemble.md): averages maps, the way to combine different seeds or models.
- [`auc`](auc.md): scores the soup's map against the labels, with the reverse-depth control and `--compare` for a paired interval.
- [`layers`](layers.md): the depth-shuffle control (`kit shuffle`) used beside the reverse one.
- [`hpscore`](hpscore.md): the letter-scale score quoted above.
- [`experiment-records`](experiment-records.md): the saved 2026-10-07 tricks job (`scripts/experiments/2026-10-07-cloud/tricks/`) that made and scored the soup.
- [tricks.md](../tricks.md): the community tricks table, where the soup sits with its sources.
- [Cloud partial log](../logs/2026-10-07-cloud-partial.md) and [novel checks log](../logs/2026-10-07-novel-checks.md): the soup's rows beside the other readers, the window averages and the shuffle control.
