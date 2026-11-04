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

**PASS** (Model output of the instrument, 4 November 2026). Hugging Face Job `6aeaa4410e0338d1bb7f866e` (cpu-upgrade,
50 s running) at commit `7741f8b`, same catalog as attempt 2 (ETag `274f64b9261982444dfd2881f48ae766`). Record:
[`data/expatlas/plant-v2-2026-11-04.json`](../data/expatlas/plant-v2-2026-11-04.json).

| Check | Result | Bar | Verdict |
| --- | --- | --- | --- |
| (a) recall | 30 of 30 exposed; f_same 0.804 to 0.973, median 0.927 | 29 | PASS |
| (b) adjacent-winding control, free vertices | 30 of 30 scored, 30 not exposed; 9 trace (0.005 to 0.037), the rest clear | 95 % of at least 25 | PASS |
| (c) cross-scroll negative | 30 of 30 not exposed; f_same at most 0.010 | 30 | PASS |
| (d) real positive pair | 0.901 and 0.0505, both exposed; the second is a near miss against the 0.05 bar | 2 | PASS |

The nine traces in (b) are the multi-winding PHerc0814 meshes again; free vertices were 54 to 100 % of each mesh.
Read with it: on such meshes the instrument leaves up to 0.037 within 60 um on free vertices even where no sheet was
planted, and on all their vertices, as matrix cells are scored, the same copies give 0.039 to 0.259; so on
multi-winding meshes a cell under about 0.04 is no evidence of exposure and one just over 0.05 is weak
(Interpretation). This PASS is not independent of version 1: the free-vertex rule came from a diagnostic of version
1's failed meshes, and 28 of the 30 source meshes are version 1's. Check (a) sends each copy forward and back through
the same catalog matrix, so it tests the instrument, not the transforms' accuracy; only the fit-RMS jitter stands in
for transform error (PHerc0009B's route has a landmark leave-one-out error of 188.8 um, over the 70 um limit a matrix
cell applies; the plant check does not apply that limit).

The matrix step in the same Job stopped on a technical fault before computing anything: some catalog meshes are
LZW-compressed TIFFs and the image lacked `imagecodecs`. The matrix then ran unchanged, at the same commit with
`imagecodecs` added, in Job `6aeaa4cfc78863f9c6322578` (76 s running, exit 0). After an independent review the
cell logic was corrected so that a list not fully published, or a name with no scroll, reads unknown instead of clear
(`913e932`), and the matrix was rerun locally: the same shares, 8 cells changed from clear to unknown. Matrix:
[`data/expatlas/matrix-2026-11-04.json`](../data/expatlas/matrix-2026-11-04.json), summary in `exposure_atlas_checks`
of [results.json](../results.json) and on the [tool page](../tools/expatlas.md).
