"""StrokeNet's preregistered run, start to finish (docs/prereg/2026-10-14-strokenet.md).

  python scripts/strokenet/pipeline.py all  --work WORK --runs RUNS [--device cuda]
  python scripts/strokenet/pipeline.py prep|sweep|finals|validate|test --work WORK --runs RUNS
  python scripts/strokenet/pipeline.py smoke --work WORK --runs RUNS     # tiny run, no test window read

Stages, in order:
  prep      the fixed validation monitor windows (monitor.npz), the baselines fitted on training
            windows (baselines.npz: spectrum, texture, nullspec), the validation evaluation
            windows (evalsets_validation.npz)
  sweep     six configurations, seed 0 (train.py); the one with the best final monitor score
            (mean of T1, T2_20, T3, T4 and T8) is chosen, ties within 0.002 going to fewer
            parameters; it is the released model
  finals    the chosen configuration with seeds 1 and 2, four ablations at seeds 0 to 2, one
            without seam-matched windows, the permuted-label control and the artifact control
  validate  the random-feature CNN baseline is fitted; every model and baseline scores the
            validation windows (read_validation.npz), numpy inference is checked against torch
            on the CPU, evaluate.calibrate() fixes calibration, directions, references and
            validity in calibration.json, and the gate is written to gate.json
  test      only after a passed gate: the test evaluation windows are built and scored once
            (read_test.npz). A marker written before any test window is scored refuses a second
            read, and a test read refuses code that differs from the commit.
evaluate.py then turns read_test.npz and calibration.json into results. A cloud runner calls the
same functions stage by stage.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import data as D  # noqa: E402
import nulls as NL  # noqa: E402

from prov import CODE_FILES, PREREG, code_provenance, sha256_bytes  # noqa: E402,F401

COMMON = ["--steps", "6000", "--eval-every", "500", "--batch", "128"]
SWEEP = {
    "A_w16_d4_lr2e-3": ["--width", "16", "--depth", "4", "--lr", "2e-3"],
    "B_w16_d4_lr1e-3": ["--width", "16", "--depth", "4", "--lr", "1e-3"],
    "C_w16_d4_lr4e-3": ["--width", "16", "--depth", "4", "--lr", "4e-3"],
    "D_w8_d4_lr2e-3": ["--width", "8", "--depth", "4", "--lr", "2e-3"],
    "E_w32_d4_lr2e-3": ["--width", "32", "--depth", "4", "--lr", "2e-3"],
    "F_w16_d5_lr2e-3": ["--depth", "5", "--width", "16", "--lr", "2e-3"],
}
ABLATIONS = {
    "abl_no_nulls": ["--neg-mix", "blank=1"],
    "abl_no_iaaft": ["--neg-mix", "blank=0.4,shuffle=0.2,rot90=0.2"],
    "abl_no_shuffle": ["--neg-mix", "blank=0.4,iaaft=0.2,rot90=0.2"],
    "abl_no_rot90": ["--neg-mix", "blank=0.4,iaaft=0.2,shuffle=0.2"],
}
FINALS = {"seed1": ["--seed", "1"], "seed2": ["--seed", "2"]}
for _n, _a in ABLATIONS.items():
    for _s in (0, 1, 2):
        FINALS[f"{_n}_s{_s}"] = _a + ["--seed", str(_s)]
FINALS.update({
    "abl_no_jitter": ["--jitter", "0,0"],
    "control_permuted": ["--permute-labels"],
    "control_artifact": ["--positives", "blank", "--neg-mix", "iaaft=1,shuffle=1,strip=1"],
})
TIE = 0.002
EVAL_SEED = {"validation": 777, "test": 778, "smoke_test": 779}
N_FIT = 8000                     # windows per class for the fitted baselines
NUMPY_CHECK = 500                # first text and blank validation windows for the numpy check


# ------------------------------------------------------------------ runs
def run_args(name, chosen_args=None):
    """train.py arguments for a run name: a sweep name, or a finals name on the chosen config."""
    if name in SWEEP:
        return COMMON + SWEEP[name] + ["--seed", "0"]
    if name in FINALS:
        if chosen_args is None:
            raise ValueError("finals need the chosen configuration")
        return COMMON + list(chosen_args) + ["--seed", "0"] + FINALS[name]       # a later --seed wins in argparse
    raise KeyError(name)


def train_run(work, runs, name, args, device=None, extra=()):
    import train as T
    out = Path(runs) / name
    if (out / "history.json").exists():
        return json.loads((out / "history.json").read_text())
    argv = ["--work", str(work), "--out", str(out), "--resume"] + list(args) + list(extra)
    mon = Path(runs) / "monitor.npz"
    if mon.exists():
        argv += ["--monitor", str(mon)]
    if device:
        argv += ["--device", device]
    T.main(argv)
    return json.loads((out / "history.json").read_text())


def choose(runs, names=tuple(SWEEP)):
    """The chosen sweep run: best final monitor score (mean of T1, T2_20, T3, T4, T8); ties within
    0.002 of the best go to the run with fewer parameters, then to the better final score, then to
    the earlier name."""
    rows = []
    for n in names:
        h = json.loads((Path(runs) / n / "history.json").read_text())
        rows.append({"name": n, "final_select": h["final_select"], "best_select": h["best_select"],
                     "best_step": h["best_step"], "n_params": h["config"]["n_params"]})
    top = max(r["final_select"] for r in rows)
    near = [r for r in rows if r["final_select"] >= top - TIE]
    pick = sorted(near, key=lambda r: (r["n_params"], -r["final_select"], list(names).index(r["name"])))[0]
    res = {"chosen": pick["name"], "args": SWEEP.get(pick["name"]), "rows": rows, "tie_margin": TIE}
    (Path(runs) / "choice.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


def report_models(runs):
    """Runs scored in the reads: the released model (chosen sweep run, seed 0) first."""
    c = json.loads((Path(runs) / "choice.json").read_text())
    return {"released": c["chosen"], **{k: k for k in FINALS}}


# ------------------------------------------------------------------ baselines' training windows
def training_mixture(work, segs, n, seed, positives="text"):
    """n positives and n negatives drawn like StrokeNet's training batches (default mix, jitter
    shares, blank rotation; no flips or intensity augmentation), as uint8, for the fitted
    baselines. Also returns plain text windows and their IAAFT-20 copies for nullspec."""
    import torch
    import train as T
    rng = np.random.default_rng(seed)
    gen = torch.Generator().manual_seed(seed)
    tr = D.load_split(work, segs, with_segments=True, with_positions=True)
    maps = D.load_maps(work, segs)
    shares = T.parse_jitter(T.DEFAULT_JITTER)
    mix = T.parse_mix(T.DEFAULT_MIX)
    src = {"w": tr[positives], "seg": tr[positives + "_seg"], "pos": tr[positives + "_pos"]}
    blank = {"w": tr["blank"], "seg": tr["blank_seg"], "pos": tr["blank_pos"]}
    u8 = lambda t: np.clip(np.rint(t[:, 0].numpy()), 0, 255).astype(np.uint8)
    pos = u8(T.windows(src, rng.integers(len(src["w"]), size=n), maps, shares, rng))
    counts = rng.multinomial(n, mix)
    negs = []
    if counts[0]:
        b = u8(T.windows(blank, rng.integers(len(blank["w"]), size=counts[0]), maps, shares, rng))
        rot = rng.random(len(b)) < 0.5
        b[rot] = np.rot90(b[rot], 1, axes=(1, 2))
        negs.append(b)
    for kind, c in zip(T.NEG_KINDS[1:], counts[1:]):
        for i in range(0, c, 512):
            w = src["w"][rng.integers(len(src["w"]), size=min(512, c - i))]
            negs.append(u8(NL.make(T.NULL_KIND[kind], torch.from_numpy(w.astype(np.float32))[:, None], rng, gen)))
    neg = np.concatenate(negs)
    text = src["w"][rng.integers(len(src["w"]), size=n)]
    copies = np.concatenate([u8(NL.make("iaaft20", torch.from_numpy(text[i:i + 512].astype(np.float32))[:, None], rng, gen))
                             for i in range(0, n, 512)])
    return pos, neg, text, copies


def eval_windows(work, runs, split, segments=None, limit=0):
    """Build and save a split's evaluation windows (evalsets_<split>.npz, with segment ids and
    positions) and their SHA-256 (evalsets_<split>.json)."""
    runs = Path(runs)
    out = runs / f"evalsets_{split}.npz"
    if out.exists():
        return json.loads((runs / f"evalsets_{split}.json").read_text())
    segs = segments or D.splits()[split]
    if split != "test" and set(segs) & set(D.splits()["test"]):
        raise SystemExit("a test segment was named for a split that is not the test split")
    d = D.load_split(work, segs, kinds=("text", "blank", "dense"), with_segments=True, with_positions=True)
    if limit:                                         # smoke tests only
        d = {k: v[:limit] for k, v in d.items()}
    t0 = time.time()
    es = NL.eval_sets(d, EVAL_SEED[split], D.load_maps(work, segs))
    for k in ("text", "blank", "dense"):
        es[k + "_seg"], es[k + "_pos"] = d[k + "_seg"], d[k + "_pos"]
    np.savez(runs / f"evalsets_{split}.part.npz", **es)
    meta = {"split": split, "segments": segs, "eval_seed": EVAL_SEED[split], "build_s": round(time.time() - t0, 1),
            "provenance": code_provenance(),
            "iaaft_iters": NL.IAAFT_ITERS, "jitter_px": NL.JITTER, "n": {k: int(len(v)) for k, v in es.items()},
            "sha256": {k: NL.array_sha256(v) for k, v in es.items()}}
    (runs / f"evalsets_{split}.json").write_text(json.dumps(meta, indent=1) + "\n")
    (runs / f"evalsets_{split}.part.npz").rename(out)              # last: the npz marks the set as built
    return meta


def prep(work, runs, n_fit=N_FIT, train_segments=None, val_segments=None, limit=0):
    """Monitor windows, the training-mixture baselines and the validation evaluation windows."""
    import baselines as BL
    import train as T
    runs = Path(runs)
    runs.mkdir(parents=True, exist_ok=True)
    sp = D.splits()
    if not (runs / "monitor.npz").exists():
        mon = T.monitor_sets(work, val_segments or sp["validation"], limit)
        np.savez(runs / "monitor.part.npz", **mon)              # written whole, then renamed
        (runs / "monitor.part.npz").rename(runs / "monitor.npz")
    if not (runs / "baselines.npz").exists():
        t0 = time.time()
        pos, neg, text, copies = training_mixture(work, train_segments or sp["train"], n_fit, seed=0)
        models = {"spectrum": BL.fit_spectrum(pos, neg), "texture": BL.fit_texture(pos, neg),
                  "nullspec": BL.fit_nullspec(text, copies)}
        BL.save_models(runs / "baselines.part.npz", models)
        (runs / "baselines.part.npz").rename(runs / "baselines.npz")
        (runs / "baselines.json").write_text(json.dumps({"n_fit": n_fit, "fit_s": round(time.time() - t0, 1),
                                                         "segments": train_segments or sp["train"]}, indent=1) + "\n")
    return eval_windows(work, runs, "validation", segments=val_segments, limit=limit)


# ------------------------------------------------------------------ reads
def fit_randcnn(work, runs, n_fit=N_FIT, train_segments=None):
    import baselines as BL
    runs = Path(runs)
    if (runs / "baseline_randcnn.npz").exists():
        return
    c = json.loads((runs / "choice.json").read_text())
    cfg = json.loads((runs / c["chosen"] / "config.json").read_text())
    pos, neg, _, _ = training_mixture(work, train_segments or D.splits()["train"], n_fit, seed=1)
    BL.save_models(runs / "baseline_randcnn.part.npz",
                   {"randcnn": BL.fit_randcnn(pos, neg, cfg["width"], cfg["depth"], seed=0)})
    (runs / "baseline_randcnn.part.npz").rename(runs / "baseline_randcnn.npz")


def model_hashes(runs):
    """SHA-256 of every reported model's exported weights and final checkpoint."""
    return {lab: {"npz": D.sha256_file(Path(runs) / name / "strokenet.npz"),
                  "final_pt": D.sha256_file(Path(runs) / name / "final.pt")} for lab, name in report_models(runs).items()}


def read(runs, split, device=None, numpy_check=False, provenance=None, allow_dirty=False, work=None, commit=None):
    """Score one split's evaluation windows with every reported model and baseline, once.

    The test split is read once per dataset: a finished read (read_test.npz, written last) is never
    redone, and a marker in the data folder WORK (when given) refuses a read under any other run
    folder. A test read cut short before it wrote read_test.npz (a preempted or crashed container)
    may be redone in the same run folder only, with the same models and the same test windows;
    whatever the cut-short attempt wrote is deleted before the redo and never used or shown, and
    every attempt is recorded in the marker. commit (the cloud volume's commit) runs right after
    the markers are written. A validation read cut short may be redone; a finished one is returned
    as it is."""
    import torch
    import baselines as BL
    import train as T
    runs = Path(runs)
    out_npz, marker = runs / f"read_{split}.npz", runs / f"read_{split}.started.json"
    if split != "test" and out_npz.exists() and (runs / f"read_{split}.json").exists():
        return json.loads((runs / f"read_{split}.json").read_text())
    if split == "test" and out_npz.exists():
        raise SystemExit(f"{out_npz.name} exists: the test split is read once")
    wmark = Path(work) / "read_test.started.json" if (split == "test" and work) else None
    olds = {}
    if split == "test":
        for m in (marker, wmark):
            if m is not None and m.exists():
                olds[m] = json.loads(m.read_text())
                if olds[m].get("runs") != str(runs):
                    raise SystemExit(f"{m} exists: the test split was already read under {olds[m].get('runs')}")
    prov = provenance or code_provenance()
    if split == "test" and prov.get("dirty") is not False and not allow_dirty:
        raise SystemExit("the test read needs committed code (provenance dirty or unknown)")
    models = report_models(runs)
    hashes = model_hashes(runs)
    if split in ("test", "smoke_test"):
        val = json.loads((runs / "read_validation.json").read_text()).get("model_sha256")
        if val != hashes:
            raise SystemExit("the models differ from the ones the validation read scored and calibrated")
    evsha = json.loads((runs / f"evalsets_{split}.json").read_text())["sha256"]
    attempts = []
    for m, old in olds.items():                     # an interrupted read of this run folder
        if old.get("model_sha256") != hashes or old.get("evalsets_sha256") != evsha:
            raise SystemExit(f"{m} exists for other models or other test windows: the test split is read once")
        attempts = old.get("attempts") or [old.get("started")]
    for f in (f"read_{split}.part.npz", f"read_{split}.part.json", f"read_{split}.json"):
        (runs / f).unlink(missing_ok=True)          # left by a read cut short: never used
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    npz_sha = {lab: h["npz"] for lab, h in hashes.items()}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = {"started": now, "attempts": attempts + [now], "provenance": prov, "model_sha256": hashes,
               "evalsets_sha256": evsha, "runs": str(runs)}
    if wmark is not None:
        wmark.write_text(json.dumps(started, indent=1) + "\n")
    marker.write_text(json.dumps(started, indent=1) + "\n")
    if commit:
        commit()
    with np.load(runs / f"evalsets_{split}.npz") as z:     # closed: an open file blocks the volume's commits
        es = {k: z[k] for k in z.files if not k.endswith(("_seg", "_pos"))}
        arrays = {k: z[k] for k in z.files if k.endswith(("_seg", "_pos"))}
    meta = {"split": split, "device": dev, "provenance": prov, "models": {}, "model_sha256": hashes,
            "evalsets_sha256": evsha, "attempts": len(started["attempts"])}
    t0 = time.time()
    for lab, name in models.items():
        model, _ = T.load_model(runs / name, dev)
        t1 = time.time()
        for k, v in es.items():
            arrays[f"cnn/{lab}/{k}"] = T.score(model, v, dev)
        meta["models"][lab] = {"run": name, "score_s": round(time.time() - t1, 1), "npz_sha256": npz_sha[lab]}
    bmodels = BL.load_models(runs / "baselines.npz")
    if (runs / "baseline_randcnn.npz").exists():
        bmodels.update(BL.load_models(runs / "baseline_randcnn.npz"))
    for k, v in es.items():
        for bname, s in BL.score_all(v, bmodels).items():
            arrays[f"base/{bname}/{k}"] = s
    meta["baselines"] = sorted({k.split("/")[1] for k in arrays if k.startswith("base/")})
    if numpy_check:
        sys.path.insert(0, str(REPO))
        from kit import strokenet as KN
        name = models["released"]
        cpu_model, _ = T.load_model(runs / name, "cpu")
        net = KN.StrokeNet(runs / name / "strokenet.npz")
        t1 = time.time()
        rows = {}
        for k in ("text", "blank"):
            w = es[k][:NUMPY_CHECK]
            cpu = T.score(cpu_model, w, "cpu")
            rows[k] = {"numpy_vs_cpu_torch": float(np.abs(net.logits(w) - cpu).max()) if len(w) else 0.0,
                       "device_vs_cpu_torch": float(np.abs(arrays[f"cnn/released/{k}"][:len(w)] - cpu).max()) if len(w) else 0.0,
                       "windows": int(len(w))}
        meta["numpy_check"] = {"rows": rows, "max_abs_logit_diff": max(r["numpy_vs_cpu_torch"] for r in rows.values()),
                               "max_device_vs_cpu": max(r["device_vs_cpu_torch"] for r in rows.values()),
                               "seconds": round(time.time() - t1, 1)}
    meta["read_s"] = round(time.time() - t0, 1)
    np.savez(runs / f"read_{split}.part.npz", **arrays)
    (runs / f"read_{split}.part.json").write_text(json.dumps(meta, indent=1) + "\n")
    (runs / f"read_{split}.part.json").replace(runs / f"read_{split}.json")
    (runs / f"read_{split}.part.npz").replace(out_npz)          # last: the npz marks the read as finished
    return meta


def validate(work, runs, device=None, provenance=None, train_segments=None, n_fit=N_FIT):
    """Random-feature baseline, the validation read, calibration and the gate."""
    import evaluate as E
    fit_randcnn(work, runs, n_fit=n_fit, train_segments=train_segments)
    read(runs, "validation", device, numpy_check=True, provenance=provenance)
    cp = Path(runs) / "calibration.json"
    if cp.exists():                       # a restarted validate: calibration is never refitted
        cal = json.loads(cp.read_text())
        if cal["validation_read_sha256"] != sha256_bytes(Path(runs) / "read_validation.npz"):
            raise SystemExit("calibration.json was made from a different validation read")
    else:
        cal = E.calibrate(runs)
    ok, checks = cal["gate"]["ok"], cal["gate"]["checks"]
    gp = Path(runs) / "gate.json"
    if not gp.exists():
        gp.write_text(json.dumps({"ok": ok, "checks": checks, "calibration_sha256": sha256_bytes(cp)}, indent=1) + "\n")
    return ok, checks


def test(work, runs, device=None, provenance=None, split="test", segments=None, limit=0, allow_dirty=False,
         smoke_ignore_gate=False, commit=None):
    g = json.loads((Path(runs) / "gate.json").read_text())
    if not g["ok"] and not (smoke_ignore_gate and split == "smoke_test"):
        raise SystemExit("validation gate failed: the test split stays unread")
    prov = provenance or code_provenance()
    if split == "test" and prov.get("dirty") is not False and not allow_dirty:
        raise SystemExit("the test read needs committed code (provenance dirty or unknown)")
    eval_windows(work, runs, split, segments=segments, limit=limit)
    return read(runs, split, device, provenance=prov, allow_dirty=allow_dirty, work=work if split == "test" else None,
                commit=commit)


def all_stages(work, runs, device=None):
    prep(work, runs)
    for n in SWEEP:
        train_run(work, runs, n, run_args(n), device)
    c = choose(runs)
    for n in FINALS:
        train_run(work, runs, n, run_args(n, c["args"]), device)
    ok, checks = validate(work, runs, device)
    if not ok:
        print("validation gate failed: the test split stays unread", json.dumps(checks), flush=True)
        return False
    test(work, runs, device)
    return True


def smoke(work, runs, device=None):
    """The whole pipeline on two training segments for a few steps, with a validation segment
    standing in for the test split, so no test window is read."""
    sp = D.splits()
    tr, va = sp["train"][:2], sp["validation"][:1]
    stand_in = sp["validation"][1:2]
    extra = ["--train-segments", ",".join(tr), "--val-segments", ",".join(va), "--steps", "6", "--eval-every", "3",
             "--batch", "16", "--val-limit", "40"]
    prep(work, runs, n_fit=300, train_segments=tr, val_segments=va, limit=40)
    for n in ("A_w16_d4_lr2e-3", "D_w8_d4_lr2e-3"):
        train_run(work, runs, n, run_args(n), device, extra)
    c = choose(runs, names=("A_w16_d4_lr2e-3", "D_w8_d4_lr2e-3"))
    for n in FINALS:
        train_run(work, runs, n, run_args(n, c["args"]), device, extra)
    ok, checks = validate(work, runs, device, train_segments=tr, n_fit=300)
    # a six-step model fails the gate; the smoke run reads its stand-in split anyway, so the read,
    # results and release code run too (the real test split is never read without a passed gate)
    test(work, runs, device, split="smoke_test", segments=stand_in, limit=40, allow_dirty=True, smoke_ignore_gate=True)
    import evaluate as E
    res = E.results(runs, test_split="smoke_test")
    (Path(runs) / "results_smoke.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    E.release(runs, Path(runs) / "release_smoke.npz")
    return ok, checks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=["all", "prep", "sweep", "finals", "validate", "test", "smoke"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--device", default=None)
    a = ap.parse_args(argv)
    Path(a.runs).mkdir(parents=True, exist_ok=True)
    if a.stage == "all":
        all_stages(a.work, a.runs, a.device)
    elif a.stage == "prep":
        print(json.dumps(prep(a.work, a.runs)["n"], indent=1))
    elif a.stage == "sweep":
        for n in SWEEP:
            train_run(a.work, a.runs, n, run_args(n), a.device)
        print(json.dumps(choose(a.runs), indent=1))
    elif a.stage == "finals":
        c = json.loads((Path(a.runs) / "choice.json").read_text())
        for n in FINALS:
            train_run(a.work, a.runs, n, run_args(n, c["args"]), a.device)
    elif a.stage == "validate":
        print(json.dumps(validate(a.work, a.runs, a.device), indent=1, default=str))
    elif a.stage == "test":
        meta = test(a.work, a.runs, a.device)
        print(json.dumps({"split": meta["split"], "read_s": meta["read_s"], "models": list(meta["models"])}, indent=1))
    else:
        print(json.dumps(smoke(a.work, a.runs, a.device), indent=1, default=str))


if __name__ == "__main__":
    main()
