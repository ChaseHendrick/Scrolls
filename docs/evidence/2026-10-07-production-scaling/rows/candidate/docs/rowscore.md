# Row-score resize modes

`kit rowscore` measures text-row periodicity as a triage aid. An ink map is model output, not a reading. Its default dense area resize and historical output fields are unchanged.

For large maps, the opt-in sparse resize avoids dense overlap matrices and zero-valued matrix products:

```bash
python -m kit rowscore forward.tif --reverse reverse.tif --voxel-um 9.366 --fast-resize --json
```

Python callers can use `score_array(array, voxel_um, fast_resize=True)` or `score_files(forward, voxel_um, reverse, fast_resize=True)`. The option requires SciPy. JSON records identify `fast_resize` at file level and each direction's `resize_mode`; the human-readable output also notes the change.

Both modes compute the same output-cell overlaps and float32 coefficients. Sparse multiplication changes their accumulation order. Resized pixels can differ, and even small differences can change a rounded score or the period and angle selected from nearly tied FFT peaks. This option is not an exact-output optimization or a new ink model. Keep the default for strict historical reproduction. No universal error bound or FFT-decision stability is promised. The FFT band, masks, erosion, largest-component selection and peak-selection rule remain the same.

Clipped arrays containing nonfinite values use the original dense path, recorded as `dense_nonfinite_fallback`, to preserve its propagation and error behavior. Do not treat the option as a way to repair invalid inputs.
