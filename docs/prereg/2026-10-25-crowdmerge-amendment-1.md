# Amendment 1 to the crowd-trace merger preregistration: settings frozen for the report split (25 October 2026)

Amends [the preregistration of 24 October](2026-10-24-crowdmerge.md). Written and committed before the report split (sites with A in w032 to w040) has been run. The bench design, the split and the bars are unchanged.

## Frozen

- Code: `kit/crowdmerge.py` as committed in `f9a30ee` (sha256 `7ae11e51952aa39c266563ace97a8e46c077559ced8b68e706764858da9ad094`), with its `SETTINGS`: canvas 5 voxels, traces densified to 2 voxels, ray -40 to +40 voxels, tolerance 2 voxels, 1 spread bin, 9-cell tie-break box, slip 4 voxels, 8 voxels sideways, flag reach 64 voxels, growth up to 100 rings at 3 rings per vote, 2 passes with reliability weights, 0.6 weight share beyond the consensus, at least 2 traces agreeing.
- Command: `python -m kit crowdmerge bench --split report --out work/crowdmerge/report`, run once.

## Development record (dev split, 36 sites, 24 to 25 October)

| Round | Change | Off sheet (vote / largest / mean) | Flag recall | Flag precision | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | first version (smoothed vote, ray 24) | 0.0595 / 0.2629 / 0.2189 | 0.7454 | 0.8952 | FAIL |
| 2 | per-vertex count decides, box breaks ties; ray 40; tangent-plane refinement | 0.0477 / 0.2629 / 0.2567 | 0.8520 | 0.9378 | FAIL |
| 3 | growth past the base | 0.0479 / 0.2629 / 0.2564 | 0.8572 | 0.9377 | FAIL |
| 4 | at least 2 traces and a strict majority per vertex | 0.0282 / 0.2629 / 0.2604 | 0.8380 | 0.9588 | FAIL |
| 5 | second pass along the result's normals | 0.0266 / 0.2629 / 0.2604 | 0.8426 | 0.9595 | FAIL |
| 6 | vertices beyond the consensus judged by the traces on their own normal | 0.0266 / 0.2629 / 0.2604 | 0.8553 | 0.9576 | FAIL |
| 7 | second pass weighs each trace by its agreement with the first | 0.0132 / 0.2629 / 0.2604 | 0.8838 | 0.9802 | FAIL (recall) |
| 8 | the beyond judgment uses the same weights | 0.0132 / 0.2629 / 0.2604 | 0.9391 | 0.9888 | PASS |

In every round the clean control stayed at 0 off sheet and at most 0.0001 false flags, and the sham control followed the wrong majority (vote off sheet 0.42 to 0.43 against 0.47 of the majority's points slipped). Eight rounds on one split make the dev numbers optimistic; the report split decides.
