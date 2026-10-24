# The patched max_composite and scale_to_uint8, pulled from render_ink.py without its
# torch-importing module imports, so both runs start from the same baseline.
import ast, glob, resource, sys, numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
src = open(sys.argv[1]).read()
keep = [n for n in ast.parse(src).body
        if (isinstance(n, ast.FunctionDef) and n.name in ('max_composite', 'scale_to_uint8'))
        or (isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'LUT_BLOCK_ROWS')]
ns = {'np': np, 'Image': Image}
exec(compile(ast.Module(keep, []), 'render_ink', 'exec'), ns)
comp = ns['max_composite'](sorted(glob.glob('l*.tif')))
strip8, p95 = ns['scale_to_uint8'](comp)
print('new peak GB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20)
