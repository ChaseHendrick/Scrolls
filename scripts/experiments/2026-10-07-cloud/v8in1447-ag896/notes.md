# Job v8in1447-ag896: control comparability (2026-10-07)

This branch contains run and scoring scripts; no completed results are recorded here.
Future forward and reverse v8in-1447 runs both use stride 42. Reverse maps are named
`v8in1447_rev_s42.npy`; reverse ensemble outputs use `_reverse_s42.npy`.

The scorer prefers the new stride 42 map, then falls back to a historical
`v8in1447_rev_s64.npy` if present, retaining its stride and marking the comparison
`provisional_stride_mismatch`. Changing both stride and depth direction cannot isolate
the direction effect. `control_map`, `control_status`, `control_note`, and settings
identify the selected control. Missing reverse members are marked `missing`.

Historical maps and reverse ensemble filenames are preserved. No inference was run
for this correction. The updated workflow and available controls still need validation
on the real crop; script tests establish selection and reporting behavior only.

## Script validation

Run `python -m unittest discover -s scripts/experiments/2026-10-07-cloud/v8in1447-ag896 -p 'test_*.py' -v` from the checkout. The six tests use synthetic map
files and mocked scoring; they verify selection/reporting and do not claim real-data
validation. Scorer exit success means available maps were scored, not that a matched
control passed or inference completed. Read the recorded status fields.
