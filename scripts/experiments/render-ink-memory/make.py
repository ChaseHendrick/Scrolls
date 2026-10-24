import sys, numpy as np
from PIL import Image
H, W, n = int(sys.argv[1]), int(sys.argv[2]), 5
rng = np.random.default_rng(0)
for i in range(n):
    a = np.zeros((H, W), np.uint8)
    # sparse-ish ink-like signal: mostly zero with some bright patches
    m = rng.random((H // 16, W // 16)) < 0.3
    a[:] = np.kron(m, np.ones((16, 16), np.uint8))[:H, :W] * rng.integers(0, 255, (H, W), dtype=np.uint8)
    Image.fromarray(a).save(f'l{i}.tif', compression='tiff_lzw')
