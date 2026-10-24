import glob, resource, numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
def max_composite(tif_paths):
    composite = None
    for tif_path in tif_paths:
        layer = np.asarray(Image.open(tif_path))
        composite = layer if composite is None else np.maximum(composite, layer)
    return composite
comp = max_composite(sorted(glob.glob('l*.tif')))
strip = comp.astype(np.float32)
p95 = np.percentile(strip, 95)
strip = np.clip(strip / p95, 0, 1) * 255 if p95 > 0 else strip
strip8 = strip.astype(np.uint8)
print('old peak GB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 'px', comp.size/1e6, 'Mpx', 'p95', p95, type(p95), (strip/1).dtype)
