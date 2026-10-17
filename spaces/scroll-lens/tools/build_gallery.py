"""Build Scroll Lens's gallery with your own ZeroGPU minutes, then (only if you say y) upload it to the Space.

Run it on your own computer, logged in to Hugging Face (`hf auth login`), after the Space is live:

  python3 tools/build_gallery.py SharpMeow/scroll-lens [--size 256] [--seed 2026] [--dry-run]

It calls the Space's `look` endpoint with your token, so every cube's GPU time counts against your ZeroGPU quota
(5 minutes a day on a free account, 40 on PRO). A 256³ cube asks for about half a minute; the quota counts what
each call actually uses. It stops at the first quota refusal and keeps what it has, so a later run (the next day)
continues where it left off: cubes already in gallery/ are skipped.

The plan, fixed by --seed: the eight PHerc. Paris 4 points the organisers trained the 3D ink model on, and one random
point on the papyrus of each other listed scan (lens.random_point). No other Paris 4 point is ever picked, because
its title is still an open prize. Cubes are interleaved so that an early stop still covers several scrolls.

Each cube is saved compact (lens.save_npz: 128 of the 864 embedding components, ink and surface at 16 levels),
about 12 MB for 256³. Then it lists the files and asks before uploading gallery/ to the Space. Needs numpy,
gradio_client and huggingface_hub (python3 -m pip install numpy gradio_client huggingface_hub).
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


def plan(seed, fetch=lens._get):
    """The gallery's cubes in build order: (id, volume, point_zyx, title, note)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    paris = [(f"paris4-train-{i + 1}", "PHercParis4", tuple(p),
              f"PHerc. Paris 4, organisers' training point {i + 1} of 8",
              "One of the eight Paris 4 points the organisers listed for training the 3D ink model, so the ink model "
              "has seen this place: a demonstration, not a test.")
             for i, p in enumerate(lens.PARIS4_TRAINING_POINTS)]
    others = []
    for vid, v in lens.VOLUMES.items():
        if vid == "PHercParis4":
            continue
        p = lens.random_point(vid, rng, fetch=fetch)
        others.append((f"{vid.lower()}-random-{seed}", vid, p, f"{v['scroll']}, a random papyrus point",
                       f"A random point on the papyrus of {v['scroll']} (seed {seed}). {v['note']}".strip()))
    out = []
    while paris or others:            # Paris 4, another scroll, another scroll, Paris 4, ...
        if paris:
            out.append(paris.pop(0))
        out.extend(others[:2])
        others = others[2:]
    return out


def is_quota(exc):
    text = str(exc).lower()
    return "quota" in text or "zerogpu" in text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("space", help="OWNER/NAME of the live Scroll Lens Space")
    ap.add_argument("--size", type=int, default=256, choices=lens.SIZES)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default=str(SPACE_DIR / "gallery"))
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument("--no-upload", action="store_true", help="build only; never ask to upload")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else {"cubes": []}
    have = {c["id"] for c in index["cubes"] if (out / c["file"]).is_file()}
    todo = [c for c in plan(a.seed) if c[0] not in have]
    print(f"{len(have)} cubes already in {out}; {len(todo)} to build at {a.size}³:")
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
    spent = 0.0
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
        meta, _ = lens.load_npz(path)          # checked before it joins the gallery
        dest = out / f"{cid}.npz"
        shutil.copyfile(path, dest)
        index["cubes"] = [c for c in index["cubes"] if c["id"] != cid] + [
            {"id": cid, "volume": vid, "title": title, "note": note, "file": dest.name,
             "point_zyx": list(p), "size": int(meta["cube_size"]), "seconds": meta.get("seconds", {}),
             "device_name": meta.get("device_name"), "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]
        index_path.write_text(json.dumps(index, indent=1) + "\n")
        spent += time.time() - t0
        print(f"  {cid}: {dest.stat().st_size / 1e6:.1f} MB, GPU {sum(meta.get('seconds', {}).values()):.1f} s, "
              f"call {time.time() - t0:.0f} s")
    order = {c[0]: i for i, c in enumerate(plan(a.seed))}
    index["cubes"].sort(key=lambda c: order.get(c["id"], 1 << 30))
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
