"""Reader V3 (Domenico Russo, MIT) as an AutoPipeline ink model, through the team's koine inference.

AutoPipeline's ink tool asks a command engine for one map per call: the forward map, or the reverse-depth control
(vc3d_catalog.BUILTIN_MODELS["reader-v3"]). This module reads level 0 of the render whole and runs it through the
Crackle Check Space's koine engine (spaces/crackle-check/koine_engine.py, used unchanged): koine_machines at villa
merge-ink-pipelines 3ea17f5, the checkpoint fetched from its fixed URL and refused unless its SHA-256 matches, loaded
with torch.load(weights_only=True), the centre 17 layers, 384 px patches at 50 % overlap with koine's floored Hann
blend. One koine run makes both directions, so the other direction is kept beside the output (keyed by the SHA-256
of the layers read) and the second call reuses it instead of running the model again.

    python -m kit.koineink RENDER.zarr --output MAP.tif [--reverse-depth 0|1] [--device cpu|cuda|mps] [--json]

Model output, not a reading."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPACE = ROOT / "spaces" / "crackle-check"
READER = "readerv3"


class KoineInkError(ValueError):
    pass


def _space():
    """The Space's koine engine module (its folder on sys.path, as the Space runs it)."""
    if str(SPACE) not in sys.path:
        sys.path.insert(0, str(SPACE))
    try:
        import koine_engine
    except ImportError as exc:
        raise KoineInkError(f"the koine engine needs torch and numpy in this Python ({sys.executable}): {exc}") from exc
    return koine_engine


def checkpoint_spec():
    """Reader V3's fixed URL, SHA-256 and licence (the Space's KOINE_READERS entry), read without importing torch."""
    import ast
    tree = ast.parse((SPACE / "koine_engine.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "KOINE_READERS" for t in node.targets):
            return ast.literal_eval(node.value)[READER]
    raise KoineInkError("spaces/crackle-check/koine_engine.py lists no KOINE_READERS")


def read_render(location, workers=8):
    """Level 0 of the render, all of it, as (layers, rows, columns) uint8."""
    from . import vc3d_region
    from .inkfilter import read_window
    shape = vc3d_region.Volume(location, workers=workers).shape(0)
    vol, _ = read_window(location, 0, [[0, shape[0]], [0, shape[1]], [0, shape[2]]], workers=workers)
    return vol


def _digest(vol):
    import numpy as np
    h = hashlib.sha256(str(vol.shape).encode())
    h.update(np.ascontiguousarray(vol).tobytes())
    return h.hexdigest()


def engine_map(location, output, reverse=False, device="cpu", reader=None, vol=None):
    """One map for AutoPipeline's ink tool: the forward map, or with `reverse` the reverse-depth control, float32 in
    0 to 1 on level 0's grid, written to `output` with a JSON record beside it. `reader` (a KoineReader, else Reader
    V3 loaded once) and `vol` (else level 0 of `location`) are for tests and callers that hold them already."""
    import numpy as np
    import tifffile
    vol = read_render(location) if vol is None else np.asarray(vol)
    if vol.ndim != 3:
        raise KoineInkError(f"the render is {vol.shape}, not layers x rows x columns")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    key = _digest(vol)
    cache = output.parent / f".koineink-{key[:24]}.npz"
    want = "reverse" if reverse else "forward"
    reused = cache.is_file()
    if reused:
        with np.load(cache, allow_pickle=False) as z:
            got = {"forward": z["forward"], "reverse": z["reverse"], "meta": json.loads(str(z["meta"]))}
    else:
        if reader is None:
            reader = _space().KoineReader(READER)
        res = reader.run(vol, device=device)
        meta = {k: v for k, v in res.items() if k not in ("forward", "reverse")}
        meta["reader"] = getattr(reader, "info", None)
        got = {"forward": res["forward"], "reverse": res["reverse"], "meta": meta}
        tmp = cache.with_name(cache.name + ".part.npz")
        np.savez(tmp, forward=got["forward"], reverse=got["reverse"], meta=json.dumps(meta, default=str))
        os.replace(tmp, cache)
    m = np.asarray(got[want], np.float32)
    if m.shape != vol.shape[1:]:
        raise KoineInkError(f"the {want} map is {m.shape}, the render's grid {vol.shape[1:]}")
    tifffile.imwrite(output, m)
    rec = {"location": str(location), "level": 0, "reverse": bool(reverse), "device": device, "model": "reader-v3",
           "checkpoint": checkpoint_spec(), "layers_sha256": key, "reused_other_direction": reused,
           "koine": got["meta"], "output": str(output), "note": "model output, not a reading"}
    side = output.with_suffix(".json")
    side.write_text(json.dumps(rec, indent=2, default=str) + "\n")
    rec["record"] = str(side)
    return rec


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.koineink", description="Reader V3 through koine: one map of a "
                                "render for AutoPipeline's ink tool (model output, not a reading)")
    p.add_argument("render", help="the render: a zarr group whose level 0 is layers x rows x columns")
    p.add_argument("--output", required=True, help="the map to write (float32 TIFF, 0 to 1)")
    p.add_argument("--reverse-depth", type=int, choices=(0, 1), default=0,
                   help="1 for the reverse-depth control (default 0, the forward map)")
    p.add_argument("--device", default="cpu", help="torch device: cpu, cuda or mps (default cpu)")
    p.add_argument("--json", action="store_true", help="print the record as JSON")
    a = p.parse_args(argv)
    try:
        rec = engine_map(a.render, a.output, reverse=bool(a.reverse_depth), device=a.device)
    except (KoineInkError, OSError, ValueError) as exc:
        print(f"kit.koineink: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rec, indent=1, default=str) if a.json else f"reader-v3 map: {rec['output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
