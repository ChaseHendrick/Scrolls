# volumeview: create a volume overlay viewer link locally

Turn explicitly declared public CT and prediction grids into a Neuroglancer state or link, checking their axes, physical extents and coordinate frame without accessing scan data.

| Field | Value |
| --- | --- |
| Id | `volumeview` |
| Status | Current |
| Kind | kit command, kit module, kit entry point |
| Area | Viewers and apps |
| Run | `python -m kit volumeview`, `python -m kit.volumeview`, `from kit import volumeview` |
| Code | `kit/volumeview.py`, `kit/data/volumeview-example.json`, `kit/cli.py` (`cmd_volumeview`) |
| Tests | `tests/test_volumeview.py` |
| Needs | Python 3.10 or newer; standard library only; an explicit local JSON manifest |
| Runs on | Any CPU; no numerical arrays or GPU required. Synthetic test timing is under Cost and time |
| Network | None. Manually opening the resulting link later loads the external viewer and lets it request the declared public sources |
| Writes | Stdout by default; `--out` creates one new local text file and refuses existing files |
| Go-ahead | Not needed for local generation; sharing a link is a separate publication action |
| Released | Added for the next public workbench release; not a separate model or dataset release |
| Checked | 2026-10-17 against commit `67ced6a` |

## What it does

CT volumes and derived predictions can use different voxel sizes. Giving them identical viewer scales makes a downsampled prediction appear too small. This helper creates a Neuroglancer state that gives each explicitly described grid its own physical spacing on a shared micrometer grid.

The supported case is deliberately narrow: public open-data OME-Zarr roots whose source grid is dimensionless, starts at zero and has ZYX axes. One CT layer is required; one prediction layer is optional. An overlay requires the same declared frame and physical extent. The manifest supplies every value; the helper never guesses a missing scale from a URL or catalog row.

This checks the consistency of supplied metadata. It does not inspect the remote OME metadata, prove registration, download arrays, infer ink or open a browser. A viewer overlay is a visualization, and an ink prediction is model output, not a reading. The example URLs are fictional paths for an offline software demonstration.

## When to use it

Use it to prepare a reproducible inspection link when you already have authoritative grid metadata for public open-data sources. A saved receipt records the exact input file digest and generated state.

For beginners, the [official Data Browser](https://scrollprize.org/data_browser) already provides volume viewers. Use that when you do not know the source grid. For translated, rotated, cropped, differently framed or already physically scaled sources, use a viewer workflow that understands the actual transforms; this helper refuses those cases. The public scan catalog alone lacks the prediction shapes needed here.

## Quick start

Run the bundled synthetic manifest from a checkout. It creates no array data and contacts no server:

```bash
python -m kit volumeview kit/data/volumeview-example.json --format receipt --out volumeview-receipt.json
python -c 'import json; r=json.load(open("volumeview-receipt.json")); print(len(r["state"]["layers"])); print(r["validation"])'
```

Observed on 2026-10-17:

```text
2
supplied metadata only; remote sources not verified
```

The example is a CT of shape `[40, 60, 80]` at `[2, 3, 4]` micrometers per ZYX voxel and a prediction with half each dimension at twice each spacing. Both describe the same physical box. Do not open the example link expecting a real scan. For a real manifest, replace the fictional paths and all geometry fields with known source metadata. Use `--out NEW_FILE` instead of shell redirection to refuse overwriting an existing file.

## Checks and controls

`python -m unittest tests.test_volumeview -v` checks an anisotropic, non-cubic CT/prediction pair, physical point agreement, XYZ viewer dimension ordering, and state/link roundtrip. Negative controls refuse mismatched frame, extents, axis order, source scale/units, non-finite spacing, missing fields and unapproved URLs. CLI checks refuse input/output aliases and existing output files, and produce no output file for malformed input.

These are software checks using synthetic metadata. No actual remote array was read or browser rendering asserted. Independent review also compared the generated state with the pinned official helper for a 2.4 micrometer CT and a level-2, 9.6 micrometer prediction.

Claim label: None (this tool checks declared metadata and generates visualization state, with no scientific-quality claim).

## Commands and options

### `python -m kit volumeview`

```
usage: python -m kit volumeview [-h] [--format {url,state,receipt}]
                                [--out OUT]
                                manifest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `manifest` | required | Local JSON containing explicitly declared grid metadata |
| `--format FORMAT` | `url` | `url`: viewer URL; `state`: plain Neuroglancer JSON; `receipt`: state, URL and input digest |
| `--out OUT` | none | New local file instead of stdout; parent folder must exist; never overwrites |

### `python -m kit.volumeview`

```
usage: volumeview.py [-h] [--format {url,state,receipt}] [--out OUT] manifest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `manifest` | required | Same local manifest as the workbench command |
| `--format FORMAT` | `url` | Same `url`, `state` or `receipt` selection |
| `--out OUT` | none | Same exclusive local output creation |

Both entry points provide `-h, --help`. Neither reads tool-specific environment variables.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `VolumeViewError()` | Exception instance | None | A `ValueError` subtype for unsupported or inconsistent metadata |
| `build_state(manifest)` | JSON-compatible dict | `VolumeViewError` | Pure local validation and state generation; does not mutate input |
| `viewer_link(manifest)` | String | `VolumeViewError` | Validates and percent-encodes a state under the fixed viewer host |
| `add_arguments(parser)` | None | argparse errors | Registers common CLI options |
| `run(args)` | Integer, 0 or 2 | None for ordinary input/file errors | Reads one bounded local file; prints or exclusively creates output |
| `main(argv=None)` | Integer, 0 or 2 | `SystemExit` for help/argument parsing | Standalone CLI entry point |

## Inputs

The manifest must be a JSON object with exactly `schema` and `layers`. `schema` is integer 1; `layers` is one or two objects. The CLI reads at most `MAX_MANIFEST_BYTES = 1048576` bytes plus one byte to detect oversize input. Duplicate keys, NaN and Infinity are rejected.

Each layer has exactly these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Distinct layer label, 1 to 120 characters, no control characters or surrounding whitespace |
| `role` | string | First layer `ct`; optional second layer `prediction` |
| `source` | string | Public OME-Zarr root URL, at most 4096 characters, ending in `.zarr` with optional trailing slash |
| `frame` | string | Explicit coordinate-frame identifier, same text constraints as name; must match between layers |
| `shape_zyx` | three integers | Positive source level-0 dimensions in ZYX order, each at most 1e12 |
| `voxel_size_um_zyx` | three numbers | Positive finite physical spacing in micrometers, ZYX order, each at most 1e12 |
| `origin_um_zyx` | three numbers | Must be exactly `[0, 0, 0]`; translated grids are unsupported |
| `source_grid` | object | Exactly `axes: ["z", "y", "x"]`, `scale: [1, 1, 1]`, `units: ["", "", ""]`, `origin: [0, 0, 0]` |

`source_grid` declares the effective level-0 coordinates the OME-Zarr reader will expose, including any multiscale and dataset coordinate transformations. Populate it from actual metadata, not from the example. Source grids already expressed in physical units or with non-unit scale are refused to prevent applying the voxel size twice. No affine, channel or time dimension is supported.

Allowed URLs are `s3://vesuvius-challenge-open-data/PATH.zarr`, or HTTPS at `vesuvius-challenge-open-data.s3.amazonaws.com` or `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`. No credentials, port, query, fragment, percent escapes, whitespace, traversal or array-level `/0` suffix is accepted. Path components use ASCII letters, digits, dot, underscore and hyphen. Legacy buckets and arbitrary hosts are unsupported. Validation does not establish that a path exists.

## Outputs

`url` prints one percent-encoded URL beginning with `https://neuroglancer-demo.appspot.com/#!`. `state` prints the viewer state. `receipt` prints the following fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | integer | Receipt schema 1 |
| `manifest_sha256` | string | SHA-256 of the exact input bytes, not a digest of remote data |
| `validation` | string | `supplied metadata only; remote sources not verified` |
| `state` | object | Neuroglancer state described below |
| `url` | string | Encoded state at the fixed external viewer host |

The state contains `dimensions` in XYZ order, each `[1e-6, "m"]`, `layout: "4panel"`, and `layers`. Each layer has `type: "image"`, `name`, `shader`, and `source`. The source contains a direct `zarr2://https://...` URL and `transform.inputDimensions`/`outputDimensions`, both XYZ ordered. Input dimensions use that layer's physical voxel spacing in meters; output dimensions use the shared micrometer grid. The prediction adds `blend: "additive"`. The viewer state includes source URLs, layer names and physical spacing; frame identifiers and shapes remain in the input manifest. Keep names suitable for sharing.

`--out` creates a new UTF-8 file with a trailing newline. It never opens a viewer or transfers the manifest. Manually opening a real link later uses Neuroglancer, an external service, and requests its declared public Zarr sources.

| Exit code | Meaning |
| --- | --- |
| `0` | Supported, internally consistent metadata produced output; remote registration is unverified |
| `2` | Invalid metadata/arguments, unreadable input, or output creation failure |

## Failure modes

Messages from the command are prefixed `volumeview:`. Variable field names and JSON parser/OS details follow the relevant fixed fragment below.

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` | Missing or invalid CLI argument | Follow Commands and options |
| `JSON: non-finite number` or `JSON: duplicate key` | Ambiguous or nonstandard JSON | Supply one finite value per field |
| `: expected exactly` | Missing or extra object fields | Match the Inputs schema |
| `: expected nonempty text of at most 120 characters without controls` | Invalid name or frame | Supply short explicit text |
| `: expected three positive finite numbers in ZYX order` or `: expected positive` | Wrong vector length, type or bounds | Supply three positive numbers; shapes must be integers |
| `source: expected a public Vesuvius OME-Zarr root URL` or `source: invalid URL` | Invalid URL text | Use a supported public root |
| `source: credentials, ports, queries and fragments are not supported` | URL includes unsupported components | Use the ordinary public source URL |
| `source: expected a .zarr root path without escapes or traversal` | Invalid root path | Supply a direct `.zarr` group path |
| `source: only the public vesuvius-challenge-open-data bucket is supported` | Different bucket or host | Use the official Data Browser for other sources |
| `schema: expected 1` | Unsupported manifest version | Use schema 1 |
| `layers: expected CT alone or CT followed by one prediction` | Wrong layer count | Supply one or two supported layers |
| `name: layers must have distinct names` | Duplicate labels | Name each layer distinctly |
| `role: expected CT first, then prediction` | Wrong roles/order | Put CT first and prediction second |
| `source_grid.axes: only exactly [z, y, x] is supported` | Unsupported axes/order | Use a workflow for the actual source axes |
| `source_grid: only dimensionless unit scale and zero origin are supported` | Source already scaled or translated | Use a workflow supporting its real transform |
| `source_grid: physical source units are not supported; do not apply spacing twice` | Already physical source coordinates | Do not falsify the metadata to bypass the check |
| `origin_um_zyx: only an explicit zero origin is supported` | Translated grid or missing origin | Use a workflow supporting the actual origin |
| `grid: spacing or physical extent cannot be represented finitely` | Underflow/overflow | Check units and numeric values |
| `overlay: frame and physical extents must match the CT exactly` | Incompatible frame or field of view | Obtain compatible metadata; do not guess registration |
| `output: must not replace the input manifest` | Output aliases the input | Choose a new file |
| `manifest: exceeds the 1 MiB limit` | Input too large | Supply only this small metadata schema |
| OS/JSON error after `volumeview:` | Unreadable file, malformed JSON, existing output or unwritable destination | Correct the reported local file problem; existing outputs are preserved |

## How it works

Validate every field and convert allowed S3 URLs to direct public HTTPS, avoiding the old proxy. Convert each supplied ZYX voxel size from micrometers to meters with a factor of `1e-6`, then assign it to named XYZ viewer dimensions. Both transform dimension objects use the same XYZ order; Neuroglancer pairs their entries by position. Every output dimension uses `1e-6` meters. The dimensionless source-grid restriction prevents double scaling.

For an overlay, compare frame strings and each `shape * spacing` physical extent. Extents must agree with relative tolerance `1e-10` and zero absolute tolerance; no registration is inferred. Serialize the state as JSON with non-finite values forbidden, then percent-encode it beneath the fixed `VIEWER` host. Receipts hash the original manifest bytes.

Sourced fact, checked 2026-10-17: the state/shader convention and direct-bucket approach follow the [official website helper at villa 1db9cd9](https://github.com/ScrollPrize/villa/blob/1db9cd94487c2fb5e759cc4ee72018dcb7359984/scrollprize.org/src/components/atlas/dataAccess.js). This is an independent implementation; the source's MIT notice is retained in [NOTICE](../../NOTICE). The website code license does not change scan or model licenses.

## Cost and time

No paid compute or network is used. Ten synthetic tests took 0.036 seconds on the cloud CPU on 2026-10-17, measured by unittest; the local test wrapper recorded 0.2 seconds wall time. Peak memory was not measured; no scan arrays are allocated and the manifest byte read is capped. Opening a real viewer link later has separate network and browser costs.

## For agents

- **Command:** `python -m kit volumeview MANIFEST.json --format receipt --out NEW_RECEIPT.json`.
- **Parse:** `manifest_sha256`, `validation`, `state` and `url`; never treat the digest as a remote-data hash.
- **Rerun:** Safe to stdout; `--out` refuses existing paths, including links to input files.
- **Success:** Exit 0 means supported, consistent declared metadata only.
- **Not a pass:** A valid URL does not prove source availability, alignment, model quality or legible text.
- **Go-ahead:** Nothing for local generation; sharing output is a separate publication decision under the go-ahead rule (hard rule 8).
- **Never:** Guess missing transforms, change source-unit declarations to bypass checks, or call a prediction a reading.

## Tests

```bash
python -m unittest tests.test_volumeview -v
```

Tests cover anisotropic downsampling, dimension order, physical point consistency, roundtrip, schema/URL/axis/units/extent refusals, non-finite and tiny values, no socket/browser access, input digests and exclusive local output. They do not verify real Zarr contents or launch a browser.

## History

- 2026-10-17: Added local viewer state/link generation with explicit grid validation and synthetic controls (working tree on `67ced6a`).

## Related

- [Start Here](../start-here.md): choose an appropriate first task.
- [Official Data Browser](https://scrollprize.org/data_browser): explore official sources without writing a manifest.
- [Official data formats](https://scrollprize.org/data): formats, licenses and citation guidance.
- [Viewer](view.md): local two-dimensional ink-map overlays.
