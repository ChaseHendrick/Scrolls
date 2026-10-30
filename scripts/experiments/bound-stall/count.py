"""Valid vertices placed by each generation, for the villa PR that keeps a fresh bounded
vc_grow_seg_from_seed trace growing (villa #2104). Reads the x.tif and generations.tif of
each surface folder given and prints one JSON line per run: the cumulative count of valid
vertices by generation and meta.json's max_gen.

    python count.py RUN_DIR [RUN_DIR ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
import tifffile


def count(run):
    run = Path(run)
    x = tifffile.imread(run / "x.tif")
    gen = tifffile.imread(run / "generations.tif")
    valid = np.isfinite(x) & (x != -1)
    gens = gen[valid].astype(int)
    top = int(gens.max())
    by_gen = np.bincount(gens, minlength=top + 1).cumsum().tolist()
    meta = json.loads((run / "meta.json").read_text())
    return {"run": run.name, "valid": int(valid.sum()), "max_gen": meta.get("max_gen"),
            "cumulative": by_gen}


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(json.dumps(count(arg)))
