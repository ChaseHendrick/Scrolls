# greeklm: letter language model for Greek in scriptio continua

`python -m kit greeklm` builds a Kneser-Ney letter n-gram model of Greek written as capitals with no spaces from TEI editions, and scores strings in bits per letter; the letter reader can add a decode with it beside its ink-only letters.

| Field | Value |
| --- | --- |
| Id | `greeklm` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Letters and titles |
| Run | `python -m kit greeklm build`, `python -m kit greeklm score`, `from kit import greeklm` |
| Code | `kit/greeklm.py`, `kit/cli.py` (`cmd_greeklm`) |
| Tests | `tests/test_greeklm.py`, `tests/test_letterread.py` |
| Needs | Python 3.10 or newer and numpy (the `reader` extra of the `scrolls-workbench` package installs it); Greek TEI XML texts in Unicode, such as the PerseusDL canonical-greekLit editions (CC BY-SA 4.0), fetched by you |
| Runs on | Any CPU. Building from two Perseus texts (937,054 training letters) took 9.7 s with a peak of 89 MB, and scoring a short string 1.0 s from the command line (measured 2026-10-16, 4-core Intel Xeon cloud container shared with other jobs) |
| Network | None. It reads local files only; you download the TEI texts yourself |
| Writes | `build`: the model file OUT, at exactly that path (its folder made if missing), replacing any file there. `score`: nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-14 ([PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57), with the Greek letter reader); in the installable package `scrolls-workbench` since [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58) the same day |
| Guide | [letter-reader.md, Optional language model](../letter-reader.md#optional-language-model) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

Herculaneum texts are written in scriptio continua: Greek capitals one after another, with no spaces between words and no accents. The letter reader ([letterread](letterread.md)) was trained on uniform random letter strings, so its network knows letter shapes and nothing of Greek. `greeklm` is a separate prior over letter strings that can be switched on beside it: an interpolated Kneser-Ney n-gram model over the reader's 24 capitals (`ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ`, every sigma written as the lunate `Ϲ`), order 5 by default, so each letter is predicted from the four before it.

`build` reads TEI XML editions, keeps their body text (headers, notes, apparatus and similar elements removed), turns it into one string of capitals (accents and breathings dropped, every sigma lunate, spaces, punctuation and any non-Greek letter dropped), holds out every 20th block of 2,000 letters, counts n-grams on the rest, writes the counts to an `.npz` file and prints the held-out bits per letter. `score` prints a string's cleaned letters and its bits per letter. Bits per letter is the average of minus log2 of the probability the model gives each letter: lower means more Greek-like to this model, and uniform guessing among 24 letters is log2 24 = 4.585.

The reader uses a model through `--lm`: `python -m kit letterread IMAGE --weights W --lm MODEL.npz` adds to each line a second decode, `with_lm`, a CTC beam search in which every letter's score gets 0.5 times its log-probability under the model (`LM_WEIGHT` in `kit/letterread.py`). The ink-only string is always reported and never replaced. The benchmark scripts of [letters-training](letters-training.md) take `--lm` the same way, and `eval_pages.py --text` and `eval_p1667_text.py decoys` use this module's text cleaning.

It never sees an image. A `with_lm` string is the model's guess at Greek that fits the ink, not evidence from the ink, and neither string is a reading: only papyrologists read and transcribe. The model will recite text it was trained on, so keep any text you evaluate on out of its corpus (for Herculaneum work, leave Philodemus out). A model file holds counts derived from its source editions (CC BY-SA 4.0 for Perseus); keep it out of git and rebuild it when you need it.

## When to use it

- Adding the second, language-model decode to a letter read (`letterread --lm`, or `--lm` on `eval_p172.py`, `eval_p1667.py`, `eval_pages.py` and `demo_p1667.py`), to see whether a Greek-like string fits the same ink and how far it moves from the ink-only string.
- Measuring how Greek-like a letter string is, in bits per letter, against a corpus.
- Sampling Greek-like letter strings (`KNLetterLM.sample`) for a dry run of a scoring rule: the PHerc. 1667 text test used such samples to show that a fit score alone could not separate Greek-like noise from the real text ([log](../logs/2026-10-14-letter-reader.md)).

Do not use it:

- To read a scroll or claim what it says: read with [letterread](letterread.md), trust only its `ink_only` letters and its controls, and leave reading to papyrologists.
- To score or decode a text that is in its corpus: it recites it. Build from other authors.
- For word division, accents or Latin: it knows the 24 capitals only. A Latin or Beta code TEI file gives no letters at all (the build prints `"train_letters": 0`).
- To check a letter reader's accuracy: use the benchmark scripts in [letters-training](letters-training.md), or `python -m kit letterlines score` ([letterlines](letterlines.md)), which compare reads with references.

## Quick start

```bash
mkdir -p work/perseus work/letters
curl -sSfL -o work/perseus/tlg0004.tlg001.perseus-grc2.xml https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0004/tlg001/tlg0004.tlg001.perseus-grc2.xml
curl -sSfL -o work/perseus/tlg0059.tlg030.perseus-grc2.xml https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0059/tlg030/tlg0059.tlg030.perseus-grc2.xml
python -m kit greeklm build work/letters/greek5.npz work/perseus/tlg0004.tlg001.perseus-grc2.xml work/perseus/tlg0059.tlg030.perseus-grc2.xml
python -m kit greeklm score work/letters/greek5.npz "καὶ τὸν θεόν"
```

The two files are Diogenes Laertius, *Lives*, and Plato, *Republic*, the corpus of the released numbers ([guide](../letter-reader.md#optional-language-model), which clones the whole repository with `git clone --depth 1 https://github.com/PerseusDL/canonical-greekLit work/perseus` instead; then the paths are under `work/perseus/data/`). Run it from a clone's root, where `.gitignore` keeps `work/` out of git. On 2026-10-16 (Perseus `master` at `0189b9c`) it printed:

```
{
  "train_letters": 937054,
  "held_letters": 48000,
  "bits_per_letter": 2.556,
  "out": "work/letters/greek5.npz",
  "order": 5
}
{"letters": "ΚΑΙΤΟΝΘΕΟΝ", "bits_per_letter": 2.84}
```

It worked when both exit codes are 0, `train_letters` is not 0 and the held-out `bits_per_letter` is well under 4.585. These are the numbers in `results.json` (`letter_reader_checks`, first entry, `language_model`: 937,054 letters, 2.556 bits per letter). The model file was 542,092 bytes. Then read with it: `python -m kit letterread MAP.png --weights letters-v2-ccby --letter-px 86 --lm work/letters/greek5.npz`, where `MAP.png` is an image of ink and 86 its letter height in pixels ([letterread](letterread.md)).

## Checks and controls

- **Held-out letters.** `build` fits on 19 of every 20 blocks of 2,000 letters and reports bits per letter on the 20th blocks (up to 50,000 letters). A model that learned Greek letter statistics is well under 4.585; one that learned nothing is at 4.585 (an empty corpus: `bits_per_letter` is null at build and every string scores 4.585). The quick-start model: 2.556.
- **A text outside the corpus.** Score another author's text. Xenophon, *Anabasis* (`tlg0032.tlg006`, all 290,095 of its letters) scores 2.826 bits per letter under the quick-start model (measured again 2026-10-16; the same as `language_model.bits_per_letter_xenophon_anabasis` in `results.json`). A string that is not Greek-like scores high: `ΨΞΖΨΞΖΨΞΖΨ` scored 7.9.
- **Ink-only beside it.** In every read the `ink_only` string stays next to `with_lm`. When they disagree, the ink-only string is what the image supports; a large gap means the model, not the ink, is doing the work.
- **What it did to reads (Model output).** On synthetic pages whose lines were Xenophon (not in the corpus), the prototype reader's character error fell from 0.138 to 0.108 on the ink-map look and from 0.019 to 0.008 on the drawn-label look (`letter_reader_checks[0].synthetic_pages`, 2026-10-08). On real drawings it does not help consistently: `letters-v2-real` on the PHerc. 1667 label groups, 0.025 ink only and 0.041 with the model (`letter_reader_checks[5]`); on the PHerc. 172 test half with columns found, `letters-v2-real` 0.426 and 0.451, `letters-v2-ccby` 0.541 and 0.500 (`letter_reader_checks[14]`, rows 5 and 6). Interpretation: treat `with_lm` as a diagnostic, not a better read.
- **Greek-like is not the text.** In the dry run of the PHerc. 1667 text test (9 October 2026), 40 samples from this model fit the published text better than every shuffled decoy in all 40 draws (p = 0.01), with no link to the text at all ([log](../logs/2026-10-14-letter-reader.md)). A score that rewards Greek-like strings cannot show that a read carries a text.

Claim label: Model output for bits per letter and for every decode made with the model; Sourced fact for the corpus and its license (PerseusDL canonical-greekLit, CC BY-SA 4.0).

## Commands and options

### `python -m kit greeklm build`

```
usage: python -m kit greeklm build [-h] [--order ORDER] out tei [tei ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | The model file to write, at exactly this path (no `.npz` is added to a bare name); its folder is made if missing, and a file already there is replaced. Keep it out of git |
| `tei` | required | One or more TEI XML files, read as UTF-8 (bytes that do not decode are replaced). Each file's body text is cleaned and cut into 2,000-letter blocks on its own |
| `--order ORDER` | `5` | The n-gram order: each letter is predicted from the ORDER minus 1 letters before it. `0` gives the uniform model; a negative order stops with an `IndexError` traceback (exit code 1). Higher orders give bigger files and fewer seen contexts |

### `python -m kit greeklm score`

```
usage: python -m kit greeklm score [-h] model text [text ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `model` | required | A model file written by `build` (or by `KNLetterLM.save`) |
| `text` | required | One or more words, joined with spaces and cleaned as the corpus was, so `"καὶ τὸν θεόν"` and `ΚΑΙΤΟΝΘΕΟΝ` score the same. Latin look-alikes (`KAI` typed in Latin letters), digits and punctuation are dropped |

## Python API

```python
from kit import greeklm
lm, stats = greeklm.build(["work/perseus/tlg0004.tlg001.perseus-grc2.xml"], order=5)
lm.save("work/letters/greek5.npz")
lm = greeklm.KNLetterLM.load("work/letters/greek5.npz")
print(lm.bits_per_letter(greeklm.clean_text("καὶ τὸν θεόν")))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `clean_text(s)` | str of letters from `ALPHABET` only | Nothing of its own | NFD-normalizes, drops combining marks (accents, breathings, iota subscript), upper-cases, writes `Σ` and `ς` as `Ϲ`, and keeps only the 24 capitals |
| `tei_text(xml)` | str | Nothing of its own | Removes `<teiHeader>` and the elements `note`, `bibl`, `head`, `app`, `rdg`, `del`, `speaker`, `ref` and `foreign` with their content, then every other tag and every named entity (`&amp;`), each replaced by a space. Regular expressions, not an XML parser |
| `KNLetterLM(order=5, discount=0.75)` | A model object, empty until `fit` or `load` | Nothing | Attributes: `order`, `D` (the discount), `counts` and `cont` (per order, a dict from a context tuple of letter indices to 24 counts), `file` and `sha256` (set by `load`, else `None`) |
| `KNLetterLM.fit(texts)` | the model itself | Nothing of its own | Counts every n-gram of each string (letters outside `ALPHABET` are skipped) for orders 1 to `order`, then the continuation counts of the lower orders. Call it once: a second call adds counts again |
| `KNLetterLM.logp_next(prefix)` | numpy array of 24 natural-log probabilities, in `ALPHABET` order | Nothing of its own | For the letter after `prefix`; uses its last `order` minus 1 characters, letters outside `ALPHABET` among them ignored. Sums to 1 after `exp` in every context. This is the method the reader's beam search calls |
| `KNLetterLM.score(text)` | float, total log-probability in nats | `KeyError` for a character outside `ALPHABET` | Clean the text first with `clean_text` |
| `KNLetterLM.bits_per_letter(text)` | float | `KeyError` as `score` | Minus `score` divided by the letters and by ln 2. An empty string gives 0 (the command line prints null instead) |
| `KNLetterLM.sample(rng, n, prefix="")` | str of `n` letters | Nothing of its own | Draws letter by letter from `logp_next`; `rng` is a numpy `Generator`, such as `numpy.random.default_rng(0)` |
| `KNLetterLM.save(path)` | `None` | `OSError` (a folder as `path`, no permission) | Writes a compressed `.npz` to exactly `path`, making its folder. The same counts give a byte-identical file |
| `KNLetterLM.load(path)` | a model | `OSError` for a missing file; `KeyError` (`'meta is not a file in the archive'`) for an `.npz` that greeklm did not write; `ValueError` for a file that is not an `.npz` | A class method. Given a path, it records the file's name (never its folder) and SHA-256 in `file` and `sha256`; the reader puts them, with `order`, in its result's `options.lm` |
| `build(xml_files, order=5, holdout_every=20)` | `(model, stats)`; `stats` is `{"train_letters": int, "held_letters": int, "bits_per_letter": float or None}` | `OSError` for an unreadable file | Cuts each file's cleaned text into 2,000-letter blocks; block i of a file is held out when i % `holdout_every` equals `holdout_every` minus 1. Bits per letter is on the first 50,000 held-out letters, rounded to 3 decimals; `None` when nothing is held out |

`ALPHABET` (the 24 capitals, lunate sigma U+03F9) is the letter order of every 24-vector.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| TEI files (`build`) | XML text in UTF-8 with Greek in Unicode, precomposed or with combining accents | The whole file is read into memory. Only Greek letters count; Beta code (Greek typed in Latin letters) and Latin texts give no letters. Perseus files sit under `data/tlgAUTHOR/tlgWORK/` in [PerseusDL/canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit) |
| Model file (`score`, `letterread --lm`) | `.npz` from `build` | Holds `meta` (JSON: `order`, `D`, `tables`) and, per table, `counts{n}_k` or `cont{n}_k` (int8 contexts of letter indices, padded with -1 to `order` columns) with `counts{n}_v` or `cont{n}_v` (float32 rows of 24 counts) |
| Text (`score`) | Words on the command line | Any Greek, accented or not; cleaned like the corpus |

## Outputs

`build` prints one JSON object, indented:

| Field | Type | Meaning |
| --- | --- | --- |
| `train_letters` | int | Letters the model was fitted on |
| `held_letters` | int | Held-out letters scored, at most 50,000 |
| `bits_per_letter` | float (3 decimals) or null | Bits per letter on the held-out letters; null when none were held out (a corpus under 40,000 letters per file holds out nothing) |
| `out` | str | The model file, as given |
| `order` | int | The n-gram order |

`score` prints one JSON line:

| Field | Type | Meaning |
| --- | --- | --- |
| `letters` | str | The text after cleaning, as scored |
| `bits_per_letter` | float (3 decimals) or null | Bits per letter of `letters`; null when no Greek letter is left |

Both print Greek as UTF-8 when standard output is a pipe, a file or a console that cannot show Greek.

| Exit code | Meaning |
| --- | --- |
| `0` | Built or scored. Check `train_letters` and `bits_per_letter`: an empty corpus also exits 0 |
| `1` | An error the command does not catch, with a traceback, such as a negative `--order` (`IndexError`) |
| `2` | A usage error from the argument parser, or a missing module or an unreadable file, with the message on stderr (see Failure modes) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no action or no text | Check the command against Commands and options |
| `No module named 'numpy'`, exit code 2 | numpy is not installed | `python -m pip install "scrolls-workbench[reader]"`, or `python -m pip install numpy` in a clone |
| `[Errno 2] No such file or directory: 'PATH'`, exit code 2 | A TEI file or the model file does not exist | Fix the path |
| `[Errno 21] Is a directory: 'PATH'`, exit code 2 | `out` is a folder | Give a file name, such as `work/letters/greek5.npz` |
| `'meta is not a file in the archive'`, exit code 2 | The model is an `.npz` that greeklm did not write, such as letter reader weights | Give the file `build` wrote |
| `This file contains pickled (object) data. ...`, exit code 2 | The model path is not an `.npz` at all, such as a TEI file | Give the file `build` wrote |
| `IndexError: list index out of range` and a traceback, exit code 1 | `--order` below 0 | Use an order of 1 or more (5 is the default) |
| `"train_letters": 0` and `"bits_per_letter": null`, exit code 0 | No Greek letters in the TEI files: Latin, Beta code, or the wrong files | Check the files; such a model is uniform and scores every string 4.585 |
| `"bits_per_letter": null` from `score`, exit code 0 | No Greek letter left after cleaning, such as `KAI` typed in Latin letters | Type the Greek letters |
| Every string scores 4.585 | The model was built from no letters, or with `--order 0` | Rebuild from Greek texts with order 1 or more |

## How it works

1. **Text.** `tei_text` strips the TEI markup listed under Python API. `clean_text` decomposes each character (NFD), drops combining marks, upper-cases, writes every sigma as `Ϲ` and keeps only `ALPHABET`, so the corpus looks like scriptio continua in the reader's alphabet.
2. **Split.** `build` cuts each file's letters into blocks of 2,000; block i goes to the held-out set when i % 20 equals 19 (`holdout_every=20`), the rest to training.
3. **Counts.** `fit` counts, for each order n from 1 to `order`, how often each letter follows each context of n minus 1 letters. For the lower orders it also keeps continuation counts: for each shorter context and letter, the number of distinct letters seen before that context in a longer n-gram (the Kneser-Ney idea: a letter that follows many different contexts is a better guess in an unseen one).
4. **Probability.** Interpolated Kneser-Ney with one absolute discount, `D` = 0.75: at the top order with raw counts c, and at lower orders with continuation counts, p(w | context) = max(c(context, w) minus D, 0) / c(context) + D times the number of letters seen after the context / c(context) times p(w | the context less its first letter). A context never seen falls back to the shorter one, and order 0 is uniform, 1/24. Distributions are cached by context, up to 2,000,000 of them.
5. **Scores.** `logp_next` gives natural logs; `score` adds them in nats; `bits_per_letter` divides by the letters and by ln 2.
6. **In the reader.** `kit/letterread.py`'s `ctc_beam` runs a CTC prefix beam search (beam 32, the 8 most likely classes per frame) and adds `lm_weight` times `logp_next(prefix)` of each new letter to its score (shallow fusion); `lm_weight` is 0.5 (`LM_WEIGHT`) unless `--lm-weight` says otherwise. The orientation reads never use the model.
7. **File.** `save` writes the counts as int8 context keys and float32 count rows in a compressed `.npz` through a file handle, so the file is exactly the path given; `load` rebuilds the dictionaries and records the file's name and SHA-256.

The smoothing is the interpolated form of Kneser-Ney smoothing, as compared in Chen and Goodman's study of smoothing methods for n-gram language models (1998), with a single discount rather than their modified three-discount form.

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon cloud container (lscpu: 2.80 GHz) shared with other jobs, Python 3.13 and numpy 2.5.3:

| Step | Size | Time | Peak memory |
| --- | --- | --- | --- |
| `build`, two Perseus texts | 937,054 training letters; 542,092-byte model; 46,818 contexts at the top order | 9.7 s | 89 MB |
| `score` from the command line, one short string | 10 letters | 1.0 s (most of it loading) | 62 MB |
| `KNLetterLM.load` in Python | the same model | 0.39 s | not measured alone |
| `bits_per_letter` in Python, whole *Anabasis* | 290,095 letters | 6.8 s, and 14.9 s while another job ran | 79 MB (30,724 cached contexts) |

Nothing here needs a GPU or Modal. Memory grows with the cache on long, varied texts, up to its cap of 2,000,000 contexts; that limit was not reached or measured.

## For agents

- **Command:** `python -m kit greeklm build work/letters/greek5.npz TEI.xml [TEI.xml ...]`, then `python -m kit greeklm score work/letters/greek5.npz TEXT`; both print JSON on stdout. In a read: `python -m kit letterread IMAGE --weights letters-v2-ccby --letter-px H --lm work/letters/greek5.npz --json`.
- **Parse:** `build`: `train_letters` and `bits_per_letter` (held out). `score`: `letters` (what was scored) and `bits_per_letter`. In a read, each line's `ink_only` and `with_lm`, and `options.lm` (`file`, `sha256`, `order`) for provenance.
- **Rerun:** Safe. `build` replaces OUT; the same files and order give a byte-identical model (same SHA-256, checked 2026-10-16). `score` only reads.
- **Success:** Exit code 0, `train_letters` above 0 and held-out `bits_per_letter` well under 4.585 (2.556 for the released corpus).
- **Not a pass:** A null `bits_per_letter`, or 4.585 for every string (no Greek in the corpus); bits per letter on text that is in the corpus; a `with_lm` string offered as what the ink shows; a fit to a text that Greek-like samples also reach.
- **Go-ahead:** Nothing for building and scoring. Committing a model file or its corpus is never allowed (no data in git; counts derived from CC BY-SA 4.0 editions), and publishing any read of a prize-eligible scroll, with or without the model, is never allowed.
- **Never:** Call a `with_lm` or `ink_only` string a reading, or say letters were found; replace `ink_only` with `with_lm`; build from Philodemus or any text you then evaluate on.

## Tests

```bash
python -m unittest tests.test_greeklm -v
python -m unittest tests.test_letterread.PageTest.test_orientation_reads_leave_the_language_model_off tests.test_letterread.ApiTest.test_language_model_weight_defaults_as_on_the_command_line
```

`tests/test_greeklm.py` (7 tests, 0.07 s) covers text cleaning, TEI headers and notes left out, every next-letter distribution summing to 1 and positive, a model that learns a repeated text and scores random letters near uniform, save and load round trips, the exact output path with its folder made, and `build` and `score` from the command line. The two reader tests (about 10 s) check that the orientation reads leave the model off, that the default weight is 0.5 as on the command line, and that `options.lm` records the file name, SHA-256 and order. They skip without numpy. They do not use a real Perseus corpus, check the held-out split, `sample`, or a negative `--order`.

## History

- 2026-10-14: `load` records the model file's name and SHA-256 for the reader's results; the command prints Greek as UTF-8 in pipes and Windows consoles (`203018a`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).
- 2026-10-14: in the installable package, so `scrolls-workbench greeklm` runs it too (`2582ab7`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).
- 2026-10-14: `save` writes exactly the path given (numpy had added `.npz` to a bare name) and makes its folder; the tests were ported from the private workbench (`315efc3`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).
- 2026-10-14: first public version, released with the Greek letter reader (`19d2f95`, [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57)).

## Related

- [letterread](letterread.md): the Greek letter reader whose `--lm` uses this model, beside the ink-only decode.
- [letters-training](letters-training.md): training data, training and the benchmark scripts, several of which take `--lm`.
- [letterlines](letterlines.md): training lines from your own transcriptions, and character error on lines kept apart.
- [letterdemo](letterdemo.md): the offline check of a reader install.
- [The letter reader guide](../letter-reader.md#optional-language-model): how the guide builds and uses the model.
- [The letter reader log](../logs/2026-10-14-letter-reader.md): the corpus, its held-out and Xenophon numbers, and the dry run with samples of the model.
- [`results.json`](../results.json), key `letter_reader_checks`: `language_model` in the first entry, and the `with_lm` numbers of every benchmark.
