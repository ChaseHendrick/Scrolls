"""Collect scores/*.json into results.json (rows in the format of the cloud README).

    python scripts/experiments/2026-10-07-cloud/v8in1447-ag405/make_results.py [SECONDS_JSON]
"""
import argparse
import json
import pathlib
from controls import control_status

HERE = pathlib.Path(__file__).resolve().parent
S = HERE / "scores"
V8 = "YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062@2bf9f421862cda0ed41dcae6e8274c12e295d03a"
D9 = "d9v2_ft-012000.pth (TAUIL-Abd-Elilah/pherc0826-first-letters-search v1.0, sha256 50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966)"
MAPS = {
    "d9v2": ("d9v2", {"checkpoint": D9, "villa": "PR #1865", "overlap": 0.5, "blend": "hann"}, "reverse is villa --direction both"),
    "v8in1447_s42": ("v8in-1447", {"checkpoint": V8, "stride": 42, "batch": 4}, "reverse at stride 42"),
    "v8in1447_s21": ("v8in-1447", {"checkpoint": V8, "stride": 21, "batch": 4}, "optional stride 21 comparison: direction is confounded with stride 42 control"),
    "ens_v8in1447_d9v2_mean": ("v8in-1447 + d9v2", {"maps": ["v8in1447_s42", "d9v2"], "ensemble": "mean"},
                               "reverse: v8in1447 s42 reverse + d9v2 reverse, same method"),
    "ens_v8in1447_d9v2_rank": ("v8in-1447 + d9v2", {"maps": ["v8in1447_s42", "d9v2"], "ensemble": "rank"},
                               "reverse: v8in1447 s42 reverse + d9v2 reverse, same method"),
}
def collect(scores, seconds=None):
    """Collect complete score pairs; missing rows and controls remain explicit."""
    seconds = seconds or {}
    rows, missing, incomplete = [], [], []
    for name, (reader, settings, note) in MAPS.items():
        a_path, h_path = scores / f"auc_{name}.json", scores / f"hp_{name}.json"
        if not (a_path.exists() and h_path.exists()):
            missing.append(name)
            continue
        a, h = json.loads(a_path.read_text()), json.loads(h_path.read_text())
        metadata_path = scores / f"control_{name}.json"
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        available = "control" in a and "control" in h
        if name == "d9v2":
            status = "matched" if available else "missing"
            control_note = "Villa --direction both uses the same overlap and blend settings."
        else:
            forward_stride = settings.get("stride", 42)
            status = control_status(forward_stride, metadata.get("reverse_stride"), available)
            control_note = {
                "matched": "Forward and reverse v8in both use stride 42.",
                "missing": "One or more reverse control members are missing.",
                "provisional_stride_mismatch": "Direction is confounded with stride; use matching stride controls.",
                "provisional_unverified": "Historical score files lack reverse-stride provenance; comparability is unverified.",
            }[status]
        if status != "matched":
            incomplete.append(name)
        row = {"job": "v8in1447-ag405", "segment": "0841-ag405", "window": "crop", "inner_px": 64,
               "map_from": "bare-crop", "map": name, "reader": reader, "settings": dict(settings), "device": "cpu",
               "auc_as_stored": a["forward"]["auc"], "auc_reversed": a.get("control", {}).get("auc"),
               "hp_r": h["forward"]["hp_r"], "hp_r_reversed": h.get("control", {}).get("hp_r"),
               "hp_null_max_abs": h["forward"]["null_max_abs"], "ink_px": a["forward"]["ink_px"],
               "notes": note, "control_status": status, "control_note": control_note}
        if metadata:
            row["settings"]["reverse_stride"] = metadata.get("reverse_stride")
            row["control_map"] = metadata.get("control_map")
        if name in seconds:
            row["seconds"] = seconds[name]
        rows.append(row)
    primary = [name for name in MAPS if name != "v8in1447_s21"]
    primary_missing = [name for name in missing if name in primary]
    primary_incomplete = [name for name in incomplete if name in primary]
    status = {"job": "v8in1447-ag405", "status": "partial" if primary_missing or primary_incomplete else "complete",
              "expected_maps": list(MAPS), "scored_maps": [row["map"] for row in rows],
              "missing_maps": missing, "unmatched_control_maps": incomplete,
              "primary_maps": primary, "primary_missing_maps": primary_missing,
              "primary_unmatched_control_maps": primary_incomplete,
              "optional_maps": ["v8in1447_s21"]}
    return rows, status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seconds_json", nargs="?")
    parser.add_argument("--scores", type=pathlib.Path, default=S)
    parser.add_argument("--output", type=pathlib.Path, default=HERE / "results.current.json")
    parser.add_argument("--status", type=pathlib.Path, default=HERE / "status.current.json")
    args = parser.parse_args()
    seconds = json.loads(pathlib.Path(args.seconds_json).read_text()) if args.seconds_json else {}
    rows, status = collect(args.scores, seconds)
    for path, value in ((args.output, rows), (args.status, status)):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(value, indent=1) + "\n")
        tmp.replace(path)
    for row in rows:
        print(f"| {row['map']} | {row['auc_as_stored']} | {row['auc_reversed']} | {row['hp_r']} | {row['hp_r_reversed']} | {row['control_status']} |")


if __name__ == "__main__":
    main()
