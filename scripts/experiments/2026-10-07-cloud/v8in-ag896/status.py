"""Report recorded output coverage without inferring job completion from rows."""

EXPECTED = [
    ("v8in", ""), ("v8in depth-shuffled", ""), ("v8in reversed", ""),
    ("ink_9um s42", ""), ("d9v2", ""),
] + [(reader, method) for reader in
     ("v8in + d9v2", "v8in + ink_9um s42", "v8in + d9v2 + ink_9um s42")
     for method in ("mean", "rank")]


def row_key(row):
    return row.get("reader"), row.get("settings", {}).get("ensemble_method", "")


def describe(key):
    reader, method = key
    return reader + (" (" + method + ")" if method else "")


def build_status(rows):
    """Identify missing scored rows and controls; scores cannot prove inference completion."""
    scored = {row_key(row) for row in rows if row.get("auc_as_stored") is not None and row.get("hp_r") is not None}
    missing = [describe(key) for key in EXPECTED if key not in scored]
    missing_controls = []
    for row in rows:
        reader = row.get("reader", "")
        if reader in ("v8in reversed", "v8in depth-shuffled"):
            continue  # Standalone null maps, not maps needing another reverse control.
        for field in ("auc_reversed", "hp_r_reversed"):
            if row.get(field) is None:
                missing_controls.append(describe(row_key(row)) + ": " + field)
        if reader == "v8in" and row.get("auc_shuffled") is None:
            missing_controls.append("v8in: auc_shuffled")
    return {
        "job": "v8in-ag896",
        "status": "partial_results" if missing or missing_controls else "recorded_results",
        "inference_completion": "unknown",
        "expected_rows": len(EXPECTED),
        "recorded_rows": [describe(key) for key in EXPECTED if key in scored],
        "missing_rows": missing,
        "missing_control_fields": missing_controls,
        "control_comparability": "Historical v8in forward stride 42 versus reverse/shuffled stride 64 is provisional; d9v2 and ink_9um use matched settings.",
        "note": "Status describes recorded scoring coverage only. Missing rows do not establish whether inference ran, failed, or was stopped. No v8in benchmark or complete ensemble comparison can be inferred from baseline-only results."
    }
