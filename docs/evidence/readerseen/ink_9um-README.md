---
pretty_name: 9 µm ink detection labels
viewer: false
---

# 9 µm ink detection labels

Ink labels for training Herculaneum ink-detection models at ~9 µm isotropic resolution, across four scrolls. Labels only - no CT data; surface volumes come from the [open-data server](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html). The models trained on these labels live at [scrollprize/ink_9um](https://huggingface.co/scrollprize/ink_9um). Training and inference code: villa @ merge-ink-pipelines - see ink-detection/configs/README.md

## Layout

```
ink_9um/
  labels/
    aligned-scrollprizeorg-21slices/    24 segments (PHerc0139, PHerc1667, PHercParis4, PHerc0814)
      <segment>/
        <segment>_inklabels.zarr
        <segment>_supervision_mask.zarr
        <segment>_validation_mask.zarr   (3 segments only)
    native9-scrollprizeorg-21slices/    5 segments (PHerc0139 w035 w039 w040 w041 w044)
      <segment>/
        <segment>_inklabels.zarr
        <segment>_supervision_mask.zarr
```

## Labels

The two folders are two different sources at the same effective scale:

- `aligned-scrollprizeorg-21slices`: annotations transferred onto public 2.4 µm surface volumes, then pooled 4x in XYZ to ~9.6 µm. Arrays are 21 slices deep, annotated only at Z=10; the other planes are zero.
- `native9-scrollprizeorg-21slices`: annotations made directly on native 9.362 µm PHerc. 0139 volumes. Arrays are 28 slices deep, annotated only at Z=14.

They stay separate because the training configs read them as two `datasets` entries, each with its own `segments_path`. Point the entries at the two folders:

```json
"datasets": [
  {
    "segments_path": "/path/to/ink_9um/labels/aligned-scrollprizeorg-21slices",
    ...
  },
  {
    "segments_path": "/path/to/ink_9um/labels/native9-scrollprizeorg-21slices",
    ...
  }
]
```

The training loader finds `<segments_path>/<segment>/<segment>_inklabels.zarr` and friends on its own, so the layout here is exactly what a training run consumes. The three `_validation_mask.zarr` segments (pherc0139-w016, pherc0814-46527, pherc1667-w029) are the online-validation cases the released checkpoints report metrics on

Annotations originate from the Vesuvius Challenge ink annotation dataset and were transferred onto the public surface volumes with the `tifxyz_label_transfer` scripts in [villa](https://github.com/ScrollPrize/villa) (`volume-cartographer/scripts/tifxyz_label_transfer`), with a per-case offset review

## Source volumes

The labels annotate the public z-anisotropic 2.399 µm volumes downsampled to ~9.6 µm isotropic (level-2 XY, 4x z mean-pooling), with segments from PHerc. 0139 (9), Scroll 1667 (6), PHerc. Paris 4 (8), and PHerc. 0814 (1), plus 5 native 9.362 µm segments from PHerc. 0139. See the [model README](https://huggingface.co/scrollprize/ink_9um) for how inputs are prepared

Aligned public 2.399 µm volumes (used at level-2 XY with 4x z mean-pooling):

| Segment | Scroll | Source volume |
|---|---|---|
| pherc0139-w016 | PHerc. 0139 | [20250108000004-w029_2025010827 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20250108000004-w029_2025010827/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w017 | PHerc. 0139 | [20250108000005-w030_2025010818 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20250108000005-w030_2025010818/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w028 | PHerc. 0139 | [20260115000000-w044_2026011522 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260115000000-w044_2026011522/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w029 | PHerc. 0139 | [20260126000000-w045_2026012619 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260126000000-w045_2026012619/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w035 | PHerc. 0139 | [20260317000000-w035_2026031718 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260317000000-w035_2026031718/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w039 | PHerc. 0139 | [20260302000000-w039_2026030210 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260302000000-w039_2026030210/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w040 | PHerc. 0139 | [20250831000000-w040_2025083102 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20250831000000-w040_2025083102/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w041 | PHerc. 0139 | [20260108000000-w041_2026010816 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260108000000-w041_2026010816/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0139-w043 | PHerc. 0139 | [20260112000000-w043_2026011217 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260112000000-w043_2026011217/surface-volumes/2.399um-0.22m-78keV-volume-20260102150214.zarr/) |
| pherc0814-46527 | PHerc. 0814 | [20260226000000-46527_2um_try2 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0814/segments/20260226000000-46527_2um_try2/surface-volumes/2.399um-0.22m-78keV-volume-20260309142202.zarr/) |
| pherc1667-w013 | Scroll 1667 | [20240304141531-w013_20240304141531_flatboi · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc1667/segments/20240304141531-w013_20240304141531_flatboi/surface-volumes/2.399um-0.22m-78keV-volume-20251217075048.zarr/) |
| pherc1667-w018 | Scroll 1667 | [20240304144031-w018_20240304144031_flatboi · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc1667/segments/20240304144031-w018_20240304144031_flatboi/surface-volumes/2.399um-0.22m-78keV-volume-20251217075048.zarr/) |
| pherc1667-w023 | Scroll 1667 | [20240304161941-w023_20240304161941_flatboi · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc1667/segments/20240304161941-w023_20240304161941_flatboi/surface-volumes/2.399um-0.22m-78keV-volume-20251217075048.zarr/) |
| pherc1667-w028 | Scroll 1667 | [20251208130119-w028_20251208130119156_flatboi · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc1667/segments/20251208130119-w028_20251208130119156_flatboi/surface-volumes/2.399um-0.22m-78keV-volume-20251217075048.zarr/) |
| pherc1667-w029 | Scroll 1667 | [20251212185248-w029_20251212185248662_flatboi · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc1667/segments/20251212185248-w029_20251212185248662_flatboi/surface-volumes/2.399um-0.22m-78keV-volume-20251217075048.zarr/) |
| pherc1667-w031 | Scroll 1667 | [20251223230000-w031_2025122323_flatboi · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc1667/segments/20251223230000-w031_2025122323_flatboi/surface-volumes/2.399um-0.22m-78keV-volume-20251217075048.zarr/) |
| phercparis4-w00 | PHerc. Paris 4 | [20231016151002 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20231016151002/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w01 | PHerc. Paris 4 | [20230702185753 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20230702185753/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w02 | PHerc. Paris 4 | [20231031143852 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20231031143852/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w03 | PHerc. Paris 4 | [20231106155351 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20231106155351/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w05 | PHerc. Paris 4 | [20231012184424 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20231012184424/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w06 | PHerc. Paris 4 | [20231210121321 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20231210121321/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w07 | PHerc. Paris 4 | [20231007101619 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20231007101619/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |
| phercparis4-w09 | PHerc. Paris 4 | [20230929220926 · 2.399 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHercParis4/segments/20230929220926/surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/) |

Native 9.362 µm volumes (PHerc. 0139, used as-is):

| Segment | Scroll | Source volume |
|---|---|---|
| w035 | PHerc. 0139 | [20260317000000-w035_2026031718 · 9.362 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260317000000-w035_2026031718/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr/) |
| w039 | PHerc. 0139 | [20260302000000-w039_2026030210 · 9.362 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260302000000-w039_2026030210/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr/) |
| w040 | PHerc. 0139 | [20250831000000-w040_2025083102 · 9.362 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20250831000000-w040_2025083102/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr/) |
| w041 | PHerc. 0139 | [20260108000000-w041_2026010816 · 9.362 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260108000000-w041_2026010816/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr/) |
| w044 | PHerc. 0139 | [20260115000000-w044_2026011522 · 9.362 µm](https://vesuvius-challenge-open-data.s3.amazonaws.com/index.html#PHerc0139/segments/20260115000000-w044_2026011522/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr/) |

Note: segment names in the first column come from the annotation dataset and do not track the public segment w-numbering - e.g. pherc0139-w016 maps to the public segment 20250108000004-w029
