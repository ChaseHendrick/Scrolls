# PR #1996 support masks and certified geometry

7 October 2026. Local real-mesh stress test for Chase Hendrick's Scrolls workbench. Public PHerc0841 geometry only. No target data, CT downloads, labels, reader maps, GPU, flattening jobs or external posts.

**Recommendation:** evaluate the support mask as an optional coverage/performance choice while retaining independent geometry and reader gates. Supported working-grid occupancy is useful, but it does not establish locally regular geometry, faithful interpolation, matching sheet identity or usable ink-map coverage. Do not relax the 50 um correspondence limit to recover the extra mask area.

## Source and experiment scope

The experiment used the actual `resample_grid`, `support_coarse_mask` and `finalize_coarse_grid` functions from public [villa PR #1996](https://github.com/ScrollPrize/villa/pull/1996), pinned head `d651f04d2f5c73fc5ba46c5f859392391cc59b43`. The source is retained at `/workspace/scrolls-env/pr1996-review/grow_track_graph.py`. The separate full PR/public-study review is `/workspace/scrolls-env/pr1996-review/report.md`.

Current cached public PHerc0841 w00 and ag896 native meshes have scale 0.05, approximately 20-voxel native spacing. They were treated as working grids and coarsened by factors 2 and 4. This tests mask and geometry behavior at approximately 40/80-voxel output spacing. It is **not** a reproduction of Paris4 working spacing 5/output spacing 10, upstream track-graph growth, the reported physical-area percentages or flattening CPU timings. Previous cleaning/growth was not rerun.

The frozen main rule SHA-256 is `8d6fc3431201282c959b83e6437750002ba999c4ed1ca2a52d2bfd513cc01646`. It binds the exact PR helper, local geometry implementation, experiment code and input mesh files. Both full meshes and both mask modes were specified before measurements. These are geometry-selected tests, with no ink or model-based choice.

## Real-mesh mask and interpolation measurements

Coverage below counts original valid working-grid **UV cells**, not cm2 or readable text. Same-UV errors compare the actual coarse bilinear surface position with the original working vertex at the same parameter location. They are not closest-surface gaps, normal errors or flattening distortion.

| Mesh | Coarsening | Mask | Valid working-cell coverage | Retained quads | Quads failing local Jacobian certificate | Same-UV error p99, um |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| w00 | 2 | erosion | 95.15% | 8,644 | 13 | 66.90 |
| w00 | 2 | support | 98.70% | 8,966 | 18 | 68.63 |
| ag896 | 2 | erosion | 94.99% | 8,670 | 19 | 71.90 |
| ag896 | 2 | support | 98.63% | 9,002 | 27 | 73.13 |
| w00 | 4 | erosion | 89.43% | 2,031 | 0 | 172.93 |
| w00 | 4 | support | 96.21% | 2,185 | 0 | 174.70 |
| ag896 | 4 | erosion | 89.01% | 2,031 | 0 | 184.41 |
| ag896 | 4 | support | 95.98% | 2,190 | 1 | 184.53 |

Every retained support-mode quad had all required original working-grid vertices under its footprint. The support invariant passed in every measured real condition. The Jacobian test independently requires all four corner normals to lie in a common positive hemisphere, certifying no zero Jacobian or local orientation reversal throughout the bilinear quad. Failing that sufficient test does not by itself prove every failed quad actually contains a fold.

The result shows useful recovered occupancy and a separate geometry-quality problem. Large same-UV discrepancies occur under both modes, chiefly because coarsening changes the surface interpolation. The mask merely retains or removes vertices of that already resampled surface; it does not optimize its geometry.

## Controls that can fail

An all-valid 17-by-17 planar working grid coarsened by 4 retained 16 quads with support and 4 with blanket erosion, with exact interpolation geometry.

A missing working vertex at `(6,6)` inside a coarse footprint left one unsupported quad under the erosion-only finalizer, while support mode retained no unsupported quads. This isolated helper test intentionally supplies the working validity directly; it does not establish that an end-to-end growth run with preceding fine-grid cleaning would retain the same unsupported quad. It demonstrates why final coarse occupancy alone cannot certify an interior footprint.

The support helper uses two-triangle areas to rank which corner to remove. This ranking does not validate bilinear Jacobians, distortion or sheet identity. The greedy routine also need not maximize globally retained area; its invariant, rather than optimality, is the established property here.

## Actual unchanged 50 um correspondence check

Because same-UV error is not nearest-surface distance, a separately frozen supplementary test ran the production certified bilinear correspondence on 48 uniformly spaced valid native vertices from each mesh. The selection is the fixed lexicographic valid-index sequence at `floor(i*(L-1)/47)`, for `i=0..47`, without selecting by errors, labels or reader output. Supplement rule SHA-256: `a306b4aaff6181bb2165876dd18c3ee5b7cfa3533b3a2a87e8ae39066399ab9c`.

It retains the 50 um physical upper-distance limit, source coordinate roundoff tolerance, complete radius search, hole/local-fold handling, strict-convexity certificate and ambiguity/budget abstention. No maps were supplied, so these are geometry-eligible points, not accepted corrections or usable inference coverage.

| Mesh | Coarsening | Erosion eligible / 48 | Support eligible / 48 | Ambiguous in either mode | Unresolved in either mode |
| --- | ---: | ---: | ---: | ---: | ---: |
| w00 | 2 | 32 | 33 | 9 | 2 |
| ag896 | 2 | 32 | 34 | 9 | 1 |
| w00 | 4 | 37 | 40 | 2 | 0 |
| ag896 | 4 | 27 | 29 | 3 | 0 |

Support modestly increases geometric availability in this small deterministic sample. The ambiguity and unresolved counts do not improve. Thus roughly 98% occupied working-cell coverage is not equivalent to roughly 98% certified correspondence coverage. These sparse sample counts are not a statistical estimate of full-area performance or a ranking of coarsening factors. The finer/coarser cases have different boundary and ambiguity effects.

## Interaction with rendering and Scrolls safeguards

- A working-support mask says that a coarse footprint did not bridge a hole. Actual bilinear positions can still deviate from the working geometry, and local regularity requires an additional certificate. All-four-corner support is preserved by the Scrolls correspondence path, along with its independent Jacobian test.
- The continuous correspondence uses the actual retained bilinear quads. A renderer using bicubic/smooth positions would need a different geometry model; the current schema explicitly requires linear positions.
- Projection UV remains fixed from baseline geometry before map inspection. The mask must not be tuned on candidate maps, labels or which correction produces the most occupied regions.
- A retained geometric point also needs conservative dense map coverage, full-render frame metadata and matched forward/reverse/shuffle controls. Missing pixels, ambiguous geometry or unsupported displaced controls still abstain.
- The published efficiency tradeoff concerns mesh production/flattening. These scripts measured neither flattening CPU nor reader improvements. Any adoption should compare the default and support branches on the same working grid, report common versus added regions separately, then rerender through the official pipeline and audit distortion, geometry, control maps and held-out labels.

The experiment offers a concrete reason to try the optional support mode and an equally concrete reason to retain the geometry gate. It establishes no new ink finding or worldwide method novelty.

## Resources and artifacts

The whole-mesh mask/interpolation test took 3.14 seconds, peaked at 70,533,120 bytes RSS and used one CPU thread. The supplementary correspondence check took 9.11 seconds, peaked at 72,138,752 bytes RSS and also used one CPU thread. Both made zero network requests.

Main code: `/workspace/scrolls-env/continuous-correspondence-review/pr1996_mask_geometry.py`. Main rule/results: `rule.json`, `result.json`. Supplementary code/rule/results: `correspondence_audit.py`, `correspondence-rule.json`, `correspondence-result.json`. `sha256-manifest.txt` binds the code, rules, measurements, input meshes, upstream helper, reviewed geometry implementation and this report; verification output is stored alongside it.
