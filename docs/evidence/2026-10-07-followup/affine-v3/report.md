# Fresh local affine registration: controlled result

2026-10-07. Actual public labelled-control PHerc0139 CT. No target data, training, reader output or ink labels selected these patches. All rule/code versions and failed algorithm attempts were retained.

The local original-to-phase affine comparison **failed the frozen physical audit**. The phase0-to-phase50 relative mapping passed its independently measured closure checks. Fitted original-to-phase matrices are diagnostic outputs, not approved inputs for the renderer or the primary ink comparison.

| Test | Result |
| --- | --- |
| Algorithm checks | 34/34 pass: zero/integer/fractional shifts, fresh fractional directions, large displaced control, and periodic ambiguity rejection |
| Maximum known-displacement error | 0.05570 voxel; 0.5214 um |
| Minimum control NCC after continuous resampling | 0.99765 |
| Gradient affine calibration | Both rank4, normalized design condition1; all fitted residuals below0.5 voxel |
| Raw-vs-gradient calibration agreement | Four comparisons exceed the fixed0.5 voxel consistency limit |
| Fresh original-to-pag0 physical audits | 5/8 pass; maximum residual0.75410 voxel,7.060 um |
| Fresh original-to-pag50 physical audits | 4/8 pass; maximum residual0.77775 voxel,7.281 um |
| Independent fractional pag0-to-pag50 closure | 8/8 pass; maximum residual0.06770 voxel,0.634 um; NCC at least0.98175 |
| Data and compute | 214 new128^3 chunks,448,790,528bytes;28 reused chunks;1 CPU thread; peakRSS365,002,752bytes |

Calibration used eight nonplanar corners around the source mesh's physical bbox plus17voxel margin. Four fresh interior audit cubes are spatially disjoint from those calibration cubes and from the two earlier translation-pilot source cubes. All eight calibration points were mandatory. No point was dropped, no alternative model was selected after the audits, and neither a failed audit nor the raw-vs-gradient disagreement was used to refit the model.

The independently measured phase0 correspondence q0 defines each direct phase0-to-phase50 template, including its fractional center. The predicted comparison is `A50 @ inverse(A0) @ q0`, with XYZ homogeneous-column conventions. Trilinear CT sampling is explicit; the reference is not sampled only at a fitted prediction. This tests a relative phase-pair mapping even though their absolute mappings to the original volume fail the stricter gate.

The data do not by themselves distinguish nonlinear geometric distortion from reconstruction-dependent structural localization bias. Strong NCC does not prove correct sheet or ink identity. Phase0 and phase50 can be registered to one another more consistently than either can be localized relative to the original recipe. This supports a phase-pair physics study, but does not authorize projecting the original human ink labels through either failed affine as if the writing surfaces were validated.

## Why the subpixel method changed

The first affine version stopped before new CT acquisition: integer-grid quadratic refinement failed injected fractional-shift controls. A high integer-grid NCC is not the NCC at a true fractional displacement. On anisotropic real CT, the integer-grid maximum can also lie outside the closest half-voxel cell around a known shift. Thus the earlier translation pilot's +1/-1 integer peaks and18.724um difference are a failure of that frozen coarse estimator's gate; they should not be promoted to a precise physical warp magnitude.

The append-only V3 method uses a coarse integer FFT peak followed by bounded continuous NCC, resampling the raw CT at each trial and recomputing Gaussian/gradient features afterwards. Both features use explicit raw halos. A negative-definite continuous Hessian, convergence, interior/support checks and competing-peak margin remain required. Displacement accuracy was calibrated on old actual-CT controls, then tested on additional unseen fractional directions and a large offset before collecting fresh physical correspondences. The physical0.5voxel Euclidean gate was unchanged.

V2, its failure result and source remain in the parent `affine-followup/` directory. V3's initial optimizer evaluation-cap failure and the320-evaluation recheck are retained separately. No old frozen file was overwritten.

## Reproduce and inspect

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 /workspace/Scrolls/.venv/bin/python /workspace/scrolls-env/phase-reconstruction/affine-followup/v3/fit_local_affine_v3.py
```

The executable refuses changed frozen script/dependency hashes. Existing cache is reused; a reproduction remains local and cannot turn `all_pass=false` into a passing geometry approval without a new experiment.

Key artifacts: `rule_v3.json`, `v3-amendment.json`, `fit_local_affine_v3.py`, `algorithm-controls.json`, `correspondences.json`, `input-receipt.json`, `result.json`, `reference-sha256.json`. The original-to-phase matrices live under `result.fits[name].matrix_original_xyz_to_phase_xyz`; the adapter must also require `result.all_pass=true`, which is false here.

Rule SHA256: `b3ae4daddd7653322b1b4c407b1d766c102fa59b9675f4b000e0da175585bc5e`.

Script SHA256: `f22e8c3abc6b3e6b6044f61e3548cd1a20ac852322d33f45f3d48962dc5a90f4`.

The final manifest covers rules, code, all retained control evidence, input receipts, correspondences, results and this report. Raw chunk identities are pinned in the input receipt; prior geometry and metadata references are pinned separately. Final verification checks both the files and the actual cached chunk bytes.
