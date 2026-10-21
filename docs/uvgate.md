# UV overlap gate

`python -m kit uvgate PATH --source-area AREA` checks that a flattened sheet's UV triangles do not overlap, that they cover enough of the source area and, with `--mesh`, that they form one counterclockwise piece. It uses a NumPy spatial index automatically when NumPy is installed; the verdict fields, exact overlap threshold and exit codes are the same as those of the standard-library exact implementation, which remains the fallback when NumPy is unavailable. A verdict is a geometry check of the supplied coordinates, never evidence about ink or a reading.

For Python callers:

```python
from kit.uvgate import uv_overlap_gate

verdict = uv_overlap_gate(triangles)
# Diagnostics for small fixtures; all hit pairs, sorted by original face index.
checked = uv_overlap_gate(triangles, method="grid", collect_pairs=True)
# Original all-pairs oracle. Use only on small inputs.
reference = uv_overlap_gate(triangles, method="reference", collect_pairs=True)
```

The fast path indexes triangle bounding boxes into a uniform grid with a power-of-two cell size. Only faces sharing a cell can become candidates. Each pair belongs to its first shared cell, so a face spanning several cells cannot multiply the hit count. Vectorized bounding-box and conservative orientation predicates discard proven disjoint interiors. Uncertain candidates still use the original exact Fraction clipping and area comparison. The witness remains the first overlapping pair in input-index order.

This reduces typical candidate work to near-linear scaling for similarly sized triangles with bounded cell occupancy. Dense overlap and extreme size variation can still require quadratic work. Exact coordinates that cannot be converted safely, negative thresholds, and unsafe grid ranges use the reference implementation. NumPy integer coordinates become Python integers before exact clipping so Fraction arithmetic cannot overflow fixed-width scalars.

The overlap gate does not measure tears, coverage or winding constraints by itself. Existing `--mesh` and coverage checks keep their separate rules. Relative winding constraints are checked by [`windconsistency`](windconsistency.md).

For a reproducible run on actual flattened OBJ texture coordinates, download a released flattened OBJ from the open-data bucket into any scratch folder `WORK`, for example PHerc0139 w039's `flatten-segment` output (36.9 MB):

```bash
mkdir -p WORK
curl -o WORK/w039_flattened.obj https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/segments/20260302000000-w039_2026030210/mesh/intermediate/20260302000000-w039_2026030210_flattened.obj
python scripts/bench_uvgate.py \
  --obj-uv WORK/w039_flattened.obj \
  --triangles all --method grid --collect-pairs \
  --output WORK/w039-full.json
```

`--obj-uv` reads the texture index of each face corner. It preserves face order, UV seams, degenerate faces and original units. It does not use vertex XY, normalize UV values, open materials or load images. Nontriangular faces, missing texture indices and nonfinite UVs are refused. Every face is validated before selecting a subset. `--triangles 800 --selection random --seed 17` selects a reproducible sample in original face order; repeat it with `--method reference` to compare the entire verdict and overlapping-pair list. Receipts include source, triangle-array and selected-face hashes. `abs_eps` defaults to 1e-12 in squared source UV units.

`python -m kit uvgate` itself reads only a JSON list of triangles or a CSV; the benchmark script is the OBJ route, and it runs the overlap check alone. Each benchmark command starts a fresh worker and records source hashes, face counts, gate time, process time and whole-worker peak RSS. The default whole-worker timeout is 300 seconds; use `--timeout-seconds` to change it. Reference runs are restricted to at most 2,000 faces. See the [measured log](logs/2026-10-13-uvgate-fast.md) for the released-OBJ and synthetic results and their limits, and the [tool page](tools/uvgate.md) for every option, output field and failure.
