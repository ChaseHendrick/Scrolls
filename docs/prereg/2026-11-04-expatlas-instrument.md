# Exposure Atlas instrument checks: preregistration

Frozen 4 November 2026, before any planted copy was made and before any cell of the matrix was computed. Tool:
`kit/expatlas.py` (`python -m kit expatlas`, [page](../tools/expatlas.md)); the thresholds below are its constants
`D_SAME_UM`, `BAND_UM`, `EXPOSED_FRAC`, `TRACE_FRAC`, `TRANSFORM_FLAG_UM` and `TRANSFORM_LIMIT_UM`, and a change to
either this file or those constants is a new rule with a new preregistration. The geometry builds on dlescanogithub's
proposal in [villa issue 2346](https://github.com/ScrollPrize/villa/issues/2346) (28 Oct 2026).

Disclosed before freezing: two technical smoke runs of `kit expatlas pair` on real meshes, to check the bucket reads
and the frame route: PHerc0814 `20250925212701` against `20250925222237` and against `20260226121302`. None of the
three is an evaluation segment, a planted pair or the positive pair below, and no matrix cell was computed.

## The rule

- One frame per evaluation segment: level-0 voxels of the volume it was traced on. Training meshes come in as the
  catalog's own copy on that volume (`tifxyz-transformed`), else through the catalog's sample-level matrix.
- For each evaluation vertex (at most 150,000 per segment, every k-th row and column): the offset along the normal
  of a training surface at its 8 nearest vertices, kept only where the tangential distance is at most 0.8 grid steps
  of that surface. The smallest kept offset over a model's training meshes counts.
- f_same: share of evaluation vertices with an offset of at most 60 um. Calls: exposed at f_same of 0.05 or more,
  trace from 0.005 to under 0.05, clear under 0.005. f_band (offset at most 100 um) and the z overlap are reported
  beside it and do not change the call.
- Transform uncertainty: each cross-scan training mesh carries the landmark leave-one-out RMS of its catalog route
  (`kit meshaudit` numbers, root sum of squares over the route's steps). Above 30 um the cell is flagged "winding
  uncertain"; above 70 um (half a nominal 140 um winding) a geometric call reads unknown.
- Names first: a segment named in a model's own or inherited training list is "trained" whatever the geometry says.

## The checks, before the matrix

The planted set is drawn with the JSON below (`python -m kit expatlas plant --prereg` reads this block): 30 meshes,
seeded, from the PHerc0814 and PHerc0009B segments that carry a tifxyz mesh and no ink labels, leaving out the
positive pair. Each copy is moved to the scroll's other scan
nearest in voxel size by the catalog matrix, displaced along its normal by 0, 1, 2 or 3 voxels of that scan in
turn, jittered by a random rigid offset as large as that transform's landmark fit RMS, and given a new 14-digit id.
The atlas then has to bring the copy back through the catalog's reverse matrix.

1. **(a) Recall.** Each original against its copy: at least 29 of 30 called exposed.
2. **(b) Adjacent-winding control.** The same copies moved a further 100 um along the normal, below the about
   140 um winding pitch measured on PHerc0139 (about 561 um over four windings,
   [stackcheck log](../logs/2026-10-14-pherc0139-segment-defects.md)), so harder than a true neighbor winding: at least 29 of 30 not called exposed. If 60 um
   cannot separate the two, the instrument fails.
3. **(c) Cross-scroll negative.** Each original against a copy from the other scroll, read in raw voxel coordinates
   as if both were one scan (the scroll guard off): 30 of 30 not called exposed.
4. **(d) Real positive pair**, chosen from the catalog before the run: PHerc0814 `20250928235953`
   (`auto_grown_20250928235953722`, traced on the 9.362 um scan) and `20250928235954`
   (`auto_grown_20250928235953722_copy`, filed on the 2.399 um scan): the same segment in two scans. Both directions
   called exposed.

Pass: all four. A FAIL is reported as it is, here and on the tool page, and no matrix is published until the rule
is changed under a new preregistration.

```json
{
 "seed": 20261104,
 "n": 30,
 "scrolls": ["PHerc0814", "PHerc0009B"],
 "exclude_segments": ["20250928235953", "20250928235954"],
 "deltas_vox": [0, 1, 2, 3],
 "shift_um": 100.0,
 "max_mesh_points": 400000,
 "positive_pairs": [["20250928235953", "20250928235954"]],
 "bars": {"a_min": 29, "b_min": 29, "c_min": 30}
}
```

## The matrix, after a PASS

Scope of this release: the labeled evaluation segments of PHerc0009B, PHerc0500P2, PHerc0814, PHerc0841, PHerc1667
and PHercParis4 in the catalog of 2 November 2026 (20 label sets), against ink_9um, v8in, v8in-1447, d9v2, Reader v2,
Reader V3, ink_canonical_2um, Hecate, TRACE v3B and A-hn as `kit/data/expatlas-models.json` resolves their published
lists. The tool reads meshes and the catalog only, never labels or CT. A cell is model output of this geometry for
the call and Sourced fact or Community report for the list it starts from; "clear" means no covering training
surface was found, not that a model is proven held out. The evaluation segments' overlaps with each other are
reported beside the matrix.

## Results

Not yet run.
