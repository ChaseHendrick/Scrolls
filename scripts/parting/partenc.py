"""Base dinovol tokens for a CT window: the Vesuvius Challenge's self-supervised 3D encoder, linked, never copied.

The checkpoint is `scrollprize/dinovol_ps8_9.6um_101626` (`teacher_305k.pt`) on Hugging Face, pinned by revision and
sha256 and loaded with `torch.load(weights_only=True)`, so no pickled code in it runs. Its model page states no
license (checked 30 Oct 2026), so this tool downloads it from its own host at run time and never redistributes it.

The backbone is built from the checkpoint's own config by villa's dinovol code (MIT), in the copy that
jimmylomro/hercUNet vendors at a pinned commit (`hercunet/hercuvit/dinovol/`, with the robust intensity
normalization ported from villa in `hercunet/hercuvit/data/normalize.py`). These are the exact files the frozen
Frag3 run used. They are fetched from raw.githubusercontent.com at that commit, each checked by sha256, into a
cache folder; nothing from them is copied into this repository.
"""
import hashlib
import importlib
import importlib.util
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

DV_REPO = "scrollprize/dinovol_ps8_9.6um_101626"
DV_REV = "02164a5b60bc948fad038617cd7d5c5255fa4333"
DV_FILE = "teacher_305k.pt"
DV_SHA = "875306424046f69ac2767b1447ea99f9dbc6a9c7d28147d8a03ce0346e00dd77"
CODE_REPO = "jimmylomro/hercUNet"
CODE_COMMIT = "de4acb7a5f1e4282adbca21d9a34c0a523041451"
CODE_FILES = {   # path in that repository: sha256
    "LICENSE": "7ee3278dd140aa929caa7d5a3b14934b862af6ff34ea3d47715c8039941afd0f",
    "hercunet/hercuvit/dinovol/THIRD_PARTY.md": "e1afa3c9a1fc85f7c154c5220248cfb4ffd97149b70c0b94c1cb0046e609b5b9",
    "hercunet/hercuvit/dinovol/__init__.py": "b7d09b28b823a11ca9646b986d1f199bfcc6182734952e911c8a49b89da4d0a6",
    "hercunet/hercuvit/dinovol/dinov2_eva.py": "b3ea5822576a0b9509396bd9903f4813ece0b09df266ddf2af01493922602652",
    "hercunet/hercuvit/dinovol/model.py": "43d0a724bab2a299528e4e452a8716f744e13d55ab6c0231d030957409144db1",
    "hercunet/hercuvit/dinovol/patch_encode_decode.py": "ebba0736d9edbf4ff09bf86c7644678d9ad3cb23713c57e230579b838239f2c4",
    "hercunet/hercuvit/dinovol/point_embeddings.py": "599bb81f76bec4888cb68546b9e72e139901b6b09cd848f2779fe57b845922fb",
    "hercunet/hercuvit/dinovol/rope.py": "aa800dbcaada1a4ab4facb50c2db53b8b29d6a9e8ecec1ae99f2e3c02cffb05d",
    "hercunet/hercuvit/data/normalize.py": "85e20a6481520b17af5374e8e4cafd6790290f8df06ccdbfcd8709b4881ba50e",
}
STRIDE = 8              # the encoder's patch size: token i is centered at voxel STRIDE * i + (STRIDE - 1) / 2


def cache_dir():
    return Path(os.environ.get("PARTING_CACHE") or Path.home() / ".cache" / "parting")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def fetch_code(root=None):
    """The pinned encoder code in ROOT/code-COMMIT/, downloading any file not there yet; every file sha256-checked."""
    base = Path(root or cache_dir()) / f"code-{CODE_COMMIT[:12]}"
    for rel, want in CODE_FILES.items():
        p = base / rel
        if not p.exists() or _sha(p) != want:
            p.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://raw.githubusercontent.com/{CODE_REPO}/{CODE_COMMIT}/{rel}"
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            got = hashlib.sha256(data).hexdigest()
            if got != want:
                raise SystemExit(f"{url}: sha256 {got} is not the pinned {want}")
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
    return base


def _load_package(name, folder):
    spec = importlib.util.spec_from_file_location(name, Path(folder) / "__init__.py",
                                                  submodule_search_locations=[str(folder)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_normalizer(code):
    """villa's robust normalization (percentile clip 1 to 99, then median and 1.4826 MAD), from the pinned copy."""
    spec = importlib.util.spec_from_file_location("parting_dinovol_normalize",
                                                  Path(code) / "hercunet/hercuvit/data/normalize.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.dinovol_normalise


def fetch_checkpoint(path=None):
    """The pinned base dinovol checkpoint: PATH when given (checked), else downloaded from the Hub (cached)."""
    if path:
        got = _sha(path)
        if got != DV_SHA:
            raise SystemExit(f"{path}: sha256 {got} is not the pinned {DV_SHA} ({DV_REPO}/{DV_FILE})")
        return str(path)
    from huggingface_hub import hf_hub_download
    p = hf_hub_download(DV_REPO, DV_FILE, revision=DV_REV)
    got = _sha(p)
    if got != DV_SHA:
        raise SystemExit(f"{DV_REPO}/{DV_FILE}@{DV_REV}: sha256 {got} is not the pinned {DV_SHA}")
    return p


class Encoder:
    """Base dinovol on one device: tokens(ct) gives the (288, 16, 16, 16) token grid of a 128^3 uint8 window."""

    def __init__(self, device="cpu", checkpoint=None, code_root=None, threads=None):
        import torch
        if threads:
            torch.set_num_threads(int(threads))
        self.torch = torch
        code = fetch_code(code_root)
        _load_package("parting_dinovol", code / "hercunet/hercuvit/dinovol")
        model = importlib.import_module("parting_dinovol.model")
        self.normalize = load_normalizer(code)
        ck = torch.load(fetch_checkpoint(checkpoint), map_location="cpu", weights_only=True)
        net = model.DinoVitStudentTeacher._build_backbone(ck["config"]["model"])
        state = {k[len("backbone."):]: v for k, v in ck["teacher"].items() if k.startswith("backbone.")}
        missing, _ = net.load_state_dict(state, strict=False)
        missing = [k for k in missing if "num_batches_tracked" not in k]
        if missing:
            raise SystemExit(f"base dinovol: missing weights {missing[:5]}")
        net.return_embed_skips = False
        if device == "cuda" and not torch.cuda.is_available():
            raise SystemExit("--device cuda: no CUDA GPU here; use --device cpu")
        self.device = device
        self.net = net.to(device).eval()
        self.bf16 = device == "cuda"

    def tokens(self, ct):
        torch = self.torch
        x = torch.from_numpy(np.ascontiguousarray(self.normalize(ct), np.float32))[None, None].to(self.device)
        with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=self.bf16):
            tok = self.net.forward_features(x, view_kind="global")["x_norm_patchtokens"]
        g = round(tok.shape[1] ** (1 / 3))
        return tok[0].float().T.reshape(-1, g, g, g).cpu().numpy()

    def record(self):
        return {"repo": DV_REPO, "rev": DV_REV, "file": DV_FILE, "sha256": DV_SHA,
                "code": {"repo": f"https://github.com/{CODE_REPO}", "commit": CODE_COMMIT},
                "device": self.device, "bf16": self.bf16, "torch": self.torch.__version__}
