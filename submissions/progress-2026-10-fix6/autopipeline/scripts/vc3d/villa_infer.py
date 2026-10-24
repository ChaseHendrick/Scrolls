"""villa's flat ink inference with the checkpoint loaded by torch's weights-only unpickler.

    python scripts/vc3d/villa_infer.py [--sha256 HEX] INFER_ARGS...

INFER_ARGS are those of `python -m vesuvius.ink_detection.inference.infer`. villa's load_checkpoint
passes weights_only=False to torch.load, which runs any pickle code a .pth carries. Here the checkpoint
is read once into memory, checked against --sha256 when given (so the bytes loaded are the bytes
checked, with no window to swap the file between check and load), and unpickled with
weights_only=True: ink_9um, Reader v2 and d9v2 hold only tensors, dicts and numbers and load the
same; a checkpoint that needs anything else is refused. scripts/vc3d/ink.py's villa engine runs this.
"""
import hashlib
import io
import sys


class CheckpointError(Exception):
    pass


def read_checked(path, want=None):
    """The file's bytes, refused when want (a sha256 hex digest) is given and does not match them."""
    with open(path, "rb") as f:
        data = f.read()
    if want:
        got = hashlib.sha256(data).hexdigest()
        if got != want.strip().lower():
            raise CheckpointError(f"{path}: sha256 {got}, expected {want}; refusing to load it")
    return data


def safe_loader(torch, checkpoint_mod, want=None):
    """A drop-in for villa's load_checkpoint: same path resolution, weights-only load of checked bytes."""
    def load_checkpoint(path, *args, **kwargs):
        resolve = getattr(checkpoint_mod, "resolve_checkpoint_path", None)
        resolved = resolve(path) if resolve else path
        return torch.load(io.BytesIO(read_checked(str(resolved), want)), map_location="cpu", weights_only=True)
    return load_checkpoint


def split_args(argv):
    """(sha256 or None, the arguments for villa's infer)."""
    argv = list(argv)
    want = None
    if argv[:1] == ["--sha256"]:
        if len(argv) < 2:
            raise CheckpointError("--sha256 needs a value")
        want, argv = argv[1], argv[2:]
    return want, argv


def main(argv=None):
    want, rest = split_args(sys.argv[1:] if argv is None else argv)
    import torch
    from vesuvius.ink_detection.inference import infer
    from vesuvius.ink_detection.models import checkpoint
    loader = safe_loader(torch, checkpoint, want)
    unsafe = checkpoint.load_checkpoint
    for name, mod in list(sys.modules.items()):    # every villa module that imported it by name
        if name.split(".")[0] == "vesuvius" and getattr(mod, "load_checkpoint", None) is unsafe:
            mod.load_checkpoint = loader
    checkpoint.load_checkpoint = loader
    infer.load_checkpoint = loader
    return infer.main(rest)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CheckpointError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
