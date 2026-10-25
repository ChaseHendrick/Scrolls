"""AutoPipeline's ink-ensemble stage: each member map z-scored inside the mask, then the z-scores combined.

    python -m kit inkensemble OUT NAME=MAP NAME=MAP ... [--robust] [--combine mean|trimmed] [--trim T]
        [--weights W ...] [--decode [NAME=]ls|none] [--mask MASK] [--provenance REC.json] [--json]

Where it comes from (Sourced fact). The PHerc. 343 First Letters image (Erwin Nieuwlaar, prize awarded 8 October
2026, https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for) combined the maps of dense_native,
`ink_9um` seeds 42 and 43 and Hecate with a z-score ensemble: each model's map turned into z-scores with that
model's mean and SD, and the z-scores averaged (`ink/scripts/ensemble_maps.py` in
https://github.com/Nieuwlaar/pherc343-first-letters at commit e8370f1f88a211166056df62ea6fcfffe4a1063e, MIT).
`kit ensemble --method zscore` (kit/ensemble.py) is the exact port, with his statistics pooled over a declared
set of maps and his license text. This module is the swappable stage around the same z-score arithmetic. It adds
options his code does not have, and it reuses kit.ensemble's decoding, validity rule and writers. His code also
decodes the villa models' uint8 maps with the clipped label-smoothing decode clip((v - 64) / 128, 0, 1) (kit
ensemble's `ls`) before the z-scores; that decode is not affine, so it changes them. The default here is
`--decode none` (v / 255, affine, so the z-scores are those of the raw map); `--decode NAME=ls` gives a member his
decode.

  center   mean: each member's mean and population SD over the pixels below, SD + 1e-6 (his formula).
           median (`--robust`): each member's median and MAD x 1.4826 (the MAD of a normal distribution times
           1.4826 is its SD), + 1e-6, so a few saturated or dead regions move a member's scale less. A member
           whose MAD is 0 (more than half its pixels share one value) is refused with MADZeroError: its z-scores
           would be huge.
  combine  mean: the weighted mean of the members' z-scores at each pixel (his: unweighted).
           trimmed: at each pixel the k = floor(trim x n) lowest and k highest member z-scores are dropped and
           the weighted mean of the rest is taken; trim is a share above 0 and below 0.5, and a trim that drops
           nobody is refused rather than silently ignored.
  weights  one per member, in the order given (default equal). With mean, at least 0 and not all 0; with trimmed,
           above 0 (a pixel could otherwise keep only weight-0 members).

Pixels. A pixel is valid where every member holds a prediction (non-zero, finite; `keep_zero` counts raw 0) and,
with `mask`, where the mask map is above 0 or a surface volume (zarr) is above 0 in every layer (kit ensemble's
`--valid-from`). Each member's statistics are taken over exactly these pixels, the ones that are combined (his
code takes each model's own valid pixels over pooled maps). No label is ever read: the mask says where a surface
is, never where ink is. Invalid pixels are 0 in the output, so `kit auc` leaves out exactly those.

Output, as kit ensemble's zscore: the combined z is mapped onto 1..65535 (.tif, uint16) or that divided by 65535
(.npy, float32) by one increasing affine map, minimum to 1 and maximum to 65535, so pixel ranks and AUCs are kept up
to the rounding; `raw_out` (.npy) keeps the unscaled values, NaN where invalid. With the defaults (mean, mean, equal
weights) the output equals `kit ensemble --method zscore` on the maps' own statistics, with the same decode,
whenever every member is valid on the same pixels (tests/test_inkensemble.py checks it).

Provenance. Every run writes a kit provenance record (kit/provenance.py) beside the map, OUT with the suffix
.provenance.json unless `provenance_out` names another path: the SHA-256 of every member file, of the mask and of
the outputs, the code commit, and in `notes` the settings and each member's statistics. Its digest is in the
result; `python -m kit provenance check REC.json --files` verifies it later.

Controls. Combine each variant (forward, reverse, depth-shuffled) of the members separately, with the same rule on
that variant's own maps: the ensemble of the reverse maps is the control of the ensemble of the forward maps
(`kit auc --control`), as AutoPipeline's ink stage does for every variant.

AutoPipeline. The plan setting ink.ensemble {"method": "zscore", ...} runs this stage on the planned models' maps
of every variant (kit/autopipe.py, Run.combine_maps; `plan_flags` turns the setting into this command's flags, and
`check_plan` refuses a setting this command would refuse, when the plan is made). Nothing here depends on a
backend registry; `BACKEND` is the entry this stage would take in one.
"""

import math
import time
from pathlib import Path

from . import ensemble as ens
from . import provenance
from .verify import VerifyError, _numpy

CENTERS = ("mean", "median")
COMBINES = ("mean", "trimmed")
MAD_TO_SD = 1.482602218505602     # 1 / the normal quantile at 0.75
SD_EPS = ens.SD_EPS               # 1e-6, his rule, added to every scale
DEFAULT_TRIM = 0.25
ROWS = 256                        # rows per block when the z-scores are combined
KIND = "kit-inkensemble"
VERSION = 1
REPO = Path(__file__).resolve().parents[1]

# The entry a backend registry of AutoPipeline's stages would list under a stage "ensemble".
BACKEND = {
    "zscore": {"origin": "community", "by": "Erwin Nieuwlaar's z-score ensemble of reader maps (PHerc. 343 First "
               "Letters), run by kit inkensemble with optional median and MAD statistics, trimmed mean and weights",
               "kind": "classical", "licence": "MIT arithmetic ported in kit/ensemble.py", "needs": ["numpy", "tifffile"],
               "compute": "cpu", "settings": {"ink": {"ensemble": {"method": "zscore"}}}},
}


def trim_count(n, trim):
    """How many member z-scores a trimmed mean drops at each end of a pixel's sorted values."""
    if not (isinstance(trim, (int, float)) and not isinstance(trim, bool) and 0 < trim < 0.5):
        raise VerifyError(f"trim is a share above 0 and below 0.5, not {trim!r}")
    k = int(math.floor(trim * n + 1e-9))
    if k < 1:
        raise VerifyError(f"a trim of {trim} drops nobody from {n} members: give at least "
                          f"{math.ceil(1 / trim - 1e-9)} members or a larger trim")
    return k


def check_weights(weights, n, combine):
    """Weights as a list of floats, one per member (None: equal)."""
    if weights is None:
        return [1.0] * n
    w = list(weights)
    if len(w) != n:
        raise VerifyError(f"give one weight per member: {len(w)} weights for {n} members")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0 for x in w):
        raise VerifyError("weights are finite numbers of at least 0")
    if combine == "trimmed" and min(w) <= 0:
        raise VerifyError("a trimmed mean needs every weight above 0")
    if sum(w) <= 0:
        raise VerifyError("the weights are all 0")
    return [float(x) for x in w]


class MADZeroError(VerifyError):
    """A member refused by the median and MAD statistics: more than half its valid values are one value."""


def member_stats(values, center, name="member"):
    """{"center", "scale"} of one member's valid values: mean and SD (his formula) or median and MAD x 1.4826."""
    np = _numpy()
    v = np.asarray(values, np.float64)
    if v.size == 0:
        raise VerifyError(f"{name}: no valid pixels")
    if center == "mean":
        n = float(v.size)
        mu = float(v.sum()) / n
        sd = math.sqrt(max(float(np.square(v).sum()) / n - mu * mu, 0.0))
        return {"center": mu, "scale": sd + SD_EPS, "sd": sd}
    if center == "median":
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med)))
        if mad == 0.0:
            raise MADZeroError(f"{name}: more than half its valid pixels share one value, so its MAD is 0; "
                               "use center mean")
        return {"center": med, "scale": mad * MAD_TO_SD + SD_EPS, "mad": mad}
    raise VerifyError(f"center is one of {CENTERS}, not {center!r}")


def combine_z(z, weights, k=0):
    """Combined value per column of z (members x pixels): weighted mean, or with k > 0 the weighted mean after the
    k lowest and k highest values of each column are dropped."""
    np = _numpy()
    z = np.asarray(z, np.float64)
    w = np.asarray(weights, np.float64)
    if k == 0:
        return (w[:, None] * z).sum(0) / w.sum()
    n = z.shape[0]
    if n - 2 * k < 1:
        raise VerifyError(f"dropping {k} at each end of {n} members leaves nothing")
    order = np.argsort(z, axis=0, kind="stable")
    zs = np.take_along_axis(z, order, 0)[k:n - k]
    ws = w[order][k:n - k]
    return (ws * zs).sum(0) / ws.sum(0)


def _decodes(decode, names):
    if decode is None or isinstance(decode, str):
        return [decode or "none"] * len(names)
    if isinstance(decode, dict):
        return [decode.get(n, "none") for n in names]
    decode = list(decode)
    if len(decode) != len(names):
        raise VerifyError("give one decode per member, or one for all")
    return decode


def combine_members(members, center="mean", combine="mean", trim=DEFAULT_TRIM, weights=None, decode="none",
                    valid=None, keep_zero=False, rows=ROWS):
    """(combined z, float64, 0 where invalid; valid mask; {name: statistics}) of (name, map or path) members."""
    np = _numpy()
    members = list(members)
    names = [n for n, _ in members]
    if len(members) < 2:
        raise VerifyError("an ensemble needs at least two maps")
    if len(set(names)) != len(names):
        raise VerifyError(f"member names repeat: {sorted({n for n in names if names.count(n) > 1})}")
    bad = [n for n in names if not ens.NAME_RE.match(str(n))]
    if bad:
        raise VerifyError(f"member names are letters, digits, _ . + -: {bad}")
    if center not in CENTERS:
        raise VerifyError(f"center is one of {CENTERS}, not {center!r}")
    if combine not in COMBINES:
        raise VerifyError(f"combine is one of {COMBINES}, not {combine!r}")
    w = check_weights(weights, len(members), combine)
    k = trim_count(len(members), trim) if combine == "trimmed" else 0
    decodes = _decodes(decode, names)
    for how in decodes:
        if how not in ens.DECODES:
            raise VerifyError(f"decode is one of {ens.DECODES}, not {how!r}")
    raws, shape = [], None
    for i, (name, src) in enumerate(members):
        raw = ens._as_map(np, src)
        if shape is None:
            shape = raw.shape
        elif raw.shape != shape:
            raise VerifyError(f"member {name} ({ens._label(src, i)}) is {raw.shape}, not {shape}")
        raws.append(raw)
    ok = ens._base_valid(np, shape, valid).copy()
    for raw in raws:
        ok &= ens._predicted(np, raw, keep_zero)
    if not ok.any():
        raise VerifyError("no pixel is valid in every member map (and the mask)")
    stats = {}
    for i, ((name, src), raw, how, wt) in enumerate(zip(members, raws, decodes, w)):
        st = member_stats(ens.decode_values(raw, how)[ok], center, f"member {name}")
        st.update({"decode": how, "weight": wt, "n_px": int(ok.sum()), "source": ens._label(src, i)})
        stats[name] = st
    out = np.zeros(shape, np.float64)
    for r0 in range(0, shape[0], max(1, int(rows))):
        okb = ok[r0:r0 + rows]
        if not okb.any():
            continue
        z = np.stack([(ens.decode_values(raw[r0:r0 + rows], how)[okb].astype(np.float64) - stats[name]["center"])
                      / stats[name]["scale"] for name, raw, how in zip(names, raws, decodes)])
        block = out[r0:r0 + rows]       # a view: assigning through it fills out
        block[okb] = combine_z(z, w, k)
    return out, ok, stats


def default_provenance(out):
    return Path(out).with_suffix(".provenance.json")


def run(out, members, center="mean", combine="mean", trim=DEFAULT_TRIM, weights=None, decode="none", mask=None,
        keep_zero=False, raw_out=None, provenance_out=None, run_name="inkensemble", extra_notes=None):
    """Combine (name, path) member maps into OUT, write the provenance record, and return the result dict.
    extra_notes: more entries for the record's notes (such as where its weights came from)."""
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _numpy()
    if out is None:
        raise VerifyError("give the output map before the member maps")
    ens._check_raw_out(raw_out)
    members = [(str(n), str(p)) for n, p in members]
    prov = Path(provenance_out) if provenance_out else default_provenance(out)
    written = [Path(out), prov] + ([Path(raw_out)] if raw_out else [])
    taken = {str(Path(p).resolve()) for _, p in members} | ({str(Path(mask).resolve())} if mask else set())
    names = [str(w.resolve()) for w in written]
    if len(set(names)) != len(names) or taken & set(names):
        raise VerifyError("an output path is also an input, or two outputs share a path")
    valid = ens.valid_from(mask) if mask else None
    score, ok, stats = combine_members(members, center, combine, trim, weights, decode, valid, keep_zero)
    scaled, lo, hi = ens.affine01(score, ok)
    ens.write(out, scaled, ok)
    if raw_out:
        ens.write_raw(raw_out, score, ok)
    settings = {"center": center, "scale": "sd" if center == "mean" else "mad x 1.4826", "combine": combine,
                "trim": trim if combine == "trimmed" else None,
                "trimmed_each_end": trim_count(len(members), trim) if combine == "trimmed" else 0,
                "weights": [stats[n]["weight"] for n, _ in members], "keep_zero": bool(keep_zero),
                "mask": None if mask is None else str(mask), "sd_eps": SD_EPS}
    result = {"kind": KIND, "version": VERSION, "out": str(out), "raw_out": None if raw_out is None else str(raw_out),
              "members": [{"name": n, "path": p, **{k: v for k, v in stats[n].items() if k != "source"}}
                          for n, p in members],
              "settings": settings, "shape": list(score.shape), "valid_px": int(ok.sum()),
              "combined_z_min": lo, "combined_z_max": hi,
              "scale": "tif u = 1 + round((z - combined_z_min) / (combined_z_max - combined_z_min) * 65534); "
                       "npy u / 65535", "source": ens.SOURCE}
    inputs = [p for _, p in members] + ([str(mask)] if mask else [])
    outputs = [str(out)] + ([str(raw_out)] if raw_out else [])
    rec = provenance.build(run_name, REPO, started=started, inputs=inputs, outputs=outputs,
                           note="kit inkensemble: member maps z-scored inside the mask, then combined",
                           notes={"kind": KIND, "version": VERSION, "settings": settings,
                                  "members": result["members"], "valid_px": result["valid_px"],
                                  "combined_z_min": lo, "combined_z_max": hi, **(extra_notes or {})})
    try:
        provenance.write(rec, prov)
    except OSError as exc:
        raise VerifyError(f"cannot write {prov}: {exc}") from exc
    result["provenance"] = {"path": str(prov), "digest": rec["digest"]}
    return result


# ---------------------------------------------------------------- AutoPipeline

PLAN_KEYS = ("robust", "combine", "trim", "weights")


def check_plan(cfg, models):
    """Refusals for AutoPipeline's ink.ensemble {"method": "zscore", ...} with these planned models (a message
    naming the setting, or None)."""
    extra = [k for k in cfg if k not in ("method",) + PLAN_KEYS]
    if extra:
        return f"unknown plan setting ink.ensemble.{extra[0]}"
    models = list(models)
    bad = [m for m in models if not (isinstance(m, str) and ens.NAME_RE.match(m))]
    if bad:
        return (f"ink.ensemble method zscore names each member by its model, and kit inkensemble takes names of "
                f"letters, digits and _ . + - only: {bad}")
    twice = sorted({m for m in models if models.count(m) > 1})
    if twice:
        return f"ink.ensemble method zscore combines each planned model once: {twice} planned twice"
    if "robust" in cfg and not isinstance(cfg["robust"], bool):
        return "ink.ensemble.robust is true or false"
    combine = cfg.get("combine", "mean")
    if combine not in COMBINES:
        return f"ink.ensemble.combine is one of {COMBINES}"
    if "trim" in cfg and combine != "trimmed":
        return "ink.ensemble.trim goes with combine trimmed"
    try:
        if combine == "trimmed":
            trim_count(len(models), cfg.get("trim", DEFAULT_TRIM))
        w = cfg.get("weights")
        if w is not None:
            if not isinstance(w, dict) or sorted(w) != sorted(models):
                return "ink.ensemble.weights names every planned model once: {model: weight}"
            check_weights([w[m] for m in models], len(models), combine)
    except VerifyError as exc:
        return f"ink.ensemble: {exc}"
    return None


def plan_flags(cfg, models):
    """This command's flags for AutoPipeline's ink.ensemble setting (method zscore) and the planned models."""
    flags = []
    if cfg.get("robust"):
        flags.append("--robust")
    combine = cfg.get("combine", "mean")
    flags += ["--combine", combine]
    if combine == "trimmed":
        flags += ["--trim", repr(float(cfg.get("trim", DEFAULT_TRIM)))]
    if cfg.get("weights") is not None:
        flags += ["--weights", *[repr(float(cfg["weights"][m])) for m in models]]
    return flags


# ---------------------------------------------------------------- command line

def from_args(args):
    if args.out is not None and ens._looks_named(args.out):
        raise VerifyError(f"{args.out!r} looks like a NAME=PATH member; the output map comes first")
    if len(args.maps) < 2:
        raise VerifyError("give the output map and at least two member maps")
    members = []
    for i, spec in enumerate(args.maps):
        named = ens.parse_named(spec)
        members.append(named if named is not None else (f"map{i + 1}", spec))
    default, per = ens.parse_decode(args.decode)
    names = [n for n, _ in members]
    unknown = sorted(set(per) - set(names))
    if unknown:
        raise VerifyError(f"--decode names members that are not given: {unknown}")
    decode = {n: per.get(n, default or "none") for n in names}
    if args.trim is not None and args.combine != "trimmed":
        raise VerifyError("--trim goes with --combine trimmed")
    return run(args.out, members, "median" if args.robust else "mean", args.combine,
               DEFAULT_TRIM if args.trim is None else args.trim, args.weights, decode, args.mask, args.keep_zero,
               args.raw_out, args.provenance, args.run)


def format_result(result):
    s = result["settings"]
    how = (f"{'median and MAD' if s['center'] == 'median' else 'mean and SD'} z-scores, "
           + (f"trimmed mean dropping {s['trimmed_each_end']} at each end" if s["combine"] == "trimmed"
              else "weighted mean"))
    rows = [f"{len(result['members'])} members, {how}, inside "
            + ("the mask and " if s["mask"] else "") + "the pixels every member predicts:"]
    for m in result["members"]:
        rows.append(f"  {m['name']}: weight {m['weight']:g}, decode {m['decode']}, center {m['center']:.6f}, "
                    f"scale {m['scale']:.6f} over {m['n_px']} px")
    rows.append(f"-> {result['out']} ({result['valid_px']} valid px of {result['shape'][0]} x {result['shape'][1]}; "
                f"combined z {result['combined_z_min']:.4f} .. {result['combined_z_max']:.4f} mapped to 1..65535)")
    rows.append(f"provenance {result['provenance']['path']} (digest {result['provenance']['digest'][:16]})")
    return "\n".join(rows)
