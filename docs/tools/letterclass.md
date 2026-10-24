# letterclass: name Greek letters and read lines on papyrus photographs, for people and agents

Our single-letter classifier (trained on Hell-Char only), a Greek prose language model with no Homer for reading lines of given letter boxes, and an agent interface (JSON command line and MCP server) over both and over the CTC line reader.

| Field | Value |
| --- | --- |
| Id | `letterclass` |
| Status | Experimental |
| Kind | script,agent tool |
| Area | Letters and titles |
| Run | `python scripts/letters/reader_api.py letter`, `python scripts/letters/reader_api.py line`, `python scripts/letters/reader_api.py line-free`, `python scripts/letters/reader_api.py mcp`, `python scripts/letters/icdar_train.py train`, `python scripts/letters/icdar_train.py devpost`, `python scripts/letters/icdar_train.py smoke`, `python scripts/letters/greek_lm.py build`, `python scripts/letters/greek_lm.py ppl`, `python scripts/letters/icdar_h2h.py build`, `python scripts/letters/icdar_read.py post`, `python scripts/letters/icdar_read.py score`, `bash scripts/letters/icdar_job/train_job.sh` (inside an HF Job) |
| Code | `scripts/letters/reader_api.py`, `scripts/letters/letterclass-weights.json`, `scripts/letters/ctc_letter.py`, `scripts/letters/icdar_train.py`, `scripts/letters/greek_lm.py`, `scripts/letters/icdar_h2h.py`, `scripts/letters/icdar_read.py`, `scripts/letters/icdar_job/train_job.sh` |
| Tests | `tests/test_icdar_letters.py` |
| Needs | Python 3.10 or newer, numpy and Pillow; torch, timm 1.0.30 and opencv-python-headless for `letter`, `line`, training and posteriors; kit's `kit/letterread.py` and letters-v2-ccby weights for `line-free`. Data you fetch: the Hell-Char clone (aeef8466), the ICDAR 2023 zip (Zenodo 13825619), Perseus TEI texts at commit `0189b9c8` |
| Runs on | Any CPU for reads: with the released three runs, one `letter` call took 11 s and one 11-letter `line` call 11 s including model loading (25 s for the first call on a cold disk; measured 2026-10-24, 4-core cloud container). Training runs on an HF Job GPU: one 40-epoch run at 128 px took 3.4 to 3.9 min on an RTX Pro 6000 (convnext_small 205 s and 208 s, convnext_base 236 s; `train.json` of each run) |
| Network | None for `reader_api.py`. `greek_lm.py build`: `raw.githubusercontent.com` (Perseus) unless the cache folder holds the texts. `train_job.sh`: PyPI and the HF bucket named in `RESULTS` |
| Writes | `reader_api.py`: nothing (prints JSON). `icdar_train.py train`: `OUT/model.pt`, `config.json`, `train.json`. `greek_lm.py build`: the model file. `icdar_h2h.py build`: `WORK/{test,dev}/letters.json`, `lines.json`, `crops/`, `crops.sha256`, `WORK/build.json`. `icdar_read.py`: `WORK/PART/post-ARM.npz`, `lines-O2free.json` and the score file |
| Go-ahead | Not needed for reads, `fetch` and CPU runs on public data. Training rents a GPU (an HF Job; Cost and time); posting weights, numbers or reads follows the go-ahead rule of AGENTS.md |
| Released | Public `main` since 2026-10-24; weights as the GitHub release `letterclass-v1` of this repository (`scripts/letters/letterclass-weights.json`): runs CC BY 4.0, language model CC BY-SA 4.0 |
| Checked | 2026-10-24 against commit `7752c98` |

## What it does

Three reads, all **Model output**: letter hypotheses for a person or an automated check, never a reading or a transcription of a scroll.

- `letter`: one letter box of a gray image to the 24 Greek capitals, ranked with probabilities. The classifier (called O5 in the preregistration) is a ConvNeXt from timm's ImageNet weights, trained on Hell-Char's 13,014 letter crops of 144 papyri and nothing else, with augmentation that imitates other collections' photographs.
- `line`: a line whose letter boxes are given, decoded with a character language model of Greek prose (interpolated Kneser-Ney, order 5, 7,068,213 letters of 22 Perseus prose texts, with Homer, every poet and every verse line or quotation inside the prose left out). It returns the best string, each letter's confidence and its ranked alternatives.
- `line_free`: a line strip with no boxes, read by letters-v2-ccby's CTC line reader ([letterread](letterread.md)), greedy.

The fair test of these against Hell-Char ConvNeXt-V2 is the preregistered ICDAR 2023 head-to-head ([preregistration](../prereg/2026-10-24-letter-reader-icdar-h2h.md)). Those are photographs of papyri, not Herculaneum ink maps: a result there says which reader names papyrus letters better on unseen hands and collections, not which reads a scroll.

## When to use it

- An agent needs ranked letter hypotheses for boxes on a papyrus photograph or a clean ink-map crop.
- Reading a line of boxed letters with a language-model correction and per-letter confidences.

Do not use it:

- to claim a letter or a word was read on a scroll: no reader here can; any such claim needs a preregistered test with controls;
- on lines of verse it may know: the language model holds no Homer, but its prose shares common words;
- for text without letter boxes when accuracy matters: `line_free` is the weaker CTC reader.

## Quick start

```bash
python scripts/letters/reader_api.py fetch          # once: about 750 MB of weights, each SHA-256 checked
python scripts/letters/reader_api.py letter IMAGE --box 168 198 217 257 --top 3
```

`fetch` downloads the released weights listed in `scripts/letters/letterclass-weights.json` into `~/.cache/scrolls-kit/letterclass`; `IMAGE` is a photograph and the box `x0 y0 x1 y1` in pixels. To use your own runs instead, set `READER_RUNS=RUN1,RUN2` (folders from `icdar_train.py train`) and `READER_LM=LM.json.gz` (`greek_lm.py build`). On an ICDAR training photograph (P.CtYBR inv. 69, a dev image) it printed:

```
{"letter": "Η", "probability": 0.8442, "ranked": [{"letter": "Η", "probability": 0.8442}, {"letter": "Ν", "probability": 0.0294}, ...]}
```

It worked if `ranked` holds `--top` entries whose probabilities fall.

## Checks and controls

The head-to-head's controls (preregistration, section Controls): references permuted within texts (C1), tile-shuffled decoy crops (C2), the prior alone (C6) and the language model alone for lines (C7). Each must fail when the reader sees nothing. On the one test read (24 October 2026) all passed: decoys cut accuracy by 0.571 for our classifier (lower bound 0.534) and 0.526 for R1, and the language model alone erred 0.869 on lines. Result: our classifier 0.291 letter error against R1 0.340 (ahead, d -0.049, 95% -0.061 to -0.035); lines 0.241 against R1 letter by letter 0.320 (ahead) and 0.252 for R1 with the same language model (level) ([outcome](../prereg/2026-10-24-letter-reader-icdar-h2h.md#outcome-appended-24-october-2026-about-0920-utc-nothing-above-changed)). The ICDAR test answers are now spent.

Claim label: Model output, for every read; Interpretation, for any comparison not under the preregistration.

## Commands and options

### letter

`reader_api.py letter IMAGE [--box X0 Y0 X1 Y1] [--top 5]`

| Option | Default | Meaning |
| --- | --- | --- |
| `IMAGE` | required | PNG, JPEG or TIFF; read as gray |
| `--box` | whole image | the letter box in pixels |
| `--top` | 5 | how many ranked letters to return |

### line

`reader_api.py line IMAGE --boxes BOXES.json [--lm-weight W]`

| Option | Default | Meaning |
| --- | --- | --- |
| `--boxes` | required | JSON file: `[[x0, y0, x1, y1], ...]`, left to right |
| `--lm-weight` | 0.5 | weight of the language model's log-probability (best on the ICDAR dev part); 0 reads box by box |

### line-free

`reader_api.py line-free IMAGE [--box X0 Y0 X1 Y1] [--letter-height H]`

| Option | Default | Meaning |
| --- | --- | --- |
| `--box` | whole image | the line strip |
| `--letter-height` | strip height / 1.3 | letter height in pixels, to scale the strip |

### fetch

`reader_api.py fetch [--into DIR]`: downloads the three classifier runs and the language model once, checks every SHA-256 against `letterclass-weights.json` and prints the run folders and model path as JSON. A file already there with the right hash is kept.

| Option | Default | Meaning |
| --- | --- | --- |
| `--into` | `READER_HOME` or `~/.cache/scrolls-kit/letterclass` | where the weights go |

### mcp

`reader_api.py mcp`: an MCP server over stdio (JSON-RPC 2.0, one message a line) with tools `read_letter`, `read_line` and `read_line_free`, whose arguments match the commands above. A tool error comes back as a result with `isError: true`; a missing argument as error -32602.

| Global option | Default | Meaning |
| --- | --- | --- |
| `--runs` | `READER_RUNS` | classifier run folders, comma-separated |
| `--lm` | `READER_LM` | language model file |
| `--o2` | `READER_O2` | letters-v2-ccby weights |

### icdar_train.py train, devpost, smoke

`icdar_train.py train --hellchar HC --out DIR [--seed 0] [--arch A] [--size 96] [--epochs 40] ...`; `devpost --crops CROPS.npz --runs DIR... --out DIR`; `smoke --out DIR`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--hellchar` | required | Hell-Char data folder holding `hellchar.csv` and `cliplets/` |
| `--out` | required | run folder (train, smoke) or output folder (devpost) |
| `--seed` | 0 | training seed |
| `--max-steps` | none | stop after this many steps (tests) |
| `--crops` | required | packed dev crops (`pack_crops`) |
| `--runs` | required | run folders to read the crops with, each at test-time scaling 0 and 1 |
| `--arch`, `--size`, `--epochs`, `--batch`, `--lr`, `--wd`, `--smooth`, `--ema`, `--warmup`, `--tta` | `DEFAULTS` in the code | the training recipe (How it works) |

### greek_lm.py build, ppl

| Option | Default | Meaning |
| --- | --- | --- |
| `--out` | required | model file to write (gzip JSON) |
| `--cache` | none | folder of Perseus XML files, read before fetching |
| `--order` | 5 | n-gram order |
| `--lm` | required | model file (ppl) |
| `--text` | required | a TEI XML or plain text file to score (ppl) |
| `--limit` | 200000 | letters scored (ppl) |

### icdar_h2h.py build

| Option | Default | Meaning |
| --- | --- | --- |
| `--zip` | required | the ICDAR 2023 zip, sha256 pinned |
| `--hellchar` | required | `hellchar.csv` at Hell-Char commit aeef8466, for the overlap check |
| `--iliad` | required | Perseus `tlg0012.tlg001.perseus-grc2.xml`, for the line rule |
| `--work` | required | output folder |
| `--skip-dev` | off | build the test part only |

### icdar_read.py post, acc, devlines, freelines, score

| Option | Default | Meaning |
| --- | --- | --- |
| `--work` | required | the build folder |
| `--part` | required | `dev` or `test` (test reads are guarded) |
| `--arm` | required | `R1...`, `O2` or `O5...`; names the posterior file |
| `--variant` | plain | R1's input recipe: `plain`, `pad` or `demo` |
| `--r1`, `--r1-config` | none | R1's pinned weights and config |
| `--o2` | none | letters-v2-ccby weights |
| `--o5` | none | our run folders, comma-separated |
| `--decoy` | off | read tile-shuffled crops (control C2) |
| `--prior` | 0 | prior weight (acc, devlines) |
| `--lm`, `--hellchar` | required | language model and `hellchar.csv` (devlines, score) |
| `--weights` | `0.0 0.5 1.0` | language model weights to try (devlines) |
| `--fill` | required | JSON of the fill: `o5_runs`, `o5_prior`, `lm_weight`, `r1_lm_weight` |
| `--out` | required | score file |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `READER_RUNS` | none | classifier run folders, comma-separated; an ensemble averages their log-probabilities |
| `READER_LM` | none | the language model file from `greek_lm.py build` |
| `READER_O2` | none | letters-v2-ccby weights for `line-free` |
| `READER_HOME` | `~/.cache/scrolls-kit/letterclass` | where `fetch` puts the released weights and where the reads look for them when `READER_RUNS` or `READER_LM` is unset |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `reader_api.Reader(runs, lm, o2).letter(image, box, top)` | dict as `letter` prints | `ValueError` with no runs | |
| `Reader.line(image, boxes, lm_weight)` | dict as `line` prints | `ValueError` with no boxes or no model | |
| `Reader.line_free(image, box, letter_height)` | dict | `ValueError` with no weights | |
| `icdar_train.predict_folder(runs, greys)` | (n, 24) log-probabilities, ALPHABET order | | |
| `greek_lm.decode_boxes(post, lm, weight, train_logprior)` | (string, confidences, alternatives) | | beam 16 |

## Inputs

Gray images of any size (Pillow reads them; huge photographs are allowed). Boxes are pixels, `x0 y0 x1 y1`, origin top left. Crops work best when the box is the letter's own box, as an expert would draw it.

## Outputs

`letter`: `letter`, `probability`, `ranked` (letter and probability), `note`. `line`: `text` (with the language model), `ink_only` (box by box), `lm_weight`, `letters` (per box: `letter`, `confidence`, `alternatives`, `box`), `note`. `line-free`: `text`, `letter_height`, `note`. Probabilities are model posteriors, not calibrated chances of being right.

| Exit code | Meaning |
| --- | --- |
| `0` | the read ran; the JSON is printed |
| `1` | an error (missing file, no model), with a traceback |
| `2` | a wrong argument |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `unknown tool` | an MCP call named a tool that does not exist | use `tools/list` |
| `no classifier: run reader_api.py fetch, or set READER_RUNS or --runs` | no run folders given and no released weights in `READER_HOME` | run `fetch`, or set `READER_RUNS` |
| `FILE: sha256 differs from letterclass-weights.json` | a download is not the released file | run `fetch` again; if it repeats, the release changed and the manifest is the reference |
| `line needs at least one box` | an empty box list | pass the boxes |
| `no line reader weights: set READER_O2 or --o2` | `line-free` without letters-v2-ccby weights | set `READER_O2` |
| `: no Perseus Greek edition found` | a text is in none of the three Perseus editions at the pinned commit, or the network refused | fill `--cache` from a clone (`git show`) |
| `ZIP: sha256 HASH, not the pinned HASH` | the zip is not the pinned ICDAR file | fetch Zenodo 13825619 again |
| `empty crop` | a box outside the image, or of zero size | check the box is `x0 y0 x1 y1` inside the image |
| `TOOL: missing ARGS` (MCP error -32602) | an MCP call left out a required argument | pass every argument in the tool's `inputSchema.required` |
| `answers: N annotation image ids, M images` | the answers file changed shape; the image id repair no longer applies | stop; the build must be reviewed |
| `R1: weights or config are not the pinned files` | another R1 checkpoint | fetch R1 at `355f1b1c` |
| `O2: not the pinned letters-v2-ccby weights` | other weights | use step 26,000 |
| `test read refused: the working tree has uncommitted changes` | a test read from a dirty tree | commit or stash first |
| `test read refused: the preregistration still has placeholders` | the fill commit is not made | fill and freeze first |
| `test read refused: PATH differs from the preregistration` | code changed after the fill | read from the fill commit's code |
| `no language model: run reader_api.py fetch, or set READER_LM or --lm` | `line` with a weight above 0 and no model | run `fetch`, set `READER_LM`, or `--lm-weight 0` |

## How it works

`icdar_train.py`: crops standardized per crop (2nd percentile to 0, 80th to 1), padded square on the papyrus tone to 96 px, augmented (box jitter of -6% to +15%, affine, stroke erosion or dilation, resolution loss and blur, gamma, contrast, noise), ConvNeXt from `*.fb_in22k_ft_in1k` weights, AdamW, cosine schedule, label smoothing 0.1, an EMA of the weights (0.999). `greek_lm.py`: interpolated Kneser-Ney (discount 0.75, order 5) over the 24 capitals in scriptio continua. `decode_boxes`: per box, the classifier's log-posterior minus the log of its training class shares (a likelihood), plus the weight times the language model's log-probability, in a beam of 16; confidences are max-marginals over the final beam.

## Cost and time

Training: the three released runs came from one Hugging Face Job of seven runs plus dev posteriors (rtx-pro-6000, 2,561 s, 1.97 USD, 24 October 2026); an earlier Job of three ConvNeXt-Tiny runs cost 0.41 USD (499 s); the whole study, 11 runs and a lost run included, cost 3.90 USD. Reads: CPU, seconds per call (Runs on).

## For agents

- **Command:** `python scripts/letters/reader_api.py line IMAGE --boxes BOXES.json`, or the MCP server `reader_api.py mcp`.
- **Parse:** `text`, and per letter `confidence` and `alternatives`.
- **Rerun:** safe; it writes nothing.
- **Success:** exit 0 and JSON with `note`.
- **Not a pass:** a high confidence is not a correct letter; scores mean something only under a preregistered test with its controls.
- **Go-ahead:** Nothing for reads on public data.
- **Never:** call its output a reading of a scroll, or score it on a spent test set.

## Tests

`python -m unittest tests.test_icdar_letters`: the build's line grouping, ink gate and capital mapping; the bootstrap's sign and verdicts; the language model (sums to one, verse and quotations dropped, decoding); the MCP server's session, errors and version fallback with a fake reader. Not covered: training and torch reads (`icdar_train.py smoke` covers those).

## History

- 2026-10-24: first version, for the ICDAR head-to-head ([preregistration](../prereg/2026-10-24-letter-reader-icdar-h2h.md)).
- 2026-10-24: final classifier (three runs: convnext_base and two convnext_small at 128 px), frozen before the read and read once on the ICDAR test answers: ahead of Hell-Char ConvNeXt-V2 on letters, level on lines given the same language model ([outcome](../prereg/2026-10-24-letter-reader-icdar-h2h.md#outcome-appended-24-october-2026-about-0920-utc-nothing-above-changed)).

## Related

- [letters-training](letters-training.md): the CTC reader's training and earlier head-to-heads.
- [letterread](letterread.md): the CTC line reader that `line-free` calls.
- [greeklm](greeklm.md): kit's own Kneser-Ney Greek model, without the verse and quotation filter.
- [Preregistration and outcome](../prereg/2026-10-24-letter-reader-icdar-h2h.md): the development numbers behind every choice, and the test.
