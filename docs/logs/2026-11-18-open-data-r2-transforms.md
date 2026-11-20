# Open data revision 2 transforms, superseded t1 meshes and vc-delta3d copies (18 Nov 2026)

What changed in the open data, how far it moves points, and what the kit now does about it. Public data only.

## What changed (Sourced fact)

The open-data catalog `metadata.json`
(https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json, Last-Modified 18 Nov 2026 13:26 UTC), its `superseded_by` and `transforms_deprecation` notes, and the codec repository https://github.com/ScrollPrize/vc-delta3d show:

- 14 volume pairs on 10 scrolls (0009B, 0139, 0332, 0343P, 0500P2, 0814, 0841, 1667, MANBp, Paris 4) were
  re-registered as revision 2. 13 of them add a thin-plate spline on top of the affine. Each registration is a folder
  `<sample>/transforms/<from>-to-<to>-r<N>/` with `fit/transform.json`, `fit/fit.json`, `holdout.json`, `pair.json`
  and `final-review.json`; the catalog lists them as `sample.data[type=volume-transform]`.
- `sample.properties.volume_transforms` now carries `revision` and `steps` per chain. Its `matrix` is the affine part
  only. `volume.properties.transforms` is deprecated, holds the affine of the latest revision with no landmarks, and is
  removed after 2026-12-31.
- 233 segments' cross-volume meshes (`tifxyz-transformed`) were re-derived through revision 2 with `-t2` in the path.
  The 681 old entries carry `properties.superseded_by` (path, reason, `retain_until` 2027-02-14).
- PHerc1667: the 2.399 um and 1.129 um surface volumes and ink maps of 19 segments were re-rendered on the t2 meshes;
  the t1 renders and ink maps are superseded. Its 6 ink-label sets stay attached to the t1 2.399 um render (they are
  not superseded and have no t2 version).
- 66 masked volumes have a lossless vc-delta3d copy (`ome-zarr-vcd3d`, `...-masked-fast-q1-c64-v0.3.2.vcd3d.zarr`:
  sharded zarr v3, 64^3 chunks, 1024^3 shards, 8 levels). Metadata history is at `/metadata/history/`.

## How far revision 2 moves points (measurement on public data)

Each pair's r2 moving landmarks were carried through r1 (affine) and r2 (affine plus spline); distances are in
micrometres of the target volume. Residual is the distance to r2's own fixed landmarks (r2 was fitted on them, so its
residual is in-sample; the published held-out RMS is about 1 to 2 voxels).

| Sample | From (um) | To (um) | n | r2 minus r1 median | p90 | max | Residual r1 | Residual r2 | Spline p90 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PHerc0332 | 20251211183505 (2.399) | 20231117143551 (7.91) | 435 | 38.8 | 61.9 | 89.1 | 40.0 | 3.2 | 10.1 |
| PHerc0500P2 | 20250526151718 (2.215) | 20250820143440 (9.362) | 209 | 6.7 | 8.8 | 13.8 | 7.2 | 2.0 | 5.4 |
| PHerc0500P2 | 20250528085330 (4.317) | 20250526151718 (2.215) | 138 | 18.0 | 40.0 | 49.9 | 18.1 | 1.4 | 4.3 |
| PHercMANBp | 20260427100434 (1.129) | 20251216152116 (2.399) | 248 | 7.7 | 16.2 | 26.6 | 7.5 | 1.0 | 9.1 |
| PHerc0814 | 20260309142202 (2.399) | 20250804134230 (9.362) | 361 | 15.4 | 32.6 | 62.4 | 16.6 | 2.2 | 9.8 |
| PHerc0343P | 20250521134555 (8.64) | 20260304131111 (2.215) | 186 | 10.8 | 16.7 | 20.0 | 11.4 | 0.8 | 3.9 |
| PHerc0841 | 20260319124803 (2.403) | 20250821151531 (9.366) | 330 | 11.6 | 21.6 | 49.5 | 11.6 | 2.2 | 19.3 |
| PHerc0139 | 20260102150214 (2.399) | 20250728140407 (9.362) | 234 | 16.6 | 33.5 | 40.2 | 17.6 | 1.7 | 18.5 |
| PHerc0139 | 20260413113053 (1.129) | 20260102150214 (2.399) | 197 | 3.6 | 7.9 | 13.0 | 4.0 | 1.0 | 5.1 |
| PHerc1667 | 20251217075048 (2.399) | 20231117161658 (7.91) | 342 | 14.5 | 20.6 | 27.7 | 14.6 | 2.2 | 5.9 |
| PHerc1667 | 20260323082859 (1.129) | 20251217075048 (2.399) | 213 | 173.0 | 394.0 | 504.3 | 173.0 | 0.8 | 2.7 |
| PHercParis4 | 20260310170716 (45.532) | 20230205180739 (7.91) | 105 | 77.1 | 176.7 | 224.0 | 85.5 | 13.0 | 0.0 (affine only) |
| PHercParis4 | 20260608103018 (1.129) | 20260411134726 (2.4) | 183 | 3.1 | 7.1 | 12.2 | 3.8 | 1.2 | 4.9 |
| PHerc0009B | 20250521125136 (8.64) | 20250820154339 (2.401) | 225 | 14.3 | 27.5 | 38.2 | 14.2 | 2.3 | 6.6 |

Interpretation: on most pairs t1 meshes sat 5 to 40 um off their r2 place, a small fraction of a sheet. The PHerc1667
1.129 um pair moved 173 um at the median, which is about a sheet or more, so the t1 1.129 um renders of PHerc1667 are
not a reliable view of the traced sheet. PHerc0332's 2.399 um volume moved 39 um at the median.

## What the kit does now

`kit/voltransform.py` ([page](../tools/voltransform.md)) reads the table, moves points through the full chain with
the spline (identical to villa's `volreg.cores.deformable` reader on all 13 bent files), skips superseded entries, and
finds vc-delta3d copies. `kit/vc3d_landmarks.py`, `kit/meshaudit.py`, `kit/sentinel.py` and `kit/sheetrefs.py` read
through it, so they keep working after 2026-12-31 and never pick a t1 mesh beside its t2 replacement.

## vc-delta3d reads (measurement)

PHerc0139 `20260319133050` level 0 (2.403 um), region z 6,400 to 6,656, y and x 12,800 to 13,312 (64 MB), zarr 3.4.2,
vc-delta3d 0.3.2, a 4-core cloud container on 18 Nov 2026, two reads each: original (zarr v2, uncompressed 128^3 chunks)
0.81 s then 0.37 s; vc-delta3d copy 0.91 s then 0.58 s. The voxels were identical. On a fast link the copy is not
faster (decode costs about what the transfer saves); it moves 3 to 4 times fewer bytes, so it helps on slow links
(a home connection) and when staging whole regions to disk. `voltransform.open_volume` prefers it only when the codec
is installed.
