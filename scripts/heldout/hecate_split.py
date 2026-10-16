"""Which label pixels could Hecate's own training stages draw? (docs/logs/2026-10-16-reader-exposure.md)

Applies the train/validation split rule of the team's published Hecate trainer to one segment's
label masks from the ink dataset the Hecate card cites (hf://buckets/scrollprize/datasets/ink).
The rule is ported, numpy only, from villa branch `distilled_3d_ink`, commit 5ff00ca0
(Giorgio Angelotti, 2026-09-17), `vesuvius/src/vesuvius/ink_detection/data/multiteacher.py`:

  max_pool_mask      lines 47-53    16 px cells, a cell is set if any pixel is
  spatial_holdout    lines 98-108   no validation mask: 10 % of 1024 px blocks, ordered by a seeded hash
  patch_coordinates  lines 111-134  training patches: 256 px, stride 128, at least 5 % supervised cells,
                                    footprint outside the holdout dilated by a 256 px guard
  prepare_manifest   lines 184-215  holdout = the validation mask when it has any pixel; validation_only
                                    when no training patch is left

`scipy.ndimage.maximum_filter(mode="constant")` on booleans is replaced by an integral-image box test,
which gives the same mask. The archived manifest behind the released weights is not public (the
trainer's guide, `vesuvius/docs/hecate.md` at 5ff00ca0, says a new manifest "creates a new split, not a
reproduction of an archived run"), so the output is what this rule gives on the published masks, not
a record of the released run.

  python3 scripts/heldout/hecate_split.py DIR PREFIX[:IDENTITY] [...] [--suffix _v2] [--seed 27]

DIR holds PREFIX_supervision_mask{SUFFIX}.tif, PREFIX_inklabels{SUFFIX}.tif and, when the dataset has
one, PREFIX_validation_mask{SUFFIX}.tif. IDENTITY is the trainer's `scroll/folder` name (for example
0139/w043_2026011217); it only matters when there is no validation mask. Prints one JSON object per
segment. Reads label masks only, never CT or ink maps. Needs numpy, and tifffile with imagecodecs or
Pillow for the LZW TIFFs.
"""

import hashlib
import json
import math
import os
import sys

import numpy as np

MASK_FACTOR = 16
PATCH = 256
GUARD = 256
SEED = 27  # prepare_manifest's default


def stable_seed(*parts):
    return int.from_bytes(hashlib.sha256(":".join(map(str, parts)).encode()).digest()[:8], "big")


def max_pool_mask(mask, factor=MASK_FACTOR):
    mask = np.asarray(mask) > 0
    h, w = mask.shape
    padded = np.pad(mask, ((0, (-h) % factor), (0, (-w) % factor)))
    return padded.reshape(math.ceil(h / factor), factor, math.ceil(w / factor), factor).any(axis=(1, 3))


def cell_counts(mask, factor=MASK_FACTOR):
    """Number of set pixels in each cell of max_pool_mask's grid."""
    mask = np.asarray(mask) > 0
    h, w = mask.shape
    padded = np.pad(mask, ((0, (-h) % factor), (0, (-w) % factor)))
    return padded.reshape(math.ceil(h / factor), factor, math.ceil(w / factor), factor).sum(axis=(1, 3), dtype=np.int64)


def box_any(mask, size):
    """scipy.ndimage.maximum_filter(mask, size=size, mode="constant") for a boolean mask and odd size."""
    r = size // 2
    m = np.pad(np.asarray(mask, bool), r).astype(np.int64)
    ii = np.pad(m.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = np.asarray(mask).shape
    tot = ii[size:size + h, size:size + w] - ii[0:h, size:size + w] - ii[size:size + h, 0:w] + ii[0:h, 0:w]
    return tot > 0


def spatial_holdout(support, seed, identity, block_size=1024):
    cells = block_size // MASK_FACTOR
    blocks = sorted(set(zip(*(np.nonzero(support)[i] // cells for i in (0, 1)))))
    if len(blocks) < 2:
        raise ValueError(f"Not enough spatial blocks to split {identity}")
    blocks.sort(key=lambda p: stable_seed(seed, identity, *p))
    selected = blocks[:max(1, round(len(blocks) * 0.1))]
    mask = np.zeros_like(support)
    for by, bx in selected:
        mask[by * cells:(by + 1) * cells, bx * cells:(bx + 1) * cells] = True
    return mask, [[int(y), int(x)] for y, x in selected]


def patch_coordinates(support, heldout, shape_yx, patch=PATCH, guard=GUARD):
    size = patch // MASK_FACTOR
    guard_cells = math.ceil(guard / MASK_FACTOR)
    exclusion = box_any(heldout, 2 * guard_cells + 1)

    def sums(mask, ys, xs):
        integral = np.pad(mask.astype(np.uint32).cumsum(0, dtype=np.uint32).cumsum(1, dtype=np.uint32), ((1, 0), (1, 0)))
        return integral[ys + size, xs + size] - integral[ys, xs + size] - integral[ys + size, xs] + integral[ys, xs]

    def scan(stride, validation):
        ys, xs = np.meshgrid(np.arange(0, (shape_yx[0] - patch) // MASK_FACTOR + 1, stride),
                             np.arange(0, (shape_yx[1] - patch) // MASK_FACTOR + 1, stride), indexing="ij")
        ys, xs = ys.ravel(), xs.ravel()
        if validation:
            keep = sums(heldout & support, ys, xs) > 0
        else:
            keep = (sums(support, ys, xs) >= 0.05 * size * size) & (sums(exclusion, ys, xs) == 0)
        return np.stack((ys[keep], xs[keep]), axis=1).astype(np.int32) * MASK_FACTOR

    return scan(size // 2, False), scan(size, True)


def split(sup, val=None, ink=None, *, identity="", seed=SEED):
    """The trainer's split of one segment, plus our coverage counts.

    sup, val, ink: full-resolution 2D masks (val None when the dataset has no validation mask).
    Returns train_patches, val_patches, validation_only and generated_blocks as the trainer would record
    them, and, from us, how many supervised (and supervised ink) pixels lie in a training patch footprint.
    """
    shape = np.asarray(sup).shape
    support = max_pool_mask(sup)
    sup_cells = cell_counts(sup)
    out = {"shape": list(shape), "supervised_px": int(sup_cells.sum())}
    generated = []
    heldout = max_pool_mask(val) if val is not None else None
    if heldout is not None and heldout.any():
        val_support = support | heldout
        both = (np.asarray(sup) > 0) & (np.asarray(val) > 0)
        out["supervised_in_validation_px"] = int(both.sum())
        out["validation_px"] = int((np.asarray(val) > 0).sum())
        holdout_source = "validation mask"
    else:
        heldout, generated = spatial_holdout(support, seed, identity)
        val_support = support
        holdout_source = "generated blocks (no validation mask)"
    train, valp = patch_coordinates(val_support, heldout, shape)
    cover = np.zeros(support.shape, bool)
    n = PATCH // MASK_FACTOR
    for y, x in train:
        cover[y // MASK_FACTOR:y // MASK_FACTOR + n, x // MASK_FACTOR:x // MASK_FACTOR + n] = True
    out.update(holdout=holdout_source, generated_blocks=len(generated), train_patches=int(len(train)),
               val_patches=int(len(valp)), validation_only=len(train) == 0,
               supervised_px_in_training_patches=int(sup_cells[cover].sum()))
    if ink is not None:
        ink_cells = cell_counts((np.asarray(ink) > 0) & (np.asarray(sup) > 0))
        out["supervised_ink_px"] = int(ink_cells.sum())
        out["supervised_ink_px_in_training_patches"] = int(ink_cells[cover].sum())
    s = max(out["supervised_px"], 1)
    out["share_supervised_in_training_patches"] = round(out["supervised_px_in_training_patches"] / s, 4)
    if "supervised_in_validation_px" in out:
        out["share_supervised_in_validation"] = round(out["supervised_in_validation_px"] / s, 4)
    return out


def _read(path):
    """A single-page mask TIFF. The dataset's masks are LZW, which tifffile reads only with imagecodecs,
    so Pillow reads them when imagecodecs is missing."""
    try:
        import tifffile
        a = tifffile.imread(path)
    except (ImportError, ValueError):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as im:
            a = np.asarray(im)
    if a.ndim == 3:  # first page or first channel; the dataset's masks are single-page and single-channel
        a = a[..., 0] if a.shape[-1] in (3, 4) else a[0]
    return a


def main(argv):
    args, suffix, seed = [], "_v2", SEED
    it = iter(argv)
    for a in it:
        if a == "--suffix":
            suffix = next(it)
        elif a == "--seed":
            seed = int(next(it))
        else:
            args.append(a)
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = args[0]
    for item in args[1:]:
        prefix, _, identity = item.partition(":")
        p = lambda kind: os.path.join(root, f"{prefix}_{kind}{suffix}.tif")
        sup = _read(p("supervision_mask"))
        val = _read(p("validation_mask")) if os.path.exists(p("validation_mask")) else None
        ink = _read(p("inklabels")) if os.path.exists(p("inklabels")) else None
        r = split(sup, val, ink, identity=identity or prefix, seed=seed)
        print(json.dumps({"segment": prefix, "identity": identity or None, "suffix": suffix, **r}))
        del sup, val, ink
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
