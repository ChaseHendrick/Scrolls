"""The ink model zoo: every openly licensed ink model Ink Lens can compare, with its pins, its scale and what it saw.

One row per model. A row says how the model runs (its family), where its weights come from (repository, revision,
file, size and SHA-256; a file that does not match is refused), the scale and depth it reads, the depth orders it can
run, its output (a 2D map, a 3D volume in the render's layers, or a 3D volume in the scan's own voxels) and, per scroll,
whether its training labels came from that scroll. The rows for the eight ink-sdk profiles carry the same pins as
ink-sdk's TOML profiles (LimeGS/ink-sdk at INK_SDK_COMMIT, MIT); tests/test_inkcompare.py checks them against an
installed ink-sdk.

Families:
  villa9      a 9 um hybrid 3D/2D checkpoint in ink_9um's format, run by villa's own flat ink inference (engine.py);
              17 layers, both depth orders, patch size from the checkpoint's own config.
  hecate      Hecate 2.4 or 9.6 um, run by the released hecate.py through ink-sdk; a 2D map in both depth orders, and a
              3D volume in the render's layers.
  canonical   the canonical 2 um ResNet-152 model, run through ink-sdk; forward only (the profile's only order).
  ct3d        a 3D model that reads the scan itself, not a render. Its volume is read onto the segment's surface by
              project3d.py, and its control is the sheet moved two pitches out and in (a 3D model has no depth order).

Exposure, per scroll: "trained" (its training labels include that scroll), "likely" (the best public evidence says
its training reached that scroll, but no training record confirms it), "selected" (not trained on it, but its author
chose the recipe while looking at it), "held_out" (its stated training data leave it out), "unknown" (nothing
published says). Each entry names its source. A score on a "trained" scroll shows the pipeline runs, not that the
model generalises.

  python3 zoo.py list [--json]            every model, its family, scale, orders, output and exposure
  python3 zoo.py show MODEL               one row in full
"""

from __future__ import annotations

import json
import sys

INK_SDK_REPO = "https://github.com/LimeGS/ink-sdk"
INK_SDK_COMMIT = "1dbfac2178958ca4bca7469582477963d4d08ecf"
VILLA_COMMIT_SDK = "3ea17f54a9b3d5fd1aaf73e1d2c8386dbaa9f30e"   # the villa revision ink-sdk's profiles name

FAMILIES = ("villa9", "hecate", "canonical", "ct3d")
OUTPUTS = ("2d", "3d-render", "3d-scan")
EXPOSURES = ("trained", "likely", "selected", "held_out", "unknown")

# Sources the exposure entries cite (public pages; dates are when they were read).
SRC = {
    "w045": "https://github.com/ChaseHendrick/Scrolls/blob/main/docs/logs/2026-10-08-w045-not-held-out.md",
    "exposure-log": "https://github.com/ChaseHendrick/Scrolls/blob/main/docs/logs/2026-10-16-reader-exposure.md",
    "d9v2-test": "https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search",
    "reader-v3-card": "https://huggingface.co/domenicor046/reader-v3",
    "ink_9um-card": "https://huggingface.co/scrollprize/ink_9um",
    "dense-card": "https://huggingface.co/Nieuwlaar/ink9um-dense-native",
    "hecate-card": "https://huggingface.co/scrollprize/hecate",
    "canonical-card": "https://huggingface.co/scrollprize/ink_canonical_2um",
    "dino-card": "https://huggingface.co/scrollprize/ink_3d_dino_guided",
    "gambiarra-card": "https://huggingface.co/scrollprize/ink_paris4_3d_4.8um_gambiarra",
}

_INK9_TRAIN = {"PHerc0139": ("trained", "its labels include PHerc0139, among them w045's 2.4 um render", "w045"),
               "PHerc0841": ("held_out", "its label dataset has no PHerc0841 segment", "ink_9um-card")}


def _hf(repo, revision, path, sha256, size):
    return {"kind": "hf", "repo": repo, "revision": revision, "path": path, "sha256": sha256, "bytes": size,
            "url": f"https://huggingface.co/{repo}/resolve/{revision}/{path}"}


MODELS = {
    # ---------------------------------------------------------------- 9 um, villa's flat inference
    "ink_9um-s42": {
        "title": "ink_9um seed 42, step 75,000", "by": "Vesuvius Challenge", "family": "villa9",
        "sdk_profile": "ink_9um@scrollprize-seed42-step75000",
        "weights": _hf("scrollprize/ink_9um", "7109667e2607db1b90c37c8b09cb876ea7fe7bb1",
                       "hybrid_3d2d-seed42/step-075000.pth",
                       "e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab", 138360039),
        "license": "MIT", "scale_um": 9.6, "tolerance_um": 0.5, "depth": 17, "orders": ("forward", "reverse"),
        "outputs": ("2d",), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": dict(_INK9_TRAIN)},
    "ink_9um-s43": {
        "title": "ink_9um seed 43, step 75,000", "by": "Vesuvius Challenge", "family": "villa9",
        "sdk_profile": "ink_9um@scrollprize-seed43-step75000",
        "weights": _hf("scrollprize/ink_9um", "7109667e2607db1b90c37c8b09cb876ea7fe7bb1",
                       "hybrid_3d2d-seed43/step-075000.pth",
                       "2aeaa85a35ef28d7bc7bf3e848c4a6a91385e9132710927fdba41133c4ecb28f", 138360231),
        "license": "MIT", "scale_um": 9.6, "tolerance_um": 0.5, "depth": 17, "orders": ("forward", "reverse"),
        "outputs": ("2d",), "no_ink_floor": 0.25, "floor_source": "model card (ink-sdk profile)",
        "exposure": dict(_INK9_TRAIN)},
    "reader-v2": {
        "title": "Reader v2", "by": "Domenico Russo", "family": "villa9",
        "sdk_profile": "ink_9um@reader-v2-step040000",
        "weights": _hf("domenicor046/reader-v2", "72633d8aa6d40e9e737ccea4c9928fbc624dab45",
                       "reader-v2-step040000.pth",
                       "654ec5acec2b6c4788d9cb326e2f0b8c2c730584949a934ef775db7f6ab5d3a6", 138382373),
        "license": "MIT", "scale_um": 9.6, "tolerance_um": 0.5, "depth": 17, "orders": ("forward", "reverse"),
        "outputs": ("2d",), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("trained", "an ink_9um fine-tune, also trained on w045", "exposure-log"),
                     "PHerc0841": ("held_out", "not in its training data or ink_9um's", "exposure-log")}},
    "reader-v3": {
        "title": "Reader V3", "by": "Domenico Russo", "family": "villa9",
        "sdk_profile": "ink_9um@reader-v3",
        "weights": _hf("domenicor046/reader-v3", "aee1d64bced4eb35546348f3d276b9e2a0b99c46", "reader-v3.pth",
                       "ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a", 138379659),
        "license": "MIT", "scale_um": 9.362, "tolerance_um": 0.75, "depth": 17, "orders": ("forward", "reverse"),
        "outputs": ("2d",), "no_ink_floor": 0.5, "floor_source": "its author (label smoothing 0.5), per ink-sdk",
        "exposure": {"PHerc0139": ("trained", "continues Reader v2; trained on w045 and its 2.4 um render",
                                   "reader-v3-card"),
                     "PHerc0841": ("selected", "not trained on it, but its author benchmarked PHerc0841 while "
                                   "choosing the recipe", "reader-v3-card")}},
    "dense-native": {
        "title": "dense_native, step 16,000", "by": "Erwin Nieuwlaar", "family": "villa9",
        "sdk_profile": "ink_9um@dense-native-step016000",
        # Published as bare safetensors + training config; both are pinned and the state dict is loaded from them
        # directly (ink-sdk rebuilds a .pth whose bytes depend on the torch version; the tensors do not).
        "weights": {"kind": "hf-rebuild", "repo": "Nieuwlaar/ink9um-dense-native",
                    "revision": "b894a0493ab2291cc8dc3247020c0d7cb0967a58", "step": 16000,
                    "files": {"weights": ("weights/dense_native_016000.safetensors",
                                          "d3d95dc41dcb24ed76b84b5e12ca5dae25d7fb34edf1dfbb93e0186f91e6fc6d",
                                          272767904),
                              "config": ("training/configs/train_dense_native.json",
                                         "5d8459030b36cd3980a03610c684365a7407d497173eff433efdb37f75840c86",
                                         11823)},
                    "sha256": "c08d7c7640b4aa270e74ea45e7559d6248e312bca01d16a63992295b674b58c6",
                    "bytes": 272890911, "sha256_note": "ink-sdk's rebuilt .pth under torch 2.10; not checked here"},
        "license": "MIT", "scale_um": 9.362, "tolerance_um": 0.75, "depth": 17, "orders": ("forward", "reverse"),
        "outputs": ("2d",), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("trained", "dense pseudo-labels on PHerc0139 native scans, from ink_9um",
                                   "dense-card"),
                     "PHerc0841": ("unknown", "its card does not list PHerc0841", "dense-card")}},
    "d9v2": {
        "title": "d9v2", "by": "TAUIL-Abd-Elilah", "family": "villa9", "sdk_profile": None,
        "weights": {"kind": "url", "url": "https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search/"
                    "releases/download/v1.0/d9v2_ft-012000.pth", "path": "d9v2_ft-012000.pth",
                    "sha256": "50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966", "bytes": None},
        "license": "MIT", "scale_um": 9.6, "tolerance_um": 0.5, "depth": 17, "orders": ("forward", "reverse"),
        "outputs": ("2d",), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("trained", "an ink_9um fine-tune; inherits its w045 training", "exposure-log"),
                     "PHerc0841": ("held_out", "PHerc0841 w00, ag896, ag405 are its reader/test.txt", "d9v2-test")}},
    # ---------------------------------------------------------------- Hecate, through ink-sdk
    "hecate-2.4": {
        "title": "Hecate 2.4 um", "by": "Vesuvius Challenge", "family": "hecate", "sdk_profile": "hecate@2.4um",
        "weights": _hf("scrollprize/hecate", "9cb86e500e944b11a06a7020403cde5dffb5bcb2", "hecate_2.4um.pth",
                       "fa2de3827ebd247ff2d33df1b6f899ea79d5269036cf16765997c62f0e9988c7", 522656918),
        "license": "MIT", "scale_um": 2.4, "tolerance_um": 0.048, "depth": 64, "orders": ("forward", "reverse"),
        "outputs": ("2d", "3d-render"), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("trained", "its ink dataset includes PHerc0139; the published split puts 86.8 % "
                                   "of w045's supervised pixels under training patches", "exposure-log"),
                     "PHerc0841": ("likely", "its own split keeps PHerc0841 for validation, but it starts from "
                                   "canonical 2 um weights whose trainer lists w00, ag896 and ag405", "exposure-log")}},
    "hecate-9.6": {
        "title": "Hecate 9.6 um", "by": "Vesuvius Challenge", "family": "hecate", "sdk_profile": "hecate@9.6um",
        "weights": _hf("scrollprize/hecate", "9cb86e500e944b11a06a7020403cde5dffb5bcb2", "hecate_9.6um.pth",
                       "809f4f10f7cb7afa19b4bee0f7d2ab31edd7e11b664f9f210cc9c17f22fcfe5d", 522576086),
        "license": "MIT", "scale_um": 9.6, "tolerance_um": 0.192, "depth": 16, "orders": ("forward", "reverse"),
        "outputs": ("2d", "3d-render"), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("trained", "its targets came from Hecate 2.4 um, which trained on PHerc0139",
                                   "exposure-log"),
                     "PHerc0841": ("likely", "its targets came from Hecate 2.4 um, which is likely not held out on "
                                   "PHerc0841", "exposure-log")}},
    # ---------------------------------------------------------------- canonical 2 um, through ink-sdk
    "canonical-2um": {
        "title": "canonical 2 um (ResNet-152, 3D decoder)", "by": "Vesuvius Challenge", "family": "canonical",
        "sdk_profile": "canonical_2um@r152-3ddec-v2-l5-epoch13",
        "weights": _hf("scrollprize/ink_canonical_2um", "075855bc69317ef6febf39a0d9d687b27d2b7c29",
                       "r152_3ddec_v2_l5_epoch13.ckpt",
                       "36dd0de84b7b7aa6590184192c7415466cd8a1ba7c1e59f42c6373846373c3e0", 1549556213),
        "license": "MIT", "scale_um": 2.399, "tolerance_um": 0.05, "depth": 62, "orders": ("forward",),
        "outputs": ("2d",), "no_ink_floor": 0.0, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("likely", "its committed trainer lists w045's 2.4 um render as training",
                                   "exposure-log"),
                     "PHerc0841": ("likely", "its committed trainer lists w00, ag896 and ag405 as training; that the "
                                   "released run used that list is not confirmed", "exposure-log")}},
    # ---------------------------------------------------------------- 3D in the scan's own voxels
    "gambiarra-3d": {
        "title": "Paris 4 3D ink, 4.8 um (gambiarra)", "by": "Vesuvius Challenge", "family": "ct3d",
        "sdk_profile": None, "engine": "gambiarra",
        "weights": _hf("scrollprize/ink_paris4_3d_4.8um_gambiarra", "4c7119858d4390747e14ddfea6cedcebe65e0530",
                       "model.safetensors",
                       "a3986efb473364251af075bbcfa1a982a21a08106d7a5d48b9e954dfeca1a433", 98016588),
        "code": {"repo": "https://github.com/ScrollPrize/villa", "branch": "ink-paris4-3d-gambiarra",
                 "commit": "c9ca2dc52a7a47ba0df2bfef377639e4b96f16a1",
                 "path": "vesuvius/src/vesuvius/ink_detection/paris4_3d_gambiarra"},
        "license": "MIT", "scale_um": 2.4, "tolerance_um": 0.048, "out_um": 4.8, "depth": None,
        "orders": ("forward",), "outputs": ("3d-scan",), "no_ink_floor": None,
        "floor_source": "no threshold supplied (its card)",
        "exposure": {"PHerc0139": ("held_out", "trained on PHercParis4 scribbles only; its self-supervised backbone "
                                               "(dinovol_v2_ps8_with_paris4_352500) saw PHerc0139's CT, without labels",
                                   "gambiarra-card"),
                     "PHerc0841": ("held_out", "trained on PHercParis4 scribbles only; its backbone's pretraining "
                                               "volumes do not include PHerc0841", "gambiarra-card")}},
    "dino-guided-3d": {
        "title": "Paris 4 volumetric 3D ink (DINO-guided, self-distilled)", "by": "Vesuvius Challenge",
        "family": "ct3d", "sdk_profile": None, "engine": "villa-full3d",
        "weights": _hf("scrollprize/ink_3d_dino_guided", "73a79525466037432191284dfa237baf830c49ec",
                       "ckpt_78k_fullsup.pth",
                       "5a148c2c1bb730bfa683f2b3e3cdfc2000424003605e42300b527ff90118b303", 1703138075),
        "license": "MIT", "scale_um": 2.4, "tolerance_um": 0.048, "out_um": 2.4, "depth": None,
        "orders": ("forward",), "outputs": ("3d-scan",), "no_ink_floor": None, "floor_source": "not declared",
        "exposure": {"PHerc0139": ("trained", "its stage-1 teacher trained on labels of eight scrolls including "
                                   "PHerc0139", "dino-card"),
                     "PHerc0841": ("trained", "its stage-1 teacher trained on labels of eight scrolls including "
                                   "PHerc0841", "dino-card")}},
}

# Models a private copy may add (register()); a public Space ships only the rows above.
_EXTRA = {}


class ZooError(ValueError):
    """A model or request the zoo refuses; the message says why."""


def register(name, spec):
    """Add a model at run time (for example a private copy's own weights). It must pass check()."""
    if name in MODELS or name in _EXTRA:
        raise ZooError(f"model {name!r} already exists")
    check(name, spec)
    _EXTRA[name] = dict(spec)


def models():
    out = dict(MODELS)
    out.update(_EXTRA)
    return out


def get(name):
    m = models()
    if name not in m:
        raise ZooError(f"unknown model {name!r}; known: {', '.join(sorted(m))}")
    return m[name]


def check(name, spec):
    """Refuse a row that cannot be run or compared fairly."""
    need = ("title", "by", "family", "weights", "license", "scale_um", "orders", "outputs", "exposure")
    miss = [k for k in need if k not in spec]
    if miss:
        raise ZooError(f"{name}: missing {', '.join(miss)}")
    if spec["family"] not in FAMILIES:
        raise ZooError(f"{name}: family {spec['family']!r} is not one of {FAMILIES}")
    if not set(spec["orders"]) <= {"forward", "reverse"} or not spec["orders"]:
        raise ZooError(f"{name}: orders must be forward and/or reverse")
    if not set(spec["outputs"]) <= set(OUTPUTS) or not spec["outputs"]:
        raise ZooError(f"{name}: outputs must come from {OUTPUTS}")
    w = spec["weights"]
    sha = w.get("sha256") if w.get("kind") != "hf-rebuild" else None
    files = [sha] if sha is not None else [f[1] for f in w.get("files", {}).values()]
    for s in files:
        if not (isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)):
            raise ZooError(f"{name}: every weight file needs a 64-hex SHA-256 pin")
    for scroll, entry in spec["exposure"].items():
        if len(entry) != 3 or entry[0] not in EXPOSURES:
            raise ZooError(f"{name}: exposure for {scroll} must be (one of {EXPOSURES}, why, source)")
    if spec["family"] == "ct3d" and "engine" not in spec:
        raise ZooError(f"{name}: a ct3d model names its engine")
    return True


def exposure(name, scroll):
    """(status, why, source URL) for one model on one scroll; unknown when nothing is recorded."""
    entry = get(name)["exposure"].get(scroll)
    if entry is None:
        return ("unknown", "nothing published says whether its training saw this scroll", None)
    status, why, src = entry
    return (status, why, SRC.get(src, src))


def control_of(name):
    """The control a model's maps are judged against: reversed depth for a model that reads depth order, the sheet
    moved two pitches for a scan-space 3D model, none for a forward-only render model."""
    spec = get(name)
    if spec["family"] == "ct3d":
        return "moved-sheet"
    return "reverse-depth" if "reverse" in spec["orders"] else "none"


def scale_plan(source_um, name):
    """How a source of source_um reaches the model: ("native", 1), ("pool", k) for a k x k x k mean pool, or a
    ZooError (never a stretch). ink-sdk's rule (prepare.plan_scale): only a 9 um model or Hecate, reading a scale
    above 5 um from a source within 0.15 of 2.4 um, pools, by round(target / source); canonical never pools."""
    spec = get(name)
    target, tol = float(spec["scale_um"]), float(spec.get("tolerance_um") or 0.0)
    source = float(source_um)
    if abs(source - target) <= tol:
        return ("native", 1)
    if target > 5.0 and spec["family"] in ("villa9", "hecate") and abs(source - 2.4) <= 0.15:
        k = int(round(target / source))
        if k >= 2 and abs(source * k - target) <= tol:
            return ("pool", k)
    raise ZooError(f"{name} reads {target:g} um (within {tol:g}); a {source:g} um source neither matches nor "
                   "pools to it by ink-sdk's scale rule, and Ink Lens does not stretch")


def describe(name):
    spec = get(name)
    out = {k: v for k, v in spec.items() if k != "exposure"}
    out["name"] = name
    out["control"] = control_of(name)
    out["exposure"] = {s: dict(zip(("status", "why", "source"), exposure(name, s))) for s in spec["exposure"]}
    return out


def listing():
    return [describe(n) for n in models()]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="The ink model zoo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("model")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "show":
            print(json.dumps(describe(a.model), indent=1, default=list))
        elif a.json:
            print(json.dumps(listing(), indent=1, default=list))
        else:
            for d in listing():
                exp = ", ".join(f"{s} {e['status']}" for s, e in d["exposure"].items())
                print(f"{d['name']:15} {d['family']:9} {d['scale_um']:>6g} um  {'+'.join(d['orders']):15} "
                      f"{'+'.join(d['outputs']):12} {exp}")
    except ZooError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
