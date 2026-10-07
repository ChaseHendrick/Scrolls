"""Fetch the public PHerc0841 files lane B needs (about 2 GB): 9.366 um meshes, the team's
2.4 um ink maps, the 20260918 labels (level 2) and level 0 of the 9.366 um surface volumes.

    python fetch_data.py DATA_DIR

Uses kit.fetch with the bucket's global endpoint (the us-east-1 regional endpoint answered
403 from the lane B container on 2026-10-07; the global one listed fine).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
from kit import fetch  # noqa: E402
B = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
SEGS = {"w00": "20260220213127-w00", "ag896": "20260220214732-auto_grown_20260220144552896",
        "ag405": "20260221022814-auto_grown_20260220174252405"}
D = sys.argv[1]
for name, s in SEGS.items():
    root = f"PHerc0841/segments/{s}/"
    sid = s.split("-")[0]
    jobs = [(root + f"mesh/{sid}-on-20250821151531-9.366um.tifxyz", f"{D}/mesh/{name}"),
            (root + "ink-detection", f"{D}/inkdet/{name}"),
            (root + "ink-labels/2.403um-volume-20260319124803/20260918/inklabels.zarr/2", f"{D}/0841-{name}_labels/inklabels.zarr/2"),
            (root + "ink-labels/2.403um-volume-20260319124803/20260918/supervision.zarr/2", f"{D}/0841-{name}_labels/supervision.zarr/2"),
            (root + "surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/0", f"{D}/0841-{name}_9um.zarr/0")]
    for zr in ("inklabels.zarr", "supervision.zarr"):
        for meta in (".zattrs", ".zgroup", "zarr.json"):
            jobs.append(("FILE", root + f"ink-labels/2.403um-volume-20260319124803/20260918/{zr}/{meta}", f"{D}/0841-{name}_labels/{zr}/{meta}"))
    for meta in (".zattrs", ".zgroup", "zarr.json"):
        jobs.append(("FILE", root + f"surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/{meta}", f"{D}/0841-{name}_9um.zarr/{meta}"))
    for j in jobs:
        if j[0] == "FILE":
            import urllib.request
            os.makedirs(os.path.dirname(j[2]), exist_ok=True)
            try:
                open(j[2], "wb").write(urllib.request.urlopen(f"{B}/{j[1]}", timeout=60).read())
            except Exception:
                pass
            continue
        print(name, j[0][len(root):], flush=True)
        fetch.fetch_prefix(j[0], j[1], base=B)
