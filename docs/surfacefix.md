# Experimental automatic region flags and surface correction

`kit surfacefix` chooses bounded normal offsets using model output from two traces of one sheet. It writes a corrected surface copy and flags uncertain regions. It never changes the source mesh. Its first version is an experimental consistency check, not proof that a surface follows ink or that a map is legible.

villa already has snapping and geometry optimization in Lasagna. This tool is a small selection and checking layer over outputs from the existing pipeline. The [community needs review](logs/2026-10-07-community-needs.md) records the existing implementations and real-data evidence required for an upstream contribution.

## Inputs and workflow

Use two traces in the same CT coordinate system. Keep all generated surfaces, maps and region reports in local ignored `work/` or `experiments/` paths. Preregister the selection rule and thresholds before target inference. The existing public PHerc0841 result motivates this experiment ([log](logs/2026-10-07-overlap-and-baseline.md)); it does not validate the correction algorithm.

From the repository root with the map dependencies installed:

```bash
python -m kit surfacefix prepare SOURCE.tifxyz work/surfacefix-candidates \
  --voxel-um 9.366 --offsets -1 1 --max-shift-um 50
```

This produces offset meshes and a manifest template. Use villa to render each mesh and the existing reader to produce its forward, reversed-depth and depth-shuffled maps. Prepare the same maps for the source and reference trace. This tool does not install or run an ink model. Map inputs must cover their full surface, not an unregistered crop.

Fill `manifest.json` with the reference mesh, map paths, and the matching model and stride metadata for every map. Paths are relative to the manifest. The template records source mesh hashes; they must match when corrections are applied. Use the same model and inference settings for all comparisons. In particular, reverse controls must use the forward stride.

```bash
python -m kit surfacefix apply work/surfacefix-candidates/manifest.json \
  work/surfacefix-output --region-points 8 --min-points 24 \
  --min-corr 0.5 --min-gain 0.1 --control-margin 0.1 --max-step-vox 1
```

The thresholds are experimental defaults, not calibrated operating points. Choose and freeze them on held-out labelled data before target use. Changing thresholds after seeing target maps invalidates that experiment's preregistration.

## Acceptance checks

Physical point correspondences are frozen from the original geometry. Candidate shifts must follow the local normal, preserve mesh topology and holes, and stay within the physical displacement bound. Selection uses one subset of region points; the selected winner must also improve agreement on a separate subset. Reverse, shuffle and displaced matches must score below the forward agreement. Missing coverage or controls, inadequate agreement, or excessive neighboring offset jumps prevent correction.

A reference trace can share an artifact with the source. Control failures and held-back points reduce this risk but cannot establish that the chosen surface is the true ink layer. The subsets are local spatial checks, not independent scrolls or statistically calibrated confidence estimates.

Accepted candidates are copied into a new mesh. Rejected regions remain unchanged and flagged in the report. A no-correction result is meaningful and has a distinct CLI status. The source remains available for comparison and rollback.

**Rerender and rerun the reader on the final combined surface before claiming an improvement.** Combining locally accepted shifts changes neighboring input context. The scores of separate candidate renders do not validate the final combined render. Check geometry and held-back labelled AUC/high-pass scores where labels exist, with the same controls. A model-output improvement is not a reading.

## Validation scope

The automated tests use synthetic meshes and maps to exercise a recoverable displacement and failures that must reject a correction. They validate software behavior, not performance on real papyrus. No target scroll data is needed for these tests.

A [bounded real papyrus run](logs/2026-10-07-real-surfacefix-validation.md) completed twelve maps and eight full-search reference nulls. It accepted no changes and flagged 16 regions; four had enough coverage for evaluation. Geometry edits outside the declared offset were rejected. This demonstrates real-input rejection behavior, but the frozen patch had no supervised pixels and no successful real correction was established.
