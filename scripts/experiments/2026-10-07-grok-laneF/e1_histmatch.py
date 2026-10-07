"""Lane F E1: histogram-match the PHerc0841 w00 crop to the w045 crop, write Zarrs for ink_9um.

Usage: python e1_histmatch.py REPO_ROOT DATA_DIR OUT_DIR
Writes OUT_DIR/{w00_matched_w045, w00_matched_self, w00_matched_perlayer}.zarr (copies of the
quick crop's layout). Rule: docs/logs/2026-10-07-grok-laneF.md, E1.
"""
import shutil, sys
import numpy as np, zarr
sys.path.insert(0, sys.argv[1])
from kit.layers import open_volume

DATA, OUT = sys.argv[2], sys.argv[3]
src = f"{DATA}/0841-w00_quickcrop_2624_2688.zarr"
w00 = np.asarray(zarr.open_array(f"{src}/0", mode="r")[:])
v45 = open_volume(f"{DATA}/w045_9um.zarr")
ref = np.asarray(v45[:, 3840:4480, 2560:3200]).astype(np.uint8)
assert w00.shape == ref.shape, (w00.shape, ref.shape)

def lut(a, b):
    """uint8 lookup table mapping the CDF of a onto the CDF of b."""
    ha = np.bincount(a.ravel(), minlength=256)
    ca = (np.cumsum(ha) - ha / 2) / a.size      # mid-bin CDF, so a self-match is the identity
    cb = np.cumsum(np.bincount(b.ravel(), minlength=256)) / b.size
    return np.clip(np.searchsorted(cb, ca), 0, 255).astype(np.uint8)

out = {"w00_matched_w045": lut(w00, ref)[w00], "w00_matched_self": lut(w00, w00)[w00],
       "w00_matched_perlayer": np.stack([lut(w00[z], ref[z])[w00[z]] for z in range(w00.shape[0])])}
for name, arr in out.items():
    dst = f"{OUT}/{name}.zarr"; shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
    z = zarr.open_array(f"{dst}/0", mode="r+"); z[:] = arr
    print(name, "mean", round(float(arr.mean()), 2), "std", round(float(arr.std()), 2),
          "changed_vox", float((arr != w00).mean()))
print("w00 mean/std", round(float(w00.mean()), 2), round(float(w00.std()), 2),
      "w045 mean/std", round(float(ref.mean()), 2), round(float(ref.std()), 2))
