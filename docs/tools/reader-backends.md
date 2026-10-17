# reader-backends: Scroll Text Reader backends and session switching

Scroll Text Reader can switch between Greek LineNet and explicitly installed local Tesseract language packs, with model provenance, controls and validation before replacing a working selection.

| Field | Value |
| --- | --- |
| Id | `reader-backends` |
| Status | Experimental |
| Kind | kit module |
| Area | Letters and titles |
| Run | `python -m kit.reader_backends`, `from kit import reader_backends` |
| Code | `kit/reader_backends.py` |
| Tests | `tests/test_reader_backends.py` |
| Needs | Python 3.10 or newer. Discovery uses the standard library. Reading needs numpy and Pillow; Tesseract 5 and its explicitly installed language packs. Checked with Tesseract 5.5.0 |
| Runs on | Local CPU; the synthetic Latin read and its two controls finished in under one second here on 17 October 2026. Scroll-image accuracy and large-page timing are not measured |
| Network | None for Tesseract. The Greek route uses the existing hash-verified released-weight loader, which may download a requested release from GitHub |
| Writes | Temporary PNGs, deleted after the read; through the letterread CLI, only the requested JSON output. No model installation |
| Go-ahead | Not needed for local public-data use; publication of private results still needs clearance |
| Released | New source change, not a separate released model or tagged package |
| Checked | 2026-10-17 against commit `869d621` and the reader routing change |

## What it does

The original line network can emit Greek capitals. Changing the requested language does not add new letters to its weights. This adapter offers an explicit choice between that Greek model and Tesseract, a separate local OCR engine with language-specific `.traineddata` files. It checks the loaded Greek checkpoint's actual alphabet before annotating its output as Greek.

The CLI and `read()` choose per call. `ReaderSession` keeps a selection across calls and validates a replacement before activating it, preserving the previous selection if a switch fails. Greek networks are validated with a small forward pass and stay loaded; Tesseract still launches a local process for each read. Neither interface is an automatic search for whichever model produces the most text. Unsupported languages, missing packs and incompatible options are errors. The Greek route retains its existing schema and controls. Tesseract returns a separate word schema; its confidence is neither a glyph probability nor the Greek reader's scroll validation gate.

Tesseract is [Apache 2.0 code](https://github.com/tesseract-ocr/tesseract). The official [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) packs are Apache 2.0, but a local pack may be different. Results therefore record every local pack's SHA-256 and say its licence is not inferred from its filename. Check the source before redistributing any custom pack.

## When to use it

Use it to read a printed Latin, Ancient Greek, Hebrew or other supported page with the corresponding installed pack, or to compare a local OCR baseline against Greek LineNet on known-answer public images. `lat`, `grc` and `heb` mean the OCR model's language; their availability does not establish that a particular scroll contains that language.

Do not use a successful printed-text smoke test as a claim about damaged manuscripts or scroll ink maps. Do not send target maps to a remote OCR service or treat OCR text as a papyrologist's reading. No remote backend is implemented here.

## Quick start

```bash
python -m kit.reader_backends --json
python -m kit.reader_backends --tessdata LOCAL_PACKS --json
python -m kit letterread PAGE.png --backend tesseract --language lat \
  --tessdata LOCAL_PACKS --polarity dark --ocr-psm 7 --json --out words.json
```

`LOCAL_PACKS` holds `lat.traineddata` (and any other explicitly installed packs); `PAGE.png` is a public or synthetic image. Install Tesseract and language packs with your system package manager, or obtain packs from the official source at a pinned revision and verify their digest. This command never installs them. Omitting `--tessdata` uses Tesseract's configured system location, including its `TESSDATA_PREFIX` setting; discovery reports the languages actually available there. `osd` is orientation data, not a recognition language.

On 17 October, a synthetic DejaVu Serif Latin line read as `SENATUS POPULUSQUE ROMANUS`, exactly the known input; both blank and shuffled controls kept zero alphabetic characters. The tested `lat`, `grc` and `heb` packs were explicitly obtained from tessdata_fast revision `87416418657359cb625c412a48b6e1d6d41c29bd` and verified against the pinned Git blob identities before local installation. An independent printed-text check also transcribed `ΑΛΦΑ ΒΗΤΑ` and `שלום עולם` exactly with their respective packs. Its Latin `SALVE ROMA` was transcribed exactly but failed the control comparison: the shuffled image kept 13 alphabetic characters against 9 in the real image. Greek blank and shuffle controls kept 1 and 3 characters. These tiny fixtures establish neither script-wide accuracy nor scroll accuracy, and show why successful OCR text alone is not a pass.

## Checks and controls

Every Tesseract read also reads a white blank and a deterministic shuffle of four-pixel horizontal tiles independently within each row. These preserve different properties of the input and can expose a reader returning confident words on nontext. An optional `--control` map is read by the same engine and options. `above_controls` is true only when the image keeps more alphabetic characters than every control. Tests force a control to return the same words as the image and assert that this check fails.

This comparison is a diagnostic, not calibrated evidence of correct transcription: arbitrary noise can sometimes exceed the controls. `status` remains `unverified_model_output` even when `above_controls` is true. The installed-engine regression additionally checks a known printed English line and a blank input; it skips when Tesseract, its English pack or the test font is absent.

Claim label: Model output for the recognized words, boxes and diagnostics. Printed synthetic smokes validate plumbing only.

## Commands and options

| Option | Default | Meaning |
| --- | --- | --- |
| `--tessdata TESSDATA` | none | Local directory of Tesseract language packs |
| `--json` | off | Print capability discovery as JSON |

`python -m kit.reader_backends` prints capabilities. `--json` returns an object; `--tessdata DIR` selects a local pack directory. The Tesseract branch of `python -m kit letterread` is documented with all options on the [letterread page](letterread.md).

Tesseract accepts the shared image, key, crop, explicit bright/dark polarity, rotation, mirror, control image, seed, pixel budget, JSON and output options. Its own options are `--language`, `--tessdata`, `--ocr-psm`, `--ocr-timeout` and `--ocr-min-confidence`. The language defaults to `grc`; choose `lat` explicitly for Latin. Codes joined by `+` select a specific mixed-language model combination, in that order. Aliases `greek`, `ancient-greek`, `latin`, `english` and `hebrew` are normalized before checking the installed packs.

Greek weights, weight profiles, line coordinates, letter-size hints, language-model fusion, confidence floors, custom null counts, deskew settings and glyph exports are not Tesseract options. Supplying an incompatible value fails. In particular, use `--ocr-min-confidence`, not `--p-min`; JSON contains words, so `--csv`, `--page-xml` and `--overlay` are refused until word-aware exporters exist.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `languages(value)` | Ordered list of normalized codes | `ValueError` for empty, duplicate or unsafe codes | No detection or download |
| `validate_route(backend, language)` | Normalized codes | `ValueError` for an unknown backend or non-Greek LineNet request | Check before loading a model |
| `validate_linenet(net)` | The same network | `ValueError` for a non-Greek alphabet | Does not mutate a caller's loaded network |
| `tesseract_info(tessdata=None)` | Executable, version, actual directory and installed codes | `ValueError` for missing or unusable Tesseract | Uses two bounded local subprocesses |
| `capabilities(tessdata=None)` | JSON-compatible backend capabilities | None for missing Tesseract | Missing engine becomes `available: false` |
| `parse_tsv(text, shape, min_confidence=50)` | List of word objects | `ValueError` for malformed output or invalid coordinates/confidence | Raw word confidence stays on a 0 to 100 scale |
| `read_tesseract(image, ...)` | `scrolls-ocr-v1` result | `ValueError`, `OSError`, `ImportError` | Options: language `lat`, tessdata none, psm 3, timeout 60 seconds per invocation, min_confidence 50, polarity dark, seed 0, control none |
| `read(image, *, backend="linenet", language="grc", weights=None, **options)` | The chosen backend's result | `ValueError` for invalid routing; `TypeError` for unsupported options | Greek requires explicit weights in Python; Tesseract refuses LineNet weights |
| `ReaderSession(**selection)` | A reusable reader session | As `switch` | Constructor validates its first selection |
| `ReaderSession.selection` | Detached selection metadata | None | Includes model hashes and any Greek profile, without local paths |
| `ReaderSession.switch(backend="linenet", language="grc", weights=None, weight_profile=None, lines_given=False, tessdata=None)` | New selection metadata | Input/model errors without changing the old selection | Greek loads, checks the alphabet and runs a bounded forward pass; Tesseract initializes on a small blank and records its packs |
| `ReaderSession.read(image, **options)` | Selected reader result plus `selection` | Input/model errors | Refuses changed Tesseract packs until an explicit switch; backend/language/weights are changed only through switch |
| `run_cli(args)` | Exit code 0 | `ValueError`, `OSError`, `ImportError` | Called by the letterread command; its caller reports input errors as exit 2 |
| `main(argv=None)` | Exit code 0 | `SystemExit` for bad syntax | Capability listing only |

```python
from kit import reader_backends
result = reader_backends.read(image, backend="tesseract", language="lat",
                              tessdata="LOCAL_PACKS", psm=7, polarity="dark")
```

For repeated use, keep the same object:

```python
session = reader_backends.ReaderSession(weights="letters-v2-ccby")
greek = session.read(greek_image, letter_px=32)
session.switch(backend="tesseract", language="lat", tessdata="LOCAL_PACKS")
latin = session.read(latin_image, psm=7, polarity="dark")
session.switch(weight_profile="ink-lines", lines_given=True)
```

A missing language pack or incompatible script raises before the new selection is activated. The last working selection remains available. Session selection is explicit: changing the input does not silently change its weights. When choosing a Greek profile, declare whether line positions will be supplied through `lines_given`.

## Inputs

The API takes a finite, nonempty 2D numeric array. It scales its min/max to uint8 and inverts bright ink to dark ink. The source image must fit the CLI's pixel budget; otherwise give a crop. There is no implicit resampling. Controls must have the same shape as the image. Blank images are allowed because their failure is useful.

Model files must exist locally as `CODE.traineddata`. Language codes contain letters, digits and underscores, not paths; `osd` is refused. The explicit `--tessdata` directory chooses a different pack with the same code, and the resulting hash identifies which bytes actually ran.

## Outputs

The Greek adapter adds `backend` to the existing result. Tesseract uses `schema: "scrolls-ocr-v1"`: `backend` (engine version and ordered language codes), `models` (filenames, SHA-256, script where known and licence qualification), normalized `input_sha256`, `input_shape`, `text`, `words`, `controls`, `above_controls`, `options`, `note` and `status`.

Each word has `text`, raw `confidence`, `kept`, `box: [y0,y1,x0,x1]` and Tesseract's block/paragraph/line identifiers. All words remain available; `text` contains only words meeting the confidence floor. The API boxes are in the given array. CLI boxes are mapped back through rotation/mirror and crop into whole-image pixels after EXIF orientation; `options.box_frame` says so. Local folder names are not included in successful results. The normalized input hash covers the exact uint8 pixels sent to OCR; use its recorded shape with that hash.

Exit 0 means the operation completed; it never means a reading is verified. CLI errors exit 2. Files are written only after the read and all controls finish.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `language must name a language code, such as grc, lat or heb`, `language must use recognition language codes; paths and osd are not languages` or `language codes must not repeat` | Input, configuration or engine output failed validation | Choose explicit recognition codes such as `lat` or `grc+lat`; paths and `osd` are refused |
| `unknown reader backend ...; choose linenet or tesseract` or `linenet supports Greek (grc) only; use tesseract with an installed language pack` | Input, configuration or engine output failed validation | Choose a supported backend; Latin requires a suitable local OCR model |
| `LineNet checkpoint alphabet is not Greek; no script relabelling or model substitution is allowed` | Input, configuration or engine output failed validation | The local checkpoint cannot be labelled Greek; select matching weights rather than relabelling the output |
| `LineNet checkpoint alphabet must be a nonempty string` | Input, configuration or engine output failed validation | Malformed checkpoint metadata; use a valid LineNet file |
| `Tesseract is not installed; install tesseract and its language packs explicitly` or `Tesseract could not start; install it and check PATH` | Input, configuration or engine output failed validation | Install it explicitly and check PATH |
| `Tesseract exceeded its` or `Tesseract exited` | Input, configuration or engine output failed validation | A local process timed out or failed; inspect the error and choose a smaller crop or compatible pack |
| `Tesseract did not report its data directory; give --tessdata explicitly` or `Tesseract did not report its version` | Input, configuration or engine output failed validation | The executable did not provide the expected metadata; check installation and `--tessdata` |
| `Tesseract returned malformed TSV`, `Tesseract returned malformed word coordinates or confidence` or `Tesseract returned invalid word coordinates or confidence` | Input, configuration or engine output failed validation | The engine's output cannot be parsed safely; no result is accepted |
| `OCR image must be a nonempty finite 2D numeric array` | Input, configuration or engine output failed validation | Correct input shape/type and non-finite pixels |
| `Tesseract needs explicit bright or dark polarity; auto is a LineNet option` | Input, configuration or engine output failed validation | Choose the polarity; automatic Greek polarity trials are not applied to OCR |
| `OCR psm must be one of 3, 6, 7, 11 or 13` | Input, configuration or engine output failed validation | Use 3, 6, 7, 11 or 13 |
| `OCR timeout must be positive and at most 600 seconds per invocation` | Input, configuration or engine output failed validation | Set a finite timeout from above zero to 600 seconds per invocation |
| `OCR min confidence must be from 0 to 100` or `OCR seed must be a nonnegative integer` | Input, configuration or engine output failed validation | Correct the numeric option |
| `OCR control image must have the same shape as the input` | Input, configuration or engine output failed validation | Supply a control on the same grid |
| `Tesseract language packs not installed:` | Input, configuration or engine output failed validation | Install the named packs explicitly or point `--tessdata` at a directory containing them; no fallback occurs |
| `Tesseract uses local language packs, not LineNet weights; give tessdata instead` | Input, configuration or engine output failed validation | Use `tessdata`, not a Greek `.npz` |
| `the LineNet Python API needs explicit weights` | Input, configuration or engine output failed validation | Give a model name, path or loaded network |
| `Tesseract does not support these LineNet options` | Input, configuration or engine output failed validation | Remove the named options and use the OCR options documented above |
| `OCR max-mpx must be positive and finite`, `OCR output folder does not exist` or `OCR image exceeds max-mpx; give a smaller crop (no implicit resampling)` | Input, configuration or engine output failed validation | Correct the output/budget or choose a smaller crop before reading |


Additional session errors: `LineNet sessions do not use tessdata`, `Tesseract sessions use language packs, not Greek weights or profiles`, `change a ReaderSession model with switch(), not read() options`, `a selected Tesseract pack changed; call switch() to validate the replacement`, and `the selected Tesseract model or engine changed during the read`. Correct the selection explicitly; a failed replacement does not activate it.

Checkpoint initialization errors include `LineNet checkpoint failed its initialization check:`, `invalid band size or letter size`, and `invalid or non-finite logits`. These mean a replacement cannot run even on the bounded blank band and is not activated. `Tesseract could not load every requested language pack:` also fails when Tesseract exits zero but reports a failed language initialization; running only part of a requested language combination is not accepted.

## How it works

The adapter validates the route, enumerates installed language packs through the actual executable, hashes the chosen files, prepares the image and launches Tesseract with argument arrays, never a shell command. It requests TSV using `tessedit_create_tsv=1`, so a pack-only directory does not need a separate `configs/tsv` file. It parses word boxes and raw confidence, reads the two controls with identical OCR settings, and returns provenance. No result selects a backend for the next call. A session replacement is prepared in a separate local state and only assigned after validation succeeds. Tesseract sessions check pack hashes before and after reading; they do not retain an OCR process or claim atomic replacement of external files.

## Cost and time

Local CPU only, no paid service. Each read makes three OCR calls, or four with a supplied control, plus two metadata calls. The timeout is per call, not a total budget. Installed-engine synthetic regression tests complete in about two seconds here. A session switch additionally validates its replacement: one bounded Greek forward pass or a Tesseract blank/control probe. Larger pages and damaged text may take longer and have not been benchmarked.

## For agents

- **Command:** Discover with `python -m kit.reader_backends --json`; run `python -m kit letterread IMAGE --backend tesseract --language lat --polarity dark --json` only when that pack exists.
- **Parse:** Require the expected `schema`, backend, language order and model hashes. Read words and controls separately; word confidence is not glyph confidence.
- **Rerun:** Same image, models, options and seed give the same setup. The requested output file is overwritten; no model is installed or changed.
- **Success:** Exit 0 means completed inference with provenance. Known-answer synthetic text can validate the installation.
- **Not a pass:** A control matching the primary, or an OCR transcript without independent truth. Even `above_controls: true` is not a scroll reading or an accuracy claim.
- **Go-ahead:** No paid inference is involved. Publishing any private input or output still needs the user's clearance.
- **Never:** Relabel Greek checkpoint outputs as Latin, silently pick another pack, translate OCR into an invented transcript, or upload a target map.

## Tests

Run `python -m unittest tests.test_reader_backends -v`. Tests cover script mismatch, invalid/duplicate language codes, missing engines and packs, timeouts, malformed TSV, real model hashes, controls that can fail, incompatible CLI options, cropped/rotated word coordinates, and an installed English OCR smoke when the engine, pack and font exist. Session tests cover Greek to Latin to Greek, incompatible, missing or corrupt replacements retaining the old selection, refusal of partially loaded language combinations even on exit zero, detached provenance snapshots and changed-pack refusal. The separate manual Latin smoke uses the explicitly installed pinned pack. Neither is a held-out scroll benchmark.

## History

- 2026-10-17: working change against `869d621`, explicit per-call local backend selection and validated session switching, capability discovery, Latin/Greek/Hebrew pack discovery, word provenance and negative controls; no new trained model released.

## Related

- [letterread](letterread.md): Greek reader and shared command-line options.
- [Scroll Text Reader guide](../letter-reader.md): released Greek weights, optional local OCR and their measured scope.
