"""Lane A synthesis: cross-analysis of the JSON records on open PR branches #6 to #9.

Reads pinned committed records only (git show <commit>:<path>); runs no model and
touches no map. Usage: python3 synth.py [--json OUT]
"""
import json, subprocess, sys, itertools
from pathlib import Path

SOURCE_HEADS = {
    "tricks": "a2951681ad1c590bdd4686c5340cfe1226887d60",
    "v8in1447-w00": "c4a5ead246f502e16a7b34db6629b14562bb630e",
    "v8in1447-ag405": "97d26e74417f42fb87abf80ad25c8a90f5629710",
}
D = "scripts/experiments/2026-10-07-cloud/"

def load(job, name="results.json"):
    out = subprocess.run(["git", "show", f"{SOURCE_HEADS[job]}:{D}{job}/{name}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)

def describe_difference(left, right):
    """A point difference is descriptive; unrelated marginal CIs cannot classify it."""
    return {"diff": round(left["auc_as_stored"] - right["auc_as_stored"], 4),
            "status": "descriptive_only_no_paired_uncertainty",
            "left_control_status": left.get("control_status", "not_recorded"),
            "right_control_status": right.get("control_status", "not_recorded")}


def output_path(destination):
    path = Path(destination)
    if path.resolve() == Path(__file__).with_name("synth.json").resolve():
        raise ValueError("Historical synth.json is immutable; use a new output path.")
    return path


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    destination = output_path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    rows = load("tricks") + load("v8in1447-w00") + load("v8in1447-ag405")
    T = {}
    for r in rows:
        if r.get("auc_as_stored") is None:
            continue
        if r.get("job") == "tricks":
            key = r["map"]
        else:
            nm = {"v8in-1447": "v8in1447_s42", "d9v2": "d9v2"}.get(r["reader"])
            if nm is None:
                nm = "v8in1447_d9v2_" + ("rank" if "rank" in r.get("notes", "") else "mean")
            key = r["job"] + ":" + nm
        T.setdefault(r["segment"], {})[key] = r
    out = {}
    def p(*a): print(*a)

    p("## 1. Same-sheet reader agreement (w00 vs ag896)")
    w, a = T["0841-w00"], T["0841-ag896"]
    common = sorted(k for k in w if k in a and not k.endswith("_shuf"))
    p("maps on both:", len(common))
    pairs = list(itertools.combinations(common, 2))
    conc = disc = 0; flips = []
    for x, y in pairs:
        dw = w[x]["auc_as_stored"] - w[y]["auc_as_stored"]
        da = a[x]["auc_as_stored"] - a[y]["auc_as_stored"]
        if dw * da > 0: conc += 1
        elif dw * da < 0:
            disc += 1
            flips.append((x, y, round(dw, 4), round(da, 4)))
    tau = (conc - disc) / len(pairs)
    p(f"Kendall tau-a = {tau:.3f} ({conc} concordant, {disc} discordant of {len(pairs)})")
    p(f"descriptive discordant pairs: {len(flips)}; no uncertainty classification")
    for f in flips: p("  ", f)
    out["kendall_tau"] = tau; out["discordant_pairs"] = flips
    out["source_heads"] = SOURCE_HEADS
    out["status"] = "descriptive_only_no_paired_uncertainty"

    p("\n## 2. Depth-window transfer within the sheet")
    out["window"] = []
    for base in ["s42", "soup42", "d9v2"]:
        wins = ["z0-20", "z3-23", "z5-25", "z8-27"]
        for src, dst in [("0841-w00", "0841-ag896"), ("0841-ag896", "0841-w00")]:
            S, Dd = T[src], T[dst]
            best = max(wins, key=lambda z: S[f"{base}_{z}"]["auc_as_stored"])
            oracle = max(wins, key=lambda z: Dd[f"{base}_{z}"]["auc_as_stored"])
            tr = Dd[f"{base}_{best}"]["auc_as_stored"]
            de = Dd[base]["auc_as_stored"]; zm = Dd[f"{base}_zmean"]["auc_as_stored"]
            rec = dict(reader=base, chosen_on=src, scored_on=dst, window=best,
                       transferred=tr, default=de, zmean=zm,
                       oracle=Dd[f"{base}_{oracle}"]["auc_as_stored"], oracle_window=oracle)
            out["window"].append(rec)
            p(f"{base:7s} pick on {src[5:]:5s} -> {best}; on {dst[5:]}: transferred {tr:.4f}, "
              f"default {de:.4f}, zmean {zm:.4f}, oracle {oracle} {rec['oracle']:.4f}; "
              f"transfer-default {tr-de:+.4f}, zmean-transfer {zm-tr:+.4f}")

    p("\n## 3. Controls: forward minus reversed, forward minus shuffled")
    out["controls"] = []
    for seg in sorted(T):
        for m, r in sorted(T[seg].items()):
            rev = r.get("auc_reversed"); sh = r.get("auc_shuffled")
            if sh is None and f"{m}_shuf" in T[seg]:
                sh = T[seg][f"{m}_shuf"]["auc_as_stored"]
            if rev is None or m.endswith("_shuf"):
                continue
            out["controls"].append(dict(seg=seg, map=m, fwd=r["auc_as_stored"], rev=rev, shuf=sh,
                                        control_status=r.get("control_status", "not_recorded")))
            flag = " <- reversed >= 0.65" if rev >= 0.65 else ""
            p(f"{seg[5:]:5s} {m:28s} fwd {r['auc_as_stored']:.4f} rev {rev:.4f} "
              f"fwd-rev {r['auc_as_stored']-rev:+.4f} shuf {sh if sh is not None else '':}{flag}")

    p("\n## 4. Published descriptive point differences (uncertainty unmeasured)")
    claims = [("0841-w00", "rv2", "d9v2", "Reader v2 over d9v2"),
              ("0841-ag896", "rv2", "d9v2", "Reader v2 over d9v2"),
              ("0841-w00", "v8in1447-w00:v8in1447_d9v2_rank", "d9v2", "v8in-1447+d9v2 rank over d9v2"),
              ("0841-w00", "v8in1447-w00:v8in1447_s42", "s42", "v8in-1447 over ink_9um s42"),
              ("0841-w00", "soup42", "s42", "soup over seed 42"),
              ("0841-ag896", "soup42", "s42", "soup over seed 42"),
              ("0841-w00", "s42_zmean", "s42", "s42 4-window mean over default"),
              ("0841-ag896", "s42_zmean", "s42", "s42 4-window mean over default"),
              ("0841-w00", "d9v2_zmean", "d9v2", "d9v2 4-window mean over default"),
              ("0841-ag896", "d9v2_zmean", "d9v2", "d9v2 4-window mean over default"),
              ("0841-w00", "d9v2_tta", "d9v2", "d9v2 mirror TTA over default"),
              ("0841-ag896", "d9v2_tta", "d9v2", "d9v2 mirror TTA over default"),
              ("0841-w00", "d9v2+rv2_mean", "rv2", "d9v2+rv2 mean over rv2"),
              ("0841-w00", "d9v2+s42_mean", "d9v2", "mixing in s42 hurts d9v2")]
    out["claims"] = []
    for seg, x, y, lab in claims:
        if x not in T[seg] or y not in T[seg]:
            p(f"{seg} {lab}: missing ({x} or {y})"); continue
        rec = describe_difference(T[seg][x], T[seg][y])
        out["claims"].append(dict(seg=seg, claim=lab, **rec))
        p(f"{seg[5:]:5s} {lab:32s} diff {rec['diff']:+.4f}  descriptive only; paired uncertainty unmeasured")

    if destination is not None:
        with destination.open("w") as stream:
            json.dump(out, stream, indent=1)
    return out


if __name__ == "__main__":
    main()
