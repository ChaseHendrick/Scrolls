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

## Amendment before attempt 2 (4 November 2026)

Attempt 1 (rule frozen in commit `0ec8999`) planted all 30 copies and was then killed by the container's
out-of-memory guard (exit 137) before any check was scored; nothing was read from it but the planting log. A
technical break, so the same rule and seed run again as attempt 2 (standing decision of 29 Oct 2026 on reruns
after a technical break). One technical change, no threshold or bar changed: every mesh is now read in single
precision and thinned as it is read, every k-th row and column with k the smallest that leaves at most 400,000
vertices that are not holes (`MAX_MESH_POINTS`; the planted copies were already capped at that count by
`max_mesh_points` above). Before it, a 5-million-vertex catalog mesh was held whole while its normals and search
tree were built.

## Results

**Attempt 2: FAIL** (Model output of the instrument, 4 November 2026). Hugging Face Job `6aeaa27a0e0338d1bb7f85ec`
(cpu-upgrade, 47 s running, image `python:3.13` with numpy 2.5.3, scipy 1.18.1, tifffile 2026.10.15) at commit
`34c3683`, catalog `metadata.json` Last-Modified 2 Nov 2026 11:32:29 GMT, ETag `274f64b9261982444dfd2881f48ae766`.
33 candidates, 30 drawn (15 PHerc0009B, 15 PHerc0814). As the rule says, the matrix was not computed.

| Check | Result | Bar | Verdict |
| --- | --- | --- | --- |
| (a) recall | 30 of 30 exposed; f_same 0.804 to 0.973, median 0.927 | 29 | PASS |
| (b) adjacent-winding control | 21 of 30 not exposed (9 exposed, 1 trace); f_same up to 0.250 | 29 | **FAIL** |
| (c) cross-scroll negative | 30 of 30 not exposed; f_same at most 0.009 | 30 | PASS |
| (d) real positive pair | both directions exposed: `20250928235954` on `20250928235953` 0.901, the other way 0.0505 against the 0.05 bar, a near miss (the copy covers about a ninth of the larger mesh) | 2 | PASS |

All nine exposed copies in (b), and the one trace, are the ten large auto-grown PHerc0814 meshes traced on the
9.362 um scan; every PHerc0009B copy and every PHerc0814 2.399 um copy passed. A diagnostic run after the result
(not part of the rule; Interpretation) measured, for each original, how much of it has another part of the same mesh
nearby along the normal (`self_cover`, more than 4 grid rows or columns away): on those ten meshes 7 to 45 % of the
vertices have another part of the mesh 60 to 160 um away (median nearest other part 144 to 227 um) and 0.6 to 11 %
within 60 um; on every one of the twenty that passed, under 1 % in all. So the meshes that failed span neighboring
windings of a tight roll, and a copy moved 100 um lands on the mesh's own next winding: the control was built wrong
for such meshes, while the 60 um band itself held where the shifted copy had no sheet to land on. The fix and its
rerun are a new rule with its own preregistration: [`2026-11-04-expatlas-instrument-v2.md`](2026-11-04-expatlas-instrument-v2.md).
