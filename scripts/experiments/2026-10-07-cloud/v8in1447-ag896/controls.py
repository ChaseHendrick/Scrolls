"""Select a reverse control without relabelling historical stride 64 maps."""


def choose_reverse(resolve, matching, legacy):
    """Prefer stride 42, then preserve stride 64 as provisional, else missing."""
    for name, stride in ((matching, 42), (legacy, 64)):
        path = resolve(name)
        if path is not None:
            status = "matched" if stride == 42 else "provisional_stride_mismatch"
            note = ("Forward and reverse both use stride 42." if stride == 42 else
                    "Historical reverse uses stride 64; forward uses stride 42. "
                    "Direction is confounded with stride. Rerun reverse at stride 42.")
            return name, path, stride, status, note
    return None, None, None, "missing", "No reverse control is available."
