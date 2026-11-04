# Exposure Atlas instrument checks, version 2: preregistration

Frozen 4 November 2026, after attempt 2 of [version 1](2026-11-04-expatlas-instrument.md) failed its
adjacent-winding control (b), 21 of 30 against a bar of 29, and before any version 2 copy was made or any matrix cell
was computed. Attempt count: this is the third attempt at an instrument check for this tool (attempt 1 was killed for
memory before scoring; attempt 2 is the FAIL above). Version 2 is a new rule, informed by that failure, as version 1
says a change must be.

## What changes, and why

Attempt 2's diagnostic found that the ten PHerc0814 meshes which failed (b) each hold neighboring windings of their
own: a copy moved 100 um along the normal lands on the mesh's own next winding, so (b) there measured the mesh, not
the instrument. Version 2 scores (b) only on **free vertices**: those where the original mesh has no other part of
itself within 160 um along the normal (100 um shift plus the 60 um band), measured by `self_cover` in
`kit/expatlas.py` (another part means more than 4 grid rows or columns away, inside the footprint). A mesh with under
1,000 free vertices is not scored and is reported. Pass for (b): at least 95 % of the scored meshes not exposed, with
at least 25 meshes scored.

Everything else is version 1's rule unchanged: the geometry and every threshold (60 um band, 0.05 and 0.005 shares,
30 and 70 um transform marks), (a) on all vertices, (c), and the same real positive pair in (d). The draw uses a new
seed. The candidate pool is the same 33 meshes, so a draw of 30 shares at least 27 of them with attempt 2's sample;
the copies' jitter directions and ids are new. The code is commit-pinned in the Job that runs it.

## The checks

1. **(a) Recall**: at least 29 of 30 copies called exposed, all vertices.
2. **(b) Adjacent-winding control on free vertices**: as above.
3. **(c) Cross-scroll negative**: 30 of 30 not called exposed.
4. **(d) Real positive pair**: PHerc0814 `20250928235953` and `20250928235954`, both directions called exposed.

Pass: all four. A FAIL is reported as it is and no geometric matrix is published. After a PASS the matrix runs with
version 1's scope and readout (its section "The matrix, after a PASS"), in the same Job.

```json
{
 "seed": 20261105,
 "n": 30,
 "scrolls": ["PHerc0814", "PHerc0009B"],
 "exclude_segments": ["20250928235953", "20250928235954"],
 "deltas_vox": [0, 1, 2, 3],
 "shift_um": 100.0,
 "max_mesh_points": 400000,
 "b_free_um": 160.0,
 "b_min_free_vertices": 1000,
 "positive_pairs": [["20250928235953", "20250928235954"]],
 "bars": {"a_min": 29, "b_min_frac": 0.95, "b_min_scored": 25, "c_min": 30}
}
```

## Results

Not yet run.
