"""Write a wholly synthetic surface volume and run the local-file interface."""
import argparse
from pathlib import Path
import numpy as np
from scrolls_inkfilter.cli import main

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output_directory", type=Path)
args = parser.parse_args()
args.output_directory.mkdir(parents=True, exist_ok=False)
rng = np.random.default_rng(0)
v = np.full((40, 96, 96), 20.0)
v[14:26] = 120.0
v[23:25, 30:66, 30:66] = 180.0
v = np.clip(v + rng.normal(0, 4, v.shape), 1, 255).astype(np.uint8)
source = args.output_directory / "synthetic.npy"
np.save(source, v)
raise SystemExit(main([str(source), "--output", str(args.output_directory / "map.npy")]))
