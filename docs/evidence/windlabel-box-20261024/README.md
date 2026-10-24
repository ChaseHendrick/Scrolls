# windlabel-box on fresh PHerc0139 boxes, 24 October 2026

The check behind the first public version of [`kit windlabel-box`](../../tools/windlabel-box.md) and its VC3D plugin. Model output: relative windings grown from the open-data m7 surface prediction (`20250728140407-surface-20260413222639-surface-m7-L0-th0.2`) and lasagna grad_mag (`20260102150214-lasagna-20260419180421-L2`) of PHerc0139, scored against PHerc0139's published hand windings w023 to w040. It is not a reading and says nothing about ink.

- 18 boxes of 512 voxels, 1,000 seeds each, placed from the hand-traced meshes alone before any chain was grown; every height an earlier windlabel run had scored was left out of the judging, with a 10 voxel margin.
- The readout was fixed in a preregistration committed before the run (kept in the project's private workbench): see `readout` in [`summary.json`](summary.json). One run, nothing regrown or rescored.
- Result: PASS. Split chains 0.9758 step accuracy on 13,969 judged steps (lower bound 0.9683 over 40 blocks), 71.2 % of the uncut chains' judged steps kept (those scored 0.9223). Random cut control: median 0.9229, 97.5th percentile 0.9253. Skip control 0.0218, shift control 0.0645. Per box 0.939 to 1.0.
- Limits: one scroll, held out in position only from the windings, m7 and lasagna the split rule was developed on; only 13 to 15 % of steps can be judged; not yet run inside a VC3D build.

[`summary.json`](summary.json) has the pooled numbers and each box's step counts and accuracies; box positions and chain files are not included.
