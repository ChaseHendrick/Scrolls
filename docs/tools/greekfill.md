# greekfill: Greek gap restoration benchmark, hosted text models against a letter model

Runs and scores the Greek gap restoration benchmark: hosted text models and an order-8 Kneser-Ney letter model fill hidden letters in Philodemus, De Musica, under a frozen rule with a memorisation probe; the frozen files reproduce byte for byte.

| Field | Value |
| --- | --- |
| Id | `greekfill` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Letters and titles |
| Run | `python -m kit.greekfill`, `from kit import greekfill`, `from kit import greekkn` |
| Code | `kit/greekfill.py`, `kit/greekkn.py` |
| Tests | `tests/test_greekfill.py` |
| Needs | Python 3.10 or newer and numpy (the `reader` or `all` extra installs it); the rest is the standard library. To rebuild the corpus: git clones of [PerseusDL/canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit) at `0189b9c8d8d1f148133f2f0af309b4ee90ea4332` and [OpenGreekAndLatin/First1KGreek](https://github.com/OpenGreekAndLatin/First1KGreek) at `03776b39f4047c5cff06f5296fae4b2bae4b08fb` (CC BY-SA 4.0, about 1 GB together). For `run` only: a Hugging Face token with inference credit |
| Runs on | Any CPU. On a 4-core Claude cloud container (22 Oct 2026): `score` 1.4 s, `corpus` 5 min 26 s with `--nproc 4`, `prep` 1 min 57 s; the original `run` of 690 requests took about 11 minutes of replies |
| Network | `run` only: `https://router.huggingface.co/v1/chat/completions`, to ask the hosted models (`--dry-run` contacts nothing). Every other command reads local files; you clone the TEI repositories yourself |
| Writes | `corpus`: CORPUS.tsv. `prep`: OUT_DIR/`manifest.json`, `key.json`, `baseline.json` (and, with `--cache`, `general.npz` and `phil.npz` there). `run`: appends OUT_DIR/`replies.jsonl`. `score`: OUT_DIR/`score.json`, or the `--out` file. `chart`: OUT.svg. `check`: nothing (prints only) |
| Go-ahead | Not needed for `corpus`, `prep`, `score`, `check`, `chart` and `run --dry-run`. Needed for `run`: it sends paid requests to Hugging Face's router (renting compute: the go-ahead rule, hard rule 8), and the frozen test on these items is closed |
| Released | Public `main` from the merge of its pull request (prepared 22 Oct 2026), ported from the copy that ran the frozen test |
| Guide | [Preregistration and result](../prereg/2026-10-22-greek-restoration.md) |
| License | Code Apache-2.0; the frozen files that quote De Musica are CC BY-SA 4.0 ([evidence README](../evidence/greek-restoration-20261022/README.md#licence-of-the-text)) |
| Checked | 2026-10-22 against commit `0fbc49a` |

## What it does

Ink models and letter readers leave gaps where the ink is faint, and a language prior can propose the missing letters. Large hosted text models have read a great deal of Greek, so they are an obvious candidate prior. This benchmark asks whether they restore hidden letters in a Herculaneum author's prose better than a plain letter model. The test text is the second half of Philodemus, De Musica (Kemke's edition, First1KGreek `tlg1595.tlg221`), written as 24 Greek capitals with lunate sigma and spaces between words.

`prep` cuts the text into 150-symbol windows. 190 windows hide one gap of 1, 2, 3, 5 or 8 letters (38 each); 40 windows are memorisation probes that show 100 symbols and ask for the next letters, to see whether a model simply recalls De Musica. It writes what is sent (`manifest.json`, prompts only), the answers (`key.json`, never sent) and the baseline's fills (`baseline.json`), all before any request. `run` sends the prompts to hosted models through Hugging Face's router at temperature 0 under a cost cap. `score` reduces each reply to Greek capitals, counts letters restored in place, bootstraps the difference from the baseline and applies the frozen verdict (PASS, INCONCLUSIVE, VOID or FAIL). `check` compares the files with the frozen sha256 pins and `chart` draws letter accuracy by gap length.

The baseline, KN for short, is an order-8 interpolated modified Kneser-Ney letter model (`kit/greekkn.py`): a general component fitted on 16 million symbols of public Greek from Perseus and First1KGreek, mixed 0.728 and 0.272 with a component fitted on another Philodemus text, Volumina Rhetorica. `kit/greekkn.py` also holds the corpus builder that turns the TEI editions into one line of capitals per document. It is a different model from the order-5 letter model of Scroll Text Reader ([greeklm](greeklm.md)).

The frozen run of 22 October 2026 ended in FAIL: KN restored 0.331 of hidden letters, DeepSeek-V3-0324 and Kimi-K2-Instruct-0905 0.181 each, and Qwen3-235B-A22B-Instruct-2507 0.118 (Model output; [result](../prereg/2026-10-22-greek-restoration.md#result-22-october-2026-about-2240-utc-appended-after-the-run-nothing-above-changed)). A fill is a model's guess at edited text, not a reading of any papyrus, and the benchmark uses no scroll data.

## When to use it

- Checking the published result: `check` and `score` on the frozen files, which must reproduce `score.json` byte for byte.
- Rebuilding the whole baseline from public sources (`corpus`, then `prep`) to confirm the three frozen files.
- Measuring a new letter model or text model on the same items: write its fills in the `baseline.json` or `replies.jsonl` format and score them with `score`, reported as a new, separate run, not as part of the frozen test.
- Building the normalised Greek corpus (`corpus`) for another letter-model experiment.

Do not use it:

- To read a scroll or propose letters on an ink map: use [letterread](letterread.md), and trust only its controls.
- To rerun the frozen test with other prompts or models on these items and report it as the same test: the preregistration closed them. A new test needs a new preregistration (`docs/prereg/`) and new items.
- To score how Greek-like a string is: use [greeklm](greeklm.md) (`python -m kit greeklm score`).

## Quick start

```bash
python -m kit.greekfill check docs/evidence/greek-restoration-20261022
python -m kit.greekfill score docs/evidence/greek-restoration-20261022 --out work/greekfill-score.json
cmp work/greekfill-score.json docs/evidence/greek-restoration-20261022/score.json && echo reproduced
```

Run from a clone's root (the `work/` folder is git-ignored; make it first with `mkdir -p work`). On 22 October 2026 `check` printed `"ok": true` with every file's `"match": true` and exited 0, and `score` printed the verdict and wrote a file identical to the frozen one:

```text
{
 "verdict": "FAIL",
 "winners": [],
 ...
   "letter_acc": 0.1814,
   "kn_letter_acc": 0.331,
   "diff": -0.1496,
   "diff_lower": -0.2064,
...
reproduced
```

It worked when `check` exits 0 and `cmp` prints `reproduced`. To rebuild the baseline from the sources (about 8 minutes, 1 GB of clones):

```bash
git clone https://github.com/PerseusDL/canonical-greekLit work/per && git -C work/per checkout 0189b9c8d8d1f148133f2f0af309b4ee90ea4332
git clone https://github.com/OpenGreekAndLatin/First1KGreek work/f1k && git -C work/f1k checkout 03776b39f4047c5cff06f5296fae4b2bae4b08fb
python -m kit.greekfill corpus work/corpus.tsv work/per work/f1k --nproc 4
python -m kit.greekfill prep work/corpus.tsv work/greekfill-prep
python -m kit.greekfill check work/greekfill-prep
```

`corpus` prints `"matches_frozen": true` when the corpus's sha256 is `5c7c4684...`, and `check` then shows the three prep files matching (the replies and score are absent there, which is not a failure).

## Checks and controls

- **Pins.** `check` fails (exit 1) when any frozen file differs from its sha256 in `PINS` or a prep file is missing; `tests/test_greekfill.py` appends one space to `baseline.json` and sees it fail.
- **Byte-for-byte reproduction.** The test suite rescores the frozen replies and compares the bytes with `score.json`. As the control that this is not a constant, it sets one model's gap replies to the truth and sees that model's accuracy become 1.0 and the verdict turn to PASS.
- **The frozen rule could fail in every direction.** A model beats KN only with at least 90 % of requests parsed, a margin of at least 0.05 and a one-sided bootstrap bound above 0 (20,000 resamples, at 0.05 / 3 for three models); a win with probe accuracy of 0.50 or more is INCONCLUSIVE, since it could be recall. The tests feed `verdict()` each case.
- **Memorisation probe.** In the frozen run every arm, KN included, restored about 0.08 of probe letters (0.078 to 0.085), so no model recited De Musica.
- **Reproduction from sources** (22 Oct 2026, 4-core cloud container): the rebuilt corpus had sha256 `5c7c4684b7a4515ebd8840b963757b5a7680cfd2c986375a487b3d66bdb594bf` and `prep` wrote `manifest.json`, `key.json` and `baseline.json` byte-identical to the frozen ones ([evidence README](../evidence/greek-restoration-20261022/README.md#reproduction-22-october-2026)).

Claim label: Model output, for every accuracy, bound and verdict above (one run of three hosted models and one letter model on public edited text); Sourced fact, for the text's licence.

## Commands and options

### `python -m kit.greekfill`

```text
usage: python -m kit.greekfill [-h] {corpus,prep,run,score,check,chart} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `{corpus,prep,run,score,check,chart}` | required | The command, below |

### `python -m kit.greekfill corpus`

```text
usage: python -m kit.greekfill corpus [-h] [--nproc NPROC]
                                      CORPUS.tsv ROOT [ROOT ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `CORPUS.tsv` | required | Output corpus file, replaced if present |
| `ROOT` | required | Clone folders, read in the order given: Perseus first, then First1KGreek, as in the frozen run (the order changes the corpus and so the baseline) |
| `--nproc NPROC` | none (`NPROC` or 3) | Worker processes for parsing |

### `python -m kit.greekfill prep`

```text
usage: python -m kit.greekfill prep [-h] [--cache CACHE] CORPUS.tsv OUT_DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `CORPUS.tsv` | required | The corpus from `corpus` |
| `OUT_DIR` | required | Folder for `manifest.json`, `key.json` and `baseline.json`, made if missing; those files are replaced |
| `--cache CACHE` | none | Folder to save the fitted KN models (`general.npz`, `phil.npz`) or reuse them when present |

### `python -m kit.greekfill run`

```text
usage: python -m kit.greekfill run [-h] [--limit LIMIT]
                                   [--per-model PER_MODEL] [--dry-run]
                                   OUT_DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT_DIR` | required | Folder with `manifest.json`; `replies.jsonl` is appended |
| `--limit LIMIT` | none | Send at most N requests |
| `--per-model PER_MODEL` | none | Send at most N unanswered requests per model (the smoke run used 2, the pilot 12) |
| `--dry-run` | off | Count the requests that would be sent and their worst-case cost; send nothing and read no token |

### `python -m kit.greekfill score`

```text
usage: python -m kit.greekfill score [-h] [--out OUT] OUT_DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT_DIR` | required | Folder with `manifest.json`, `key.json`, `baseline.json` and `replies.jsonl` |
| `--out OUT` | none (OUT_DIR/`score.json`) | Write the score here instead, so a frozen folder is not touched |

### `python -m kit.greekfill check`

```text
usage: python -m kit.greekfill check [-h] OUT_DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT_DIR` | required | Folder to check against the frozen pins |

### `python -m kit.greekfill chart`

```text
usage: python -m kit.greekfill chart [-h] SCORE.json OUT.svg
```

| Option | Default | Meaning |
| --- | --- | --- |
| `SCORE.json` | required | A `score.json` written by `score` |
| `OUT.svg` | required | The SVG file to write (replaced if present) |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `HF_TOKEN` | unset | Hugging Face token for `run`; without it, `run` reads `~/.cache/huggingface/token` or `~/.huggingface/token`. Never printed or written |
| `NPROC` | `3` | Worker processes for `corpus` when `--nproc` is not given |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `test_text(corpus)` | str | `SystemExit` when De Musica is not in the corpus | The second half of `tlg1595.tlg221`, cut after the last space before the middle |
| `letters(s)` | str | None | The letters of s (spaces and anything else dropped) |
| `normalise_reply(r)` | str | None | A reply reduced to Greek capitals: accents stripped, any sigma as lunate sigma, everything else dropped |
| `letter_hits(guess, truth)` | int | None | Position-wise letter matches over the truth's letters (missing or extra letters do not help) |
| `make_items(text, rng)` | (gaps, memos), lists of dicts | None | 190 gap items (`id`, `L`, `left`, `right`, `truth`) and 40 probes (`id`, `prefix`, `truth`) from non-overlapping 150-symbol windows |
| `build_kn(corpus, cache=None)` | `MixtureLM` | None | Fits (or loads from cache) the general and Philodemus order-8 models and mixes them with `WEIGHTS` |
| `kn_fill(lm, left, right, L)` | str | None | Best L-letter fill: beam search (`BEAM`) on the left context, rescored with `RIGHT` symbols of right context |
| `kn_continue(lm, prefix, n)` | str | None | Greedy continuation to n letters (never two spaces in a row) |
| `gap_prompt(it)` | str | None | `PROMPT_GAP` filled for one gap item |
| `prep(corpus, out, cache=None)` | dict of sha256 per file | `SystemExit` from `test_text` | Writes the manifest, key and baseline and prints the counts, pins and KN accuracy |
| `boot_lower(diff_by_item, w_by_item, q, n, seed)` | float | None | Lower q-quantile of the letter-weighted mean difference, resampling items |
| `verdict(per_model)` | (verdict, rows, winners) | None | The frozen readout: PASS, INCONCLUSIVE, VOID or FAIL |
| `score(out, dest=None)` | dict (the `score.json` content) | `KeyError` or `FileNotFoundError` on a malformed folder | Score replies.jsonl in out against key.json and baseline.json; write dest (default out/score.json) and print it |
| `token()` | str | `SystemExit` when no token is found | The Hugging Face token from `HF_TOKEN` or the huggingface CLI's saved token file; never printed or written |
| `send(payload, tok, tries=3)` | (reply dict, None) or (None, error string) | None | POST one chat request to the router; 429 waits and retries, other client errors return at once |
| `body(m, req)` | dict | None | The chat request for one manifest request: its own model and prompt, temperature 0, `max_tokens` from the manifest |
| `priced(m, model, usage)` | float, USD | None | Cost of one reply from its reported usage and the manifest's price table; the worst-case reserve without usage |
| `run(d, limit=None, per_model=None, dry_run=False)` | dict | `SystemExit` from `token` | Sends the unanswered requests in order under the cap; returns `sent`, `spent_usd`, `answered`, `requests`, `stopped` (or the dry-run counts) |
| `sha256_file(path)` | str | `FileNotFoundError` | Hex sha256 of a file's bytes |
| `check_pins(d)` | dict `{"ok", "files"}` | None | Each pinned file in d against `PINS`; ok needs the three prep files present and every present file equal |
| `chart_svg(res)` | str (SVG) | `KeyError` on a dict that is not a score | Bar chart of gap letter accuracy by gap length for KN and each model |
| `build_parser()` | `argparse.ArgumentParser` | None | The command line above |
| `main(argv=None)` | int exit code | `SystemExit` from argparse or the functions above | Runs one command |
| `clean(text: str)` | str | None | Uppercase base letters (lunate sigma), non-letters as single boundaries (`kit/greekkn.py`) |
| `encode(text: str, pad: int=1)` | int8 array | None | Symbol ids with `pad` leading and one trailing boundary |
| `KNModel(order=7, discount='modified', min_count=1)` | model | `ValueError` for an order outside 1 to 13 | Interpolated modified Kneser-Ney letter model: `fit_texts`, `fit_sequences`, `next_logprobs`, `seq_logprobs`, `save`, `load` |
| `NgramLM(model: KNModel)` | language model | None | `score`, `text_logprobs`, `next_logprobs`, `bits_per_symbol`, `per_letter` over one fitted model |
| `MixtureLM(components, weights=None)` | language model | None | p = sum of w_i p_i over component models; `fit_weights` fits the weights by EM |
| `em_weights(component_logprobs, iters=100)` | numpy array | None | EM mixture weights from precomputed per-symbol log probs (equal-length arrays) |
| `normalise(raw: str)` | str | None | TEI body text to capitals: brackets dropped (letters kept), hyphenation joined, lacuna dots a boundary |
| `doc_text(path: str)` | (path, str or None) | None | The normalised text of a TEI file's `<body>`, or None when it does not parse or has no body |
| `build_corpus(out_path, roots, nproc=None)` | dict `files`, `kept`, `letters`, `sha256` | `OSError` on unwritable output | Writes `DOCID<TAB>TEXT` per document from every `*grc*.xml` under each root, sorted within each root; documents under 200 symbols are left out |

## Inputs

- **CORPUS.tsv** (for `prep`): UTF-8, one line per document, `DOCID<TAB>TEXT`, TEXT in the 24 capitals `ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ` and single spaces. It must contain `tlg1595.tlg221` (De Musica, the test text) and `tlg1595.tlg370` (Volumina Rhetorica, the Philodemus component). Every other `tlg1595` document is left out of training. The frozen corpus has 1,935 lines, 372,556,150 bytes.
- **ROOT** folders (for `corpus`): clones of the two TEI repositories; every file whose name matches `*grc*.xml` is read.
- **OUT_DIR** (for `run`, `score`, `check`): the folder `prep` wrote; `run` adds `replies.jsonl`. The frozen folder is [`docs/evidence/greek-restoration-20261022/`](../evidence/greek-restoration-20261022/README.md).
- **SCORE.json** (for `chart`): a file written by `score`.

## Outputs

`prep` prints `requests`, `gaps`, `memos`, `pins` and `kn_letter_acc`. `run` prints a progress line every 50 requests and ends with `done: sent N, priced cost N USD; answered N of N`; with `--dry-run` it prints `would_send`, `by_model`, `spent_usd`, `worst_case_usd`, `cap_usd`, `fits_cap`, `answered` and `requests`. `corpus` prints `files`, `kept`, `letters`, `sha256` and `matches_frozen`. `check` prints `ok` and, per file, `present`, `sha256`, `pinned` and `match`. `chart` prints `out` and `bytes`.

`score.json` (also printed):

| Field | Type | Meaning |
| --- | --- | --- |
| `verdict` | string | `PASS`, `INCONCLUSIVE`, `VOID` or `FAIL` under the frozen rule |
| `winners` | list | Models that beat KN and are not memorised |
| `checks` | object | Per model: `parse_ok`, `beats_kn`, `memorised` |
| `per_model.M.letter_acc` | number, 0 to 1 | Share of hidden letters restored in place over the 190 gaps |
| `per_model.M.kn_letter_acc` | number | KN's letter accuracy, repeated |
| `per_model.M.diff`, `diff_lower` | number | Model minus KN, and its one-sided bootstrap lower bound |
| `per_model.M.parsed_share` | number | Share of the model's 230 requests whose reply held a Greek letter |
| `per_model.M.memo_acc` | number | Mean probe letter accuracy (memorisation) |
| `per_model.M.by_len.L` | object | `acc` (letter accuracy) and `exact` (share of gaps restored whole) for gap length L |
| `kn` | object | KN's `letter_acc`, `memo_acc` and `by_len` |
| `replies`, `requests` | integer | Replies read and requests in the manifest |
| `priced_usd` | number, USD | Sum of the replies' priced cost |
| `rule` | object | The frozen thresholds (`RULE`) |

`replies.jsonl` lines hold `id` (`MODEL|ITEM`), `reply` (raw text), `usage`, `usd` and `t` (Unix time).

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `check`, every file matches; for `run --dry-run`, the worst case fits the cap; for `run`, it stopped only because nothing was left to send |
| `1` | `check`: a file differs from its pin or a prep file is missing; also an uncaught `SystemExit` message (no token, De Musica missing) |
| `2` | A missing or wrong argument (argparse) |
| `3` | `run`: stopped at the cost cap or after a failed request; `run --dry-run`: the worst case would pass the cap |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `De Musica (tlg1595.tlg221) not in corpus` | The corpus was built without First1KGreek, or from other roots | Rebuild with both clones, Perseus first |
| ``no Hugging Face token: set HF_TOKEN or run `huggingface-cli login` `` | `run` found no token | Set `HF_TOKEN`, or use `--dry-run` to count without one |
| `order must be 1..N` | `KNModel` asked for an order outside 1 to 13 | Use an order from 1 to 13 |
| `stop: priced cost N plus worst N would pass N` | The next request could pass the manifest's cap | Nothing to fix; the run stops by design (exit 3). Raising the cap means a new manifest and a new go-ahead |
| `request failed, stopping: ID ERROR` | The router failed three times or refused the request | Read the error; rerun `run` later, it resumes without re-asking answered requests |
| `check` shows `"match": false` | A frozen file was edited, or `prep` ran on another corpus | Restore the file from git; for a rebuild, check the clone commits and root order |

## How it works

1. **Corpus** (`kit/greekkn.py`, `build_corpus`): each TEI `<body>` loses `teiHeader`, `note`, `head`, `bibl`, `ref`, `label`, `figDesc`, `del`, `sic`, `orig`, `abbr` and non-Greek `foreign` elements (`DROP`); editorial brackets are removed with their letters kept, line-end hyphenation is joined, a run of lacuna dots becomes a boundary, accents are stripped, every sigma becomes `Ϲ`, and anything outside the 24 capitals is a word boundary.
2. **Items** (`make_items`, seed `SEED` = 20261022): 230 windows of `WINDOW` = 150 symbols from the test text; `PER_LEN` = 38 gaps for each length in `GAP_LENS` = (1, 2, 3, 5, 8), starting 60 to 90 symbols in, and `MEMO_N` = 40 probes of `MEMO_PREFIX` = 100 symbols with up to `MEMO_LETTERS` = 40 letters of truth.
3. **KN baseline** (`build_kn`): documents whose sha256 of the id, mod 100, is 6 or more, in corpus order, until `KN_TRAIN` = 16,000,000 symbols; order `KN_ORDER` = 8, modified Kneser-Ney (Chen and Goodman 1999), discounts from the count-of-counts; a second order-8 model on Volumina Rhetorica; mixed with `WEIGHTS` = (0.728, 0.272), weights fitted earlier by EM on the first half of De Musica. `kn_fill` keeps the `BEAM` = 256 best left-to-right fills and picks the one whose text plus the next `RIGHT` = 24 symbols scores best.
4. **Requests**: one per model and item (690), in a shuffled order; temperature 0, `MAX_TOKENS` = 48; prices from the router listing of 22 Oct 2026 in `MODELS`; the runner stops before `CAP_USD` = 1.20 could be passed, counting a reply without usage at `PER_CALL_WORST` = 0.0012 USD.
5. **Score**: replies to capitals, position-wise letter hits, letter-weighted bootstrap of the per-item difference (`RULE`: `boot` 20,000, `boot_seed` 0, `alpha` 0.05 / 3), then `verdict`.

Related prior work, not reproduced here: neural restoration of Greek inscriptions and papyri, such as Pythia ([Assael, Sommerschield and Prag 2019](https://arxiv.org/abs/1910.06262)), Ithaca ([Assael et al., Nature 2022](https://doi.org/10.1038/s41586-022-04448-z)), instruction-tuned Llama for papyri and inscriptions ([Cullhed 2024](https://arxiv.org/abs/2409.13870)), Apollo Restore ([McGovern et al. 2026](https://arxiv.org/abs/2609.22455)), and n-gram and BERT-like supplement suggestions for the Herculaneum papyri ([Del Grosso et al., LREC 2026](https://aclanthology.org/2026.lrec-1.41/)). This benchmark compares general hosted chat models with a letter n-gram model on one Philodemus text; it does not test those trained restorers.

## Cost and time

Measured on 22 October 2026 on a 4-core Claude cloud container (Python 3.13, numpy 2.5.3): `score` 1.4 s; `corpus` 5 min 26 s with 4 workers; `prep` 1 min 57 s including fitting both KN models; the test suite's greekfill tests about 2 s. Memory not measured. All of this is a short CPU job that runs locally (the Modal rule, hard rule 11, needs no Modal here). The frozen `run` sent 690 requests for 0.066 USD of priced cost (about 224 input and 14 output tokens per request on average); a new run of the same manifest would cost about the same, needs the go-ahead first, and is a new run, not the frozen test.

## For agents

- **Command:** `python -m kit.greekfill check docs/evidence/greek-restoration-20261022`, then `python -m kit.greekfill score docs/evidence/greek-restoration-20261022 --out work/greekfill-score.json`; both print JSON.
- **Parse:** from `check`, `ok` and each file's `match`; from `score`, `verdict`, `per_model.MODEL.letter_acc`, `diff_lower`, `memo_acc`, and `kn.letter_acc`.
- **Rerun:** `check`, `score --out` and `chart` are safe to rerun. `score` without `--out` replaces OUT_DIR/`score.json`; `prep` replaces its three files; `run` appends and resumes, never re-asking an answered request.
- **Success:** exit 0; `check` with `"ok": true`; a rescored file byte-identical to `score.json`; `verdict` `FAIL` with KN at 0.331 for the frozen run.
- **Not a pass:** a score from a folder whose `check` fails; a new prompt or model on these items reported as the frozen test; a win with probe accuracy at or above 0.50; a KN fill called a reading.
- **Go-ahead:** `run` without `--dry-run` (paid requests to the router). Nothing else.
- **Never:** edit the files in `docs/evidence/greek-restoration-20261022/`; drop the CC BY-SA 4.0 attribution when copying them; call a fill or a model's reply a reading of a scroll.

## Tests

`python -m unittest tests.test_greekfill -v` (skips without numpy). It covers reply normalisation, position-wise letter hits, item cutting, the test-text cut, every verdict branch, the bootstrap's sign, KN fills and continuations on repeated text, KN distributions summing to 1, save and load, mixtures, the TEI corpus builder on small made-up files, the frozen pins (and a changed file failing them), byte-for-byte rescoring of the frozen run with the truth-reply control, and the runner's per-model limit, resume, cap stop, failure stop and dry run with the network replaced. It does not contact the router or rebuild the full corpus; the reproduction from sources is recorded in the evidence README.

## History

- 2026-10-22: ported from the code that ran the frozen test, with the evidence files, the preregistration and result page, and the chart (branch `claude/greek-restoration-benchmark` from `0fbc49a`).

## Related

- [Preregistration and result](../prereg/2026-10-22-greek-restoration.md): the frozen rule and the numbers.
- [Frozen files](../evidence/greek-restoration-20261022/README.md): hashes, reproduction and the text's licence.
- [greeklm](greeklm.md): Scroll Text Reader's own order-5 letter model, a different model.
- [letterread](letterread.md): proposes letters on ink maps; this benchmark uses none.
- `results.json` key `text_restoration_checks`: the numbers with their source.
- [Chart](../media/greek-restoration-by-gap-length.svg): letter accuracy by gap length.
