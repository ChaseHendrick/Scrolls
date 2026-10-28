---
title: Snapped Labels
emoji: 🧲
colorFrom: yellow
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Vesuvius surface labels moved onto the papyrus, on live CT
tags:
  - vesuvius-challenge
  - herculaneum
  - computed-tomography
  - tifxyz
  - segmentation
datasets:
  - SharpMeow/vesuvius-snapped-labels
---

# Snapped Labels

Published Vesuvius Challenge surface labels of PHerc0139, PHerc0814, PHerc0841 and PHerc0172, each vertex moved
along its mesh normal onto the papyrus recto face, drawn over X-ray CT that your browser streams from the open data.
On fresh test sites, 91% of snapped PHerc0139 vertices sit within one voxel of the face seen in an independent
1.129 µm scan, against 24% for the published labels.

- **Viewer**: pick a segment and a z plane; orange is the published label, blue the snapped one, gray strokes join
  matching points; Animate snap moves each vertex from its published position to its snapped one, slowly. Arrow keys
  step along the label and through z; `?seg=SEGMENT&z=Z` links to a view.
- **All segments**: every segment with its share snapped, median move and held-back count.
- **Voxel exact** (shown once results are published): per scroll, Measured, Certified or Not shown, with the share
  within 0.5, 1 and 2 voxels, the abstain strata, residual histograms and the controls. `?vx=fixture` previews it on
  made-up data under a banner.
- **How it works**: the two methods, how they were measured, the files in each segment folder, and the limits.
- **Connect your tool**: tested snippets for the dataset, a mesh and the CT.

Data: [SharpMeow/vesuvius-snapped-labels](https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels)
(CC BY-NC 4.0, like the open data it comes from). Page source: `spaces/snapped-labels` in
[ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls). Made by Chase Hendrick.
