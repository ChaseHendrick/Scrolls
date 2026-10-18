"""Follow one papyrus sheet through a CT cube slice by slice with SAM 2.1 or MedSAM2, and score whether it kept the
same sheet where sheets touch.

Tracing fails where two windings press together: a tracer that follows "the bright layer" hops to the
neighboring sheet. SAM 2.1 (Meta, Apache-2.0) and MedSAM2 (bowang-lab; code Apache-2.0, weights for research
and education only) treat a stack of slices as a video and carry a memory of the object they were shown, so
they may keep one sheet's identity through a contact. Nobody has measured that on scrolls (Untested idea). This
file is the harness for that measurement:

  follow   CUBE.npy (Z, Y, X), SEED.npy (Y, X) labels on the key slice (0 background, 1..K one id per sheet),
           --key Z -> OUT.npz with `labels` (Z, Y, X) uint16, the object id each pixel was given (0 none),
           propagated forward and backward from the key slice along --axis; a box (default) or mask prompt per
           sheet. Needs torch, sam2 (or MedSAM2's fork), Pillow and the weights; CUDA strongly preferred
  score    OUT.npz TRUTH.npy (Z, Y, X) instance labels, one id per sheet -> per sheet: Dice, the share of slices
           where the sheet's pixels mostly sit on the right true sheet (identity kept), the first slice, counted
           from the key slice, where they mostly sit on another sheet (a hop), and the same numbers for the
           control: the seed copied unchanged to every slice, which a follower must beat. numpy only

Every mask here is model output, not a reading. Truth comes from published instance labels (for example the
cubes `kit cubescore` scores, or PHerc0139's traced windings); never a target scroll without its ledger
experiment first.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np


# ------------------------------------------------------------------ frames and prompts

def to_uint8(cube, lo_pct=0.5, hi_pct=99.5):
    """Percentile window of the whole cube to 0..255, the same window for every slice."""
    cube = np.asarray(cube, dtype=np.float32)
    lo, hi = np.percentile(cube, [lo_pct, hi_pct])
    if not hi > lo:
        return np.zeros(cube.shape, np.uint8)
    return (np.clip((cube - lo) / (hi - lo), 0, 1) * 255).round().astype(np.uint8)


def slices(cube, axis):
    """The cube with `axis` moved first, so slice i is cube along that axis."""
    return np.moveaxis(np.asarray(cube), axis, 0)


def write_frames(cube8, folder):
    """Each slice of (n, H, W) uint8 as folder/00000.jpg ... (RGB, quality 95), the layout SAM 2's
    init_state(video_path=...) reads. Returns the folder."""
    from PIL import Image
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(cube8):
        Image.fromarray(np.repeat(s[..., None], 3, axis=2)).save(folder / f"{i:05d}.jpg", quality=95)
    return folder


def frames_tensor(cube8, size=512):
    """MedSAM2's CT input: slices resized to size x size, 3 channels, ImageNet-normalized, float32 tensor
    (n, 3, size, size)."""
    import torch
    import torch.nn.functional as F
    x = torch.as_tensor(cube8, dtype=torch.float32)[:, None] / 255.0
    x = F.interpolate(x, size=(size, size), mode="bilinear", align_corners=False).repeat(1, 3, 1, 1)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    return (x - mean) / std


def box_of(mask):
    """[x0, y0, x1, y1] of a 2D boolean mask, the SAM box prompt; None when empty."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def seed_objects(seed):
    """{object id: 2D bool mask} from a seed label image."""
    seed = np.asarray(seed)
    if seed.ndim != 2:
        raise ValueError(f"the seed must be one 2D slice of labels, got shape {seed.shape}")
    ids = [int(v) for v in np.unique(seed) if v != 0]
    if not ids:
        raise ValueError("the seed has no labeled pixel (0 is background)")
    return {i: seed == i for i in ids}


# ------------------------------------------------------------------ following

def follow(predictor, cube, seed, key, axis=0, prompt="box", mode="video_path", size=512, threshold=0.0):
    """Propagate each seeded sheet from slice `key` through the cube; returns (labels (cube shape) uint16,
    info dict). `predictor` is a SAM 2 video predictor (sam2.sam2_video_predictor.SAM2VideoPredictor or
    MedSAM2's), used through init_state, add_new_points_or_box / add_new_mask, propagate_in_video and
    reset_state. mode "video_path" writes JPEG frames (SAM 2.1); "tensor" passes MedSAM2's normalized tensor."""
    cube = np.asarray(cube)
    if cube.ndim != 3:
        raise ValueError(f"the cube must be 3D, got shape {cube.shape}")
    stack = slices(to_uint8(cube), axis)
    n, H, W = stack.shape
    if not 0 <= key < n:
        raise ValueError(f"key slice {key} is outside 0..{n - 1}")
    objs = seed_objects(seed)
    if next(iter(objs.values())).shape != (H, W):
        raise ValueError(f"seed shape {next(iter(objs.values())).shape} does not match a slice, {(H, W)}")
    if prompt not in ("box", "mask"):
        raise ValueError("prompt must be box or mask")
    logits = {}   # (frame, obj) -> best logit map so far

    def add_prompts(state):
        for oid, m in objs.items():
            if prompt == "mask":
                predictor.add_new_mask(state, frame_idx=key, obj_id=oid, mask=m)
            else:
                predictor.add_new_points_or_box(state, frame_idx=key, obj_id=oid, box=np.array(box_of(m), np.float32))

    with tempfile.TemporaryDirectory() as tmp:
        if mode == "video_path":
            state = predictor.init_state(video_path=str(write_frames(stack, tmp)))
        elif mode == "tensor":
            state = predictor.init_state(frames_tensor(stack, size), H, W)
        else:
            raise ValueError("mode must be video_path or tensor")
        for reverse in (False, True):
            predictor.reset_state(state)
            add_prompts(state)
            for f, ids, masks in predictor.propagate_in_video(state, start_frame_idx=key, reverse=reverse):
                arr = masks.detach().float().cpu().numpy() if hasattr(masks, "detach") else np.asarray(masks)
                arr = arr.reshape(len(ids), H, W)
                for j, oid in enumerate(ids):
                    logits[(int(f), int(oid))] = arr[j]
    labels = np.zeros((n, H, W), np.uint16)
    best = np.full((n, H, W), threshold, np.float32)
    for (f, oid), lg in logits.items():
        win = lg > best[f]
        labels[f][win] = oid
        best[f][win] = lg[win]
    lost = {int(o): [int(f) for f in range(n) if not (labels[f] == o).any()] for o in objs}
    info = {"key": int(key), "axis": int(axis), "prompt": prompt, "mode": mode, "slices": int(n),
            "objects": sorted(int(o) for o in objs), "empty_slices": lost}
    return np.moveaxis(labels, 0, axis), info


# ------------------------------------------------------------------ scoring

def _match(seed, truth_key):
    """Each seed object -> the true sheet it covers most on the key slice."""
    out = {}
    for oid, m in seed_objects(seed).items():
        ids, counts = np.unique(truth_key[m], return_counts=True)
        keep = ids != 0
        if not keep.any():
            raise ValueError(f"seed object {oid} covers no labeled sheet on the key slice")
        out[oid] = int(ids[keep][np.argmax(counts[keep])])
    return out


def score(labels, truth, seed, key, axis=0):
    """Per seeded object: dice, identity_kept (share of slices with any predicted pixel whose majority true
    sheet is the seeded one), first_hop (slices from the key to the first slice whose majority is another
    sheet, None when it never happens) and coverage (share of slices with any pixel). Also the same numbers
    for the copy control (the seed repeated on every slice) under "control"."""
    labels, truth = slices(labels, axis), slices(truth, axis)
    if labels.shape != truth.shape:
        raise ValueError(f"prediction shape {labels.shape} differs from truth {truth.shape}")
    match = _match(seed, truth[key])
    copy = np.broadcast_to(np.asarray(seed)[None], truth.shape)

    def one(pred, oid, inst):
        p, t = pred == oid, truth == inst
        inter = np.logical_and(p, t).sum()
        dice = float(2 * inter / (p.sum() + t.sum())) if (p.sum() + t.sum()) else 0.0
        kept, seen, hop = 0, 0, None
        for f in range(truth.shape[0]):
            v = truth[f][p[f]]
            v = v[v != 0]
            if v.size == 0:
                continue
            seen += 1
            ids, counts = np.unique(v, return_counts=True)
            if ids[np.argmax(counts)] == inst:
                kept += 1
            elif hop is None or abs(f - key) < hop:
                hop = abs(f - key)
        return {"dice": round(dice, 4), "identity_kept": round(kept / seen, 4) if seen else 0.0,
                "first_hop": hop, "coverage": round(sum(p[f].any() for f in range(p.shape[0])) / p.shape[0], 4)}

    out = {"objects": {}, "control": {}}
    for oid, inst in match.items():
        out["objects"][str(oid)] = dict(one(labels, oid, inst), sheet=inst)
        out["control"][str(oid)] = dict(one(copy, oid, inst), sheet=inst)
    o, c = out["objects"].values(), out["control"].values()
    out["mean"] = {k: round(float(np.mean([x[k] for x in o])), 4) for k in ("dice", "identity_kept")}
    out["control_mean"] = {k: round(float(np.mean([x[k] for x in c])), 4) for k in ("dice", "identity_kept")}
    out["beats_control"] = out["mean"]["dice"] > out["control_mean"]["dice"]
    return out


# ------------------------------------------------------------------ models and CLI

def load_predictor(model, config, checkpoint, device):
    """A SAM 2 video predictor. model "sam2": sam2.build_sam.build_sam2_video_predictor (or from_pretrained
    with a Hugging Face id as --checkpoint); "medsam2": MedSAM2's build_sam2_video_predictor_npz."""
    if model == "sam2":
        if checkpoint.startswith("facebook/"):
            from sam2.sam2_video_predictor import SAM2VideoPredictor
            return SAM2VideoPredictor.from_pretrained(checkpoint, device=device)
        from sam2.build_sam import build_sam2_video_predictor
        return build_sam2_video_predictor(config, checkpoint, device=device)
    if model == "medsam2":
        from sam2.build_sam import build_sam2_video_predictor_npz
        return build_sam2_video_predictor_npz(config, checkpoint, device=device)
    raise ValueError("model must be sam2 or medsam2")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    f = sub.add_parser("follow", help="propagate seeded sheets through a cube")
    f.add_argument("cube", help="CT cube, .npy (Z, Y, X)")
    f.add_argument("--seed", required=True, help=".npy (Y, X) labels on the key slice, one id per sheet")
    f.add_argument("--key", type=int, required=True, help="index of the seeded slice along --axis")
    f.add_argument("--axis", type=int, default=0, choices=[0, 1, 2], help="axis to step along (default 0)")
    f.add_argument("--model", default="sam2", choices=["sam2", "medsam2"])
    f.add_argument("--config", default="configs/sam2.1/sam2.1_hiera_t.yaml",
                   help="the model's Hydra config inside the sam2 package (MedSAM2: configs/sam2.1_hiera_t512.yaml)")
    f.add_argument("--checkpoint", default="facebook/sam2.1-hiera-tiny",
                   help="weights file, or a facebook/sam2.1-* Hugging Face id for sam2")
    f.add_argument("--prompt", default="box", choices=["box", "mask"])
    f.add_argument("--device", default="cuda")
    f.add_argument("--out", required=True, help="output .npz (labels plus info)")
    s = sub.add_parser("score", help="score a follow against instance labels, with the copy control")
    s.add_argument("result", help="the .npz `follow` wrote")
    s.add_argument("truth", help=".npy (Z, Y, X) instance labels, one id per sheet, 0 background")
    s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.action == "follow":
            cube, seed = np.load(a.cube), np.load(a.seed)
            pred = load_predictor(a.model, a.config, a.checkpoint, a.device)
            labels, info = follow(pred, cube, seed, a.key, axis=a.axis, prompt=a.prompt,
                                  mode="tensor" if a.model == "medsam2" else "video_path")
            info.update(model=a.model, checkpoint=a.checkpoint, config=a.config)
            np.savez_compressed(a.out, labels=labels, seed=seed, info=json.dumps(info))
            print(json.dumps(info))
            return 0
        z = np.load(a.result)
        info = json.loads(str(z["info"]))
        res = score(z["labels"], np.load(a.truth), z["seed"], info["key"], axis=info["axis"])
        print(json.dumps(res, indent=None if a.json else 1))
        return 0
    except (ValueError, OSError, KeyError) as e:
        print(f"segzoo_sam2 {a.action}: {e}", file=sys.stderr)
        return 2
    except ImportError as e:
        print(f"segzoo_sam2 {a.action} needs torch, Pillow and the sam2 package ({e}); "
              "pip install sam2==1.1.0, or MedSAM2's fork from github.com/bowang-lab/MedSAM2", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
