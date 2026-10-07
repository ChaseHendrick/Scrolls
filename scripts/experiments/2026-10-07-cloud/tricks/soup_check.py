"""Soup bit-identical check (docs/tricks.md): our soup42_last4.pth against Nieuwlaar's release.

    python soup_check.py SOUP.pth NIEUWLAAR.safetensors

Writes our soup's state dict as a bare safetensors file (as Nieuwlaar's weights/VERIFY.md
describes his) and compares (1) its SHA-256 with the published one and (2) every tensor
with his file, bit for bit.
"""
import hashlib, json, sys, tempfile, os
import torch
from safetensors.torch import save_file, load_file

PUBLISHED = "ab3f1bdefa53733f4d4c46da6c7713c142bc8c703df5098fe8641757d764849c"   # weights/VERIFY.md


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


ours = torch.load(sys.argv[1], map_location="cpu", weights_only=False)["model"]
ours = {k: v.contiguous() for k, v in ours.items() if torch.is_tensor(v)}
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "ours.safetensors")
    save_file(ours, p)
    ours_sha = sha(p)
theirs = load_file(sys.argv[2])
same_names = ours.keys() == theirs.keys()
diff = [k for k in ours if k in theirs and not torch.equal(ours[k], theirs[k])] if same_names else None
res = {"ours_safetensors_sha256": ours_sha, "theirs_file_sha256": sha(sys.argv[2]), "published_sha256": PUBLISHED,
       "sha_match": ours_sha == PUBLISHED, "tensors": len(ours), "same_names": same_names,
       "tensors_differing": None if diff is None else len(diff), "bit_identical": same_names and not diff}
print(json.dumps(res, indent=1))
