"""Build Scroll Lens's gallery with your own ZeroGPU minutes, then (only if you say y) upload it to the Space.

Run it on your own computer, logged in to Hugging Face (`hf auth login`), after the Space is live:

  python3 tools/build_gallery.py SharpMeow/scroll-lens [--batch K] [--size 256] [--seed 2026] [--out DIR]
                                 [--dry-run] [--no-upload]

It calls the Space's `look` endpoint with your token, so every cube's GPU time counts against your ZeroGPU quota
(300 s a day on a free account, 40 minutes on PRO). Measured on 2026-10-17 (99 cubes): a 256³ cube uses about 4.5 s
of quota and a 128³ cube about 0.5 s, but ZeroGPU only starts a call while 1.5 times lens.gpu_seconds is left (about
21 s for 256³, 11 s for 128³), so the last seconds of a day go to 128³ cubes or stay unused. It stops at the first
quota refusal and keeps what it has, so a later run (the next day) continues where it left off: cubes already in the
gallery folder are skipped.

The plan, fixed by --seed and --batch:
- batch 1: the eight PHerc. Paris 4 points the organizers trained the 3D ink model on, and one random papyrus point on
  each other listed scan, drawn in lens.VOLUMES order from one generator (numpy default_rng(seed)); interleaved so
  that an early stop still covers several scrolls.
- batch K (2 or more): one more random papyrus point on each scan except Paris 4, seed + K - 1, each scan from its
  own generator default_rng([seed + K - 1, the scan's position in lens.VOLUMES]) with 48 tries.
No other Paris 4 point is ever picked, because its title is still an open prize. A scan whose random-point search
finds no papyrus is skipped with a line saying so. The live gallery (2026-10-17) holds batches 1 to 4 and most of 5 at
256³ and the rest of batch 5 and batches 6 to 9 at 128³.

Each cube is saved compact (lens.save_npz: 128 of the 864 embedding components, ink and surface at 16 levels),
about 12 MB for 256³ and 2 MB for 128³. Then it lists the files and asks before uploading the gallery folder to the
Space. Needs numpy, gradio_client and huggingface_hub (python3 -m pip install numpy gradio_client huggingface_hub).
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPACE_DIR = HERE.parent
sys.path.insert(0, str(SPACE_DIR))
import lens  # noqa: E402

PAPYRUS_TRIES = 48     # random_point tries per scan in batches 2 and up


def batch_seed(seed, batch):
    return seed + batch - 1


def random_entry(vid, point, seed, batch):
    v = lens.VOLUMES[vid]
    return (f"{vid.lower()}-random-{batch_seed(seed, batch)}", vid, tuple(point),
            f"{v['scroll']}, random papyrus point {batch}",
            f"A random point on the papyrus of {v['scroll']} (seed {batch_seed(seed, batch)}). {v['note']}".strip())


def plan(seed, fetch=lens._get, batch=1):
    """The cubes of one batch in build order: (id, volume, point_zyx, title, note). See the module docstring."""
    import numpy as np
    others = []
    if batch == 1:
        rng = np.random.default_rng(seed)
        for vid in lens.VOLUMES:
            if vid == "PHercParis4":
                continue
            try:
                others.append(random_entry(vid, lens.random_point(vid, rng, fetch=fetch), seed, 1))
            except lens.LensError as exc:
                print(f"  {vid}: skipped ({exc})")
        paris = [(f"paris4-train-{i + 1}", "PHercParis4", tuple(p),
                  f"PHerc. Paris 4, organizers' training point {i + 1} of 8",
                  "One of the eight Paris 4 points the organizers listed for training the 3D ink model, so the ink "
                  "model has seen this place: a demonstration, not a test.")
                 for i, p in enumerate(lens.PARIS4_TRAINING_POINTS)]
        return interleave(paris, others)
    s = batch_seed(seed, batch)
    for i, vid in enumerate(lens.VOLUMES):
        if vid == "PHercParis4":
            continue
        try:
            p = lens.random_point(vid, np.random.default_rng([s, i]), fetch=fetch, tries=PAPYRUS_TRIES)
        except lens.LensError as exc:
            print(f"  {vid}: skipped ({exc})")
            continue
        others.append(random_entry(vid, p, seed, batch))
    return others


def interleave(paris, others):
    out = []
    paris, others = list(paris), list(others)
    while paris or others:            # Paris 4, another scroll, another scroll, Paris 4, ...
        if paris:
            out.append(paris.pop(0))
        out.extend(others[:2])
        others = others[2:]
    return out


def gallery_order(ids, seed):
    """Sort keys for the index: batch 1 in its interleaved build order, then each later batch in lens.VOLUMES order.
    Worked out from the ids alone, so sorting needs no bucket reads."""
    vids = [v for v in lens.VOLUMES if v != "PHercParis4"]
    first = [c[0] for c in interleave([(f"paris4-train-{i + 1}",) for i in range(8)],
                                      [(f"{v.lower()}-random-{seed}",) for v in vids])]
    key = {cid: (1, i) for i, cid in enumerate(first)}
    for cid in ids:
        if cid in key:
            continue
        head, _, tail = cid.rpartition("-random-")
        try:
            batch = int(tail) - seed + 1
            pos = [v.lower() for v in vids].index(head)
        except ValueError:
            batch, pos = 1 << 20, 0
        key[cid] = (batch, pos)
    return key


def is_quota(exc):
    text = str(exc).lower()
    return "quota" in text or "zerogpu" in text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("space", help="OWNER/NAME of the live Scroll Lens Space")
    ap.add_argument("--batch", type=int, default=1, help="1: Paris 4 training points and one point per other scan; "
                                                          "K > 1: one more point per scan except Paris 4")
    ap.add_argument("--size", type=int, default=256, choices=lens.SIZES)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default=str(SPACE_DIR / "gallery"))
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument("--no-upload", action="store_true", help="build only; never ask to upload")
    a = ap.parse_args(argv)
    if a.batch < 1:
        ap.error("--batch is 1 or more")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else {"cubes": []}
    have = {c["id"] for c in index["cubes"] if (out / c["file"]).is_file()}
    todo = [c for c in plan(a.seed, batch=a.batch) if c[0] not in have]
    print(f"{len(have)} cubes already in {out}; {len(todo)} to build at {a.size}³ (batch {a.batch}):")
    for cid, vid, p, title, _ in todo:
        print(f"  {cid:28s} {vid:12s} z {p[0]} y {p[1]} x {p[2]}")
    if a.dry_run:
        return 0
    from gradio_client import Client
    from huggingface_hub import get_token
    token = get_token()
    if not token:
        sys.exit("not logged in to Hugging Face; run: hf auth login (your token is what spends your GPU minutes)")
    client = Client(a.space, token=token, verbose=False)
    for cid, vid, p, title, note in todo:
        t0 = time.time()
        try:
            path = client.predict(vid, p[0], p[1], p[2], a.size, "dino,ink,surface", False, True, False,
                                  api_name="/look")
        except Exception as exc:  # noqa: BLE001
            if is_quota(exc):
                print(f"stopping: ZeroGPU quota ({str(exc).strip()[:200]})")
                break
            print(f"  {cid}: failed ({exc}); skipped")
            continue
        if isinstance(path, (list, tuple)):    # look returns (npz, receipt) from 1.1.0
            path = path[0]
        meta, _ = lens.load_npz(path)          # checked before it joins the gallery
        dest = out / f"{cid}.npz"
        shutil.copyfile(path, dest)
        index["cubes"] = [c for c in index["cubes"] if c["id"] != cid] + [
            {"id": cid, "volume": vid, "title": title, "note": note, "file": dest.name,
             "point_zyx": list(p), "size": int(meta["cube_size"]), "seconds": meta.get("seconds", {}),
             "device_name": meta.get("device_name"), "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]
        index_path.write_text(json.dumps(index, indent=1) + "\n")
        print(f"  {cid}: {dest.stat().st_size / 1e6:.1f} MB, GPU {sum(meta.get('seconds', {}).values()):.1f} s, "
              f"call {time.time() - t0:.0f} s")
    order = gallery_order([c["id"] for c in index["cubes"]], a.seed)
    index["cubes"].sort(key=lambda c: order.get(c["id"], (1 << 20, 0)))
    index["tool"], index["version"] = "Scroll Lens", lens.VERSION
    index_path.write_text(json.dumps(index, indent=1) + "\n")
    lens.gallery(out)                          # refuses a malformed index before anything is sent
    files = sorted(p for p in out.iterdir() if p.suffix in (".json", ".npz"))
    total = sum(p.stat().st_size for p in files)
    print(f"\n{len(index['cubes'])} cubes, {total / 1e6:.0f} MB in {out}:")
    for p in files:
        print(f"  {lens.sha256_file(p)[:16]}  {p.stat().st_size / 1e6:7.1f} MB  {p.name}")
    if a.no_upload or not index["cubes"]:
        return 0
    if input(f"Upload these files to {a.space}/gallery? Type y to upload: ").strip().lower() != "y":
        print("nothing uploaded")
        return 0
    from huggingface_hub import HfApi
    HfApi(token=token).upload_folder(folder_path=str(out), path_in_repo="gallery", repo_id=a.space,
                                     repo_type="space", allow_patterns=["*.json", "*.npz"],
                                     commit_message=f"Gallery: {len(index['cubes'])} cubes")
    print("uploaded; the Space restarts with the new gallery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
