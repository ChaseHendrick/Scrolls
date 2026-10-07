"""Control provenance for this crop; historical files are never renamed."""


def choose_reverse(resolve, matching, legacy):
    """Prefer stride 42; preserve stride 64 as a provisional fallback."""
    for name, stride in ((matching, 42), (legacy, 64)):
        path = resolve(name)
        if path is not None:
            return name, path, stride, control_status(42, stride, True)
    return None, None, None, "missing"


def control_status(forward_stride, reverse_stride, available):
    if not available:
        return "missing"
    if forward_stride is None or reverse_stride is None:
        return "provisional_unverified"
    return "matched" if forward_stride == reverse_stride else "provisional_stride_mismatch"


if __name__ == "__main__":
    from pathlib import Path
    import sys
    maps = Path(sys.argv[1])
    def resolve(name):
        path = maps / name
        return str(path) if path.exists() else None
    name, path, stride, status = choose_reverse(resolve, "v8in1447_s42_reverse.npy", "v8in1447_s64_reverse.npy")
    print(path or "")
    print(stride or "")
