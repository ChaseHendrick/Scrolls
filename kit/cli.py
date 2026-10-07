"""Command line: python -m kit {prizes,doctor,plan,cost,fetch,verify,rowscore,auc,hpscore,overlap,collate,ensemble,fibertensor,gate,layers,shuffle,provenance,compute,run,surfacefix,phantom,view}."""

import argparse
import json
import sys
from pathlib import Path
from datetime import date

from . import localcost, auc, compute, ensemble, fibertensor, gate, hpscore, doctor, fetch, layers, overlap, provenance, ledger, plan, prizes, rowscore, verify, surfacefix, phantom, viewer


def cmd_prizes(args):
    snapshot = prizes.load()
    if args.json:
        print(json.dumps(snapshot, indent=2))
    else:
        today = date.fromisoformat(args.today) if args.today else None
        print(prizes.format_table(snapshot, today))
    return 0


def cmd_doctor(args):
    report, worst = doctor.format_report(doctor.run_checks(disk_path=args.disk))
    print(report)
    return 1 if worst == doctor.FAIL else 0


def cmd_plan(args):
    try:
        print(plan.first_letters(args.scroll, batch=args.batch, mac=args.mac))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def cmd_cost(args):
    total = plan.cost(args.gpu_hours, args.rate, args.cpu_hours, args.cpu_rate, args.storage)
    print(f"${total:.2f}")
    return 0


def cmd_fetch(args):
    prefix = fetch.ALIASES.get(args.prefix, args.prefix)
    try:
        objects, fetched, total = fetch.fetch_prefix(prefix, args.dest, workers=args.workers)
    except (fetch.FetchError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"{objects} objects, {total / 1e6:.1f} MB total, {fetched / 1e6:.1f} MB downloaded -> {args.dest}")
    return 0


def cmd_verify(args):
    try:
        result = verify.verify_files(args.reference, args.candidate, args.control,
                                     args.tolerance, args.max_fraction)
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else verify.format_result(result))
    return {verify.PASS: 0, verify.PASS_UNCONTROLLED: 3}.get(result["verdict"], 1)


def cmd_rowscore(args):
    try:
        result = rowscore.score_files(args.forward, args.voxel_um, args.reverse, fast_resize=args.fast_resize)
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else rowscore.format_result(result))
    return 0


def cmd_auc(args):
    try:
        result = auc.score_files(args.prediction, args.labels, args.mask, args.control, args.level,
                                 args.crop, args.surface_shape, args.keep_zero, args.inner,
                                 args.bootstrap, args.block_px, args.compare, args.seed)
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else auc.format_result(result))
    return 0


def cmd_fibertensor(args):
    try:
        if args.action == "train":
            result = fibertensor.train_files(args.volume, args.labels, args.crop, args.surface_shape, args.output,
                                             kind=args.kind, model=args.model, seed=args.seed,
                                             samples=args.samples, epochs=args.epochs, reverse=args.reverse)
        else:
            result = fibertensor.predict_files(args.model_file, args.volume, args.crop, args.output, args.reverse)
    except verify.VerifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def cmd_hpscore(args):
    try:
        result = hpscore.score_files(args.prediction, args.labels, args.mask, args.voxel_um, args.control,
                                     args.level, args.crop, args.surface_shape, args.inner)
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else hpscore.format_result(result))
    return 0


def cmd_overlap(args):
    try:
        result = overlap.overlap(args.mesh_a, args.mesh_b, args.voxel_um, args.within, args.labels_a, args.labels_b,
                                 args.level, args.draws, args.seed)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(overlap.dumps(result) if args.json else overlap.format_overlap(result))
    return 0


def cmd_collate(args):
    try:
        result = overlap.collate(args.mesh_a, args.mesh_b, args.map_a, args.map_b, args.voxel_um, tuple(args.gaps),
                                 args.top, args.control_a, args.control_b, args.box, args.draws, args.seed)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(overlap.dumps(result) if args.json else overlap.format_collate(result))
    return 0


def cmd_surfacefix(args):
    try:
        if args.action == "prepare":
            result = surfacefix.prepare(args.mesh, args.out, args.voxel_um, args.offsets, args.max_shift_um)
        else:
            result = surfacefix.correct(args.manifest, args.out, args.region_points, args.min_points,
                                        args.min_corr, args.min_gain, args.control_margin, args.max_step_vox)
    except (verify.VerifyError, OSError, ValueError) as exc:
        print(f"surfacefix: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.action == "prepare":
        print(f"candidate surfaces prepared in {args.out}; render and score them with the existing reader, "
              "then fill manifest.json before applying corrections")
    else:
        print(f"{result['status']}: corrected surface copy and region report in {args.out}; "
              "rerender and recheck this copy before using its predictions")
    return 0 if args.action == "prepare" or result["accepted_regions"] > 0 or result["status"] == "unchanged" else 1


def cmd_provenance(args):
    try:
        if args.action == "write":
            record = provenance.build(args.run, args.repo, started=args.started, inputs=args.input,
                                      models=args.model, outputs=args.output, extra_code=args.code_repo,
                                      note=args.note)
            path = provenance.write(record, args.path)
            print(f"{path}: digest {record['digest']}")
            return 0
        record = json.loads(open(args.path, encoding="utf-8").read())
        problems = provenance.verify(record, recheck_files=args.files)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    for problem in problems:
        print(f"problem: {problem}")
    if problems:
        return 1
    print(f"{args.path}: ok (digest {record['digest']}{', files unchanged' if args.files else ''})")
    return 0


def cmd_compute(args):
    records = compute.collect(args.paths)
    if not records:
        print("no provenance records found", file=sys.stderr)
        return 2
    r = compute.rows(records, args.watts)
    print(json.dumps(r, indent=2) if args.json else compute.table(r, args.watts))
    return 0


def cmd_ensemble(args):
    try:
        result = ensemble.ensemble_files(args.out, args.maps, args.method, args.weights)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['method']} of {len(result['inputs'])} maps -> {result['out']} "
              f"({result['valid_px']} valid px of {result['shape'][0]} x {result['shape'][1]})")
    return 0


def cmd_gate(args):
    work = args.work
    if work is None:
        default = Path.home() / "scrolls-work"
        work = str(default) if default.is_dir() else None
    try:
        result = gate.run(work, args.results, args.min_lead, args.min_gap)
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot read the scores: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else gate.format_result(result))
    return 1 if any(not c["match"] for c in result["checks"]) else 0


def cmd_layers(args):
    try:
        result = layers.export_file(args.volume, args.out_dir, args.start, args.count, args.level, args.crop,
                                shuffle_seed=args.shuffle)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    window = f", rows {args.crop[0]}-{args.crop[1]}, columns {args.crop[2]}-{args.crop[3]}" if args.crop else ""
    order = f", depth order shuffled (seed {args.shuffle}): {result['order']}" if args.shuffle is not None else ""
    print(f"{result['layers']} layers of {result['shape']} from layer {result['start']}{window} -> {result['out_dir']}{order}")
    return 0


def cmd_shuffle(args):
    try:
        result = layers.shuffle_file(args.volume, args.out, args.seed, args.level, args.crop)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"{result['shape'][0]} layers shuffled (seed {result['seed']}, order {result['order']}) -> {result['out']}")
    return 0


def cmd_run(args):
    root = args.root
    try:
        if args.action == "init":
            path, _ = ledger.init(args.slug, args.scroll, args.question, args.readout,
                                  root=root, villa_commit=args.villa_commit)
            print(f"created {path} (status planned, readout rule hashed)")
        elif args.action == "status":
            record = ledger.set_status(args.slug, args.status, args.note, args.announced, root=root)
            print(f"{record['slug']}: {record['status']}")
        elif args.action == "cost":
            record = ledger.add_cost(args.slug, args.usd, args.what, root=root)
            print(f"{record['slug']}: total ${ledger.total_cost(record):.2f}")
        elif args.action == "record":
            record = ledger.add_provenance(args.slug, args.command, args.file, root=root)
            print(f"{record['slug']}: recorded command and {len(args.file)} file hash(es)")
        elif args.action == "check":
            problems = ledger.check(args.slug, root=root)
            for problem in problems:
                print(f"problem: {problem}")
            if problems:
                return 1
            print(f"{args.slug}: ok")
        elif args.action == "local":
            cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
            code, item = localcost.run(args.slug, cmd, root=root, device=args.device,
                                       watts=args.watts, rate=args.rate)
            cpu = "unavailable" if item["cpu_s"] is None else f"{item['cpu_s']:.1f} s"
            print(f"{args.slug}: {item['wall_s']:.1f} s wall, {cpu} CPU, "
                  f"{item['kwh']:.4f} kWh, ${item['usd_exact']:.4f} (exit {code})", file=sys.stderr)
            return code
        elif args.action == "backfill":
            try:
                with open(args.file, encoding="utf-8") as fh:
                    items = json.load(fh)
            except (OSError, ValueError) as exc:
                raise localcost.CostError(f"cannot read backfill {args.file}: {exc}") from exc
            hours, usd = localcost.backfill(args.slug, items, root=root, rate=args.rate)
            print(f"{args.slug}: backfilled {len(items)} entries, {hours:.3f} h, ${usd:.4f} (estimated from logs)")
        elif args.action == "list":
            for record in ledger.list_runs(root):
                print(f"{record['slug']:<28} {record['scroll']:<12} {record['status']:<10} ${ledger.total_cost(record):.2f}")
    except (ledger.LedgerError, localcost.CostError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _shape(v):
    return (v[0], v[1]) if v else (384, 384)


def cmd_phantom(args):
    import numpy as np
    from .verify import VerifyError
    try:
        if args.action == "make":
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            p = phantom.make_phantom(_shape(args.shape), args.depth, args.seed, args.letter_px,
                                     ink_contrast=args.ink_contrast, ink_bump=args.ink_bump, noise=args.noise)
            np.save(out / "volume.npy", p["volume"])
            np.save(out / "ink.npy", p["ink"])
            np.save(out / "mask.npy", p["mask"])
            (out / "meta.json").write_text(json.dumps(p["meta"], indent=2) + "\n")
            print(json.dumps(p["meta"], indent=2))
        elif args.action == "stress":
            from . import auc
            rows = []
            for seed in range(args.seed, args.seed + args.n):
                p = phantom.make_phantom(_shape(args.shape), args.depth, seed, args.letter_px,
                                         ink_contrast=args.ink_contrast, ink_bump=args.ink_bump, noise=args.noise)
                fwd = phantom.surface_detector(p["volume"])
                rev = phantom.surface_detector(p["volume"][::-1])
                rows.append({"seed": seed, "auc": auc.score_array(fwd, p["ink"], p["mask"])["auc"],
                             "auc_reversed": auc.score_array(rev, p["ink"], p["mask"])["auc"]})
                if args.save_maps:
                    d = Path(args.save_maps)
                    d.mkdir(parents=True, exist_ok=True)
                    np.save(d / f"surface_{seed}.npy", fwd)
                    np.save(d / f"surface_reversed_{seed}.npy", rev)
            res = {"detector": "surface_detector", "ink_contrast": args.ink_contrast, "ink_bump": args.ink_bump,
                   "noise": args.noise, "rows": rows}
            print(json.dumps(res, indent=2))
        else:
            res = phantom.calibrate(args.n, _shape(args.shape), args.letter_px, args.quality, args.draws,
                                    args.block_px, args.seed)
            print(json.dumps(res, indent=2) if args.json else
                  f"AUC over {res['n']} phantoms: mean {res['auc_mean']}, between-phantom 95% half width "
                  f"{res['empirical_half_width']}; mean block-bootstrap half width {res['bootstrap_half_width_mean']} "
                  f"(ratio {res['ratio_bootstrap_to_empirical']}); intervals covering the mean {res['intervals_covering_mean']}")
    except VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def cmd_view(args):
    from .verify import VerifyError
    try:
        maps = []
        for item in args.maps:
            name, _, path = item.rpartition("=")
            maps.append((name or Path(path).stem, viewer.load_array(path)))
        lab = viewer.load_array(args.labels) if args.labels else None
        msk = viewer.load_array(args.mask) if args.mask else None
        page, stats = viewer.build_html(maps, lab, msk, args.title, args.max_side)
        Path(args.out).write_text(page)
        if args.png:
            img, _ = viewer.render_png(maps, lab, msk)
            Path(args.png).write_bytes(viewer.png_bytes(img))
        print(json.dumps(stats, indent=2))
    except VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m kit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prizes", help="open prizes from the dated snapshot")
    p.add_argument("--json", action="store_true")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_prizes)

    p = sub.add_parser("doctor", help="check GPU, disk, tools and villa paths")
    p.add_argument("--disk", default=".", help="path whose free space to check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("plan", help="print a First Letters run plan for an eligible scroll")
    p.add_argument("scroll", help="e.g. PHerc0826")
    p.add_argument("--batch", type=int, help="inference batch size (default 4, or 1 with --mac)")
    p.add_argument("--mac", action="store_true", help="Apple Silicon setup: VC3D.app tools, CPU or MPS inference")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("cost", help="estimate run cost in USD")
    p.add_argument("--gpu-hours", type=float, required=True)
    p.add_argument("--rate", type=float, required=True, help="USD per GPU hour")
    p.add_argument("--cpu-hours", type=float, default=0.0)
    p.add_argument("--cpu-rate", type=float, default=0.0)
    p.add_argument("--storage", type=float, default=0.0, help="flat storage or egress USD")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("fetch", help="mirror a public bucket prefix over HTTPS (no AWS CLI needed)")
    p.add_argument("prefix", help="bucket prefix, e.g. PHerc0139/segments/..., or 'w035' / 'w045' for the PHerc0139 training / held-out surface volumes")
    p.add_argument("dest", help="local directory")
    p.add_argument("--workers", type=int, default=16)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("verify", help="compare two ink maps (e.g. CPU vs MPS) with a control")
    p.add_argument("reference", help="reference map, e.g. the CPU run")
    p.add_argument("candidate", help="map to check, e.g. the MPS run")
    p.add_argument("--control", help="a map that must NOT agree, e.g. the reverse-direction output")
    p.add_argument("--tolerance", type=float, default=verify.DEFAULT_TOLERANCE, help="grey levels (0-255)")
    p.add_argument("--max-fraction", type=float, default=verify.DEFAULT_MAX_FRACTION,
                   help="largest fraction of pixels allowed beyond the tolerance")
    p.add_argument("--json", action="store_true")
    p.add_argument("--slug", help="attach the result to this experiment")
    p.add_argument("--name", default="device-agreement")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("rowscore", help="text-row periodicity triage score for ink maps (Bullo27's method)")
    p.add_argument("--fast-resize", action="store_true",
                   help="use sparse area resize (scipy); float32 rounding and near-tied FFT peaks can differ")
    p.add_argument("forward", nargs="+", help="forward-direction map(s); several are averaged, e.g. two checkpoints")
    p.add_argument("--reverse", nargs="+", default=[], help="reverse-direction map(s), averaged the same way")
    p.add_argument("--voxel-um", type=float, required=True, help="map pixel size in micrometres, e.g. 9.362")
    p.add_argument("--json", action="store_true")
    p.add_argument("--slug", help="attach the result to this experiment")
    p.add_argument("--name", default="rowscore")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    p.set_defaults(func=cmd_rowscore)

    p = sub.add_parser("auc", help="pixel AUC of an ink map against a segment's published labels")
    p.add_argument("prediction", help="ink map (.tif or .npy) on the 9 um surface grid")
    p.add_argument("--labels", required=True, help="inklabels.zarr of the segment")
    p.add_argument("--mask", required=True, help="supervision.zarr: where ink and non-ink were both labelled")
    p.add_argument("--control", help="reverse-direction map of the same surface")
    p.add_argument("--level", default=auc.DEFAULT_LEVEL, help="label pyramid level matching the 9 um grid")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="the map covers only this window of the surface")
    p.add_argument("--surface-shape", type=int, nargs=2, metavar=("H", "W"), help="full surface shape, with --crop")
    p.add_argument("--keep-zero", action="store_true", help="count pixels where the map is exactly 0")
    p.add_argument("--inner", type=int, default=0, metavar="PX",
                   help="leave out this many pixels at every edge (for maps inferred on a cropped input)")
    p.add_argument("--bootstrap", type=int, default=0, metavar="N",
                   help="block-bootstrap draws for a 95 %% interval (300 is plenty); 0 for none")
    p.add_argument("--block-px", type=int, default=auc.BLOCK_PX, help="bootstrap block side (default 107: 1 mm at 9.366 um)")
    p.add_argument("--compare", metavar="MAP", help="second map of the same surface: is the first ahead beyond sampling noise?")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.add_argument("--slug", help="attach the result to this experiment")
    p.add_argument("--name", default="label-auc")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    p.set_defaults(func=cmd_auc)

    p = sub.add_parser("fibertensor", help="fibre-orientation (structure tensor) features and a tiny CPU ink reader")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("train", help="fit on one labelled segment window")
    a.add_argument("volume", help="surface volume zarr (9 um)")
    a.add_argument("labels", help="label folder with inklabels.zarr and supervision.zarr")
    a.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"))
    a.add_argument("--surface-shape", type=int, nargs=2, metavar=("H", "W"), required=True)
    a.add_argument("--kind", choices=["fibre", "raw"], default="fibre", help="raw: brightness-only baseline")
    a.add_argument("--model", choices=["mlp", "logreg"], default="mlp")
    a.add_argument("--samples", type=int, default=60000)
    a.add_argument("--epochs", type=int, default=200)
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--reverse", action="store_true", help="reverse the depth order (control)")
    a.add_argument("-o", "--output", required=True, help="model .npz")
    a = actions.add_parser("predict", help="write an ink map for a window")
    a.add_argument("model_file", help="model .npz from train")
    a.add_argument("volume")
    a.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"))
    a.add_argument("--reverse", action="store_true", help="reverse the depth order (the control map)")
    a.add_argument("-o", "--output", required=True, help="map .tif")
    p.set_defaults(func=cmd_fibertensor)

    p = sub.add_parser("hpscore", help="letter-scale score: 48 um high-passed correlation with the labels (Scheirer)")
    p.add_argument("prediction", help="ink map (.tif or .npy) on the 9 um surface grid")
    p.add_argument("--labels", required=True, help="inklabels.zarr of the segment")
    p.add_argument("--mask", required=True, help="supervision.zarr")
    p.add_argument("--voxel-um", type=float, required=True, help="map pixel size in micrometres, e.g. 9.366")
    p.add_argument("--control", help="reverse-direction map of the same surface")
    p.add_argument("--level", default=auc.DEFAULT_LEVEL)
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"))
    p.add_argument("--surface-shape", type=int, nargs=2, metavar=("H", "W"))
    p.add_argument("--inner", type=int, default=0, metavar="PX", help="leave this many edge pixels out")
    p.add_argument("--json", action="store_true")
    p.add_argument("--slug")
    p.add_argument("--name", default="letter-scale")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    p.set_defaults(func=cmd_hpscore)

    p = sub.add_parser("overlap", help="do two segments trace the same papyrus? mesh gaps and label agreement")
    p.add_argument("mesh_a", help="tifxyz folder (x.tif, y.tif, z.tif) of segment A")
    p.add_argument("mesh_b", help="tifxyz folder of segment B, in the same volume")
    p.add_argument("--voxel-um", type=float, required=True, help="voxel size of the mesh coordinates, e.g. 9.366")
    p.add_argument("--within", type=int, default=12, help="gap in voxels that counts as the same sheet (default 12)")
    p.add_argument("--labels-a", help="folder with A's inklabels.zarr and supervision.zarr")
    p.add_argument("--labels-b", help="the same for B")
    p.add_argument("--level", default=auc.DEFAULT_LEVEL)
    p.add_argument("--draws", type=int, default=200, help="displaced matches for the label null")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_overlap)

    p = sub.add_parser("collate", help="two traces of one sheet as two copies: do their ink maps agree, against a control?")
    p.add_argument("mesh_a")
    p.add_argument("mesh_b")
    p.add_argument("map_a", help="ink map of A on A's surface grid (.tif or .npy, any resolution)")
    p.add_argument("map_b", help="ink map of B on B's surface grid")
    p.add_argument("--voxel-um", type=float, required=True)
    p.add_argument("--gaps", type=float, nargs="+", default=[0, 3, 6, 9, 12, 18, 30], help="gap bin edges in voxels")
    p.add_argument("--top", type=float, default=0.2, help="a 'strong spot' is in this top fraction of its map")
    p.add_argument("--control-a", help="control map of A (e.g. high-passed raw CT or the reverse-depth map)")
    p.add_argument("--control-b", help="control map of B")
    p.add_argument("--box", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="only A's points in this window of map A (one candidate)")
    p.add_argument("--draws", type=int, default=50, help="displaced matches for the null")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_collate)

    p = sub.add_parser("surfacefix", help="experimental region flags and bounded, controlled surface corrections")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("prepare", help="write offset surface copies for the official render and reader pipeline")
    a.add_argument("mesh", help="source tifxyz folder; kept unchanged")
    a.add_argument("out", help="new local output folder, e.g. work/surfacefix-candidates")
    a.add_argument("--voxel-um", type=float, required=True)
    a.add_argument("--offsets", type=float, nargs="+", default=[-1, 1], help="candidate normal offsets in voxels")
    a.add_argument("--max-shift-um", type=float, default=50.0)
    a.add_argument("--json", action="store_true")
    a = actions.add_parser("apply", help="select, independently check and apply regional offsets to a new surface copy")
    a.add_argument("manifest", help="prepared manifest filled with matching forward, reverse and shuffle maps")
    a.add_argument("out", help="new local output folder, e.g. work/surfacefix-output")
    a.add_argument("--region-points", type=int, default=8, help="native mesh-grid side per scoring region")
    a.add_argument("--min-points", type=int, default=24, help="minimum common points in each scoring subset")
    a.add_argument("--min-corr", type=float, default=0.5)
    a.add_argument("--min-gain", type=float, default=0.1)
    a.add_argument("--control-margin", type=float, default=0.1)
    a.add_argument("--max-step-vox", type=float, default=1.0, help="maximum offset jump between adjacent mesh vertices")
    a.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_surfacefix)

    p = sub.add_parser("provenance", help="who ran what, when, from which inputs: a record and one digest")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("write", help="hash models, inputs and outputs into a provenance record")
    a.add_argument("path", help="where to write the JSON record")
    a.add_argument("--run", required=True, help="run name")
    a.add_argument("--repo", default=".", help="the Scrolls checkout (operator and commit come from it)")
    a.add_argument("--code-repo", action="append", default=[], help="another git repo used, e.g. villa")
    a.add_argument("--model", action="append", default=[], help="checkpoint file or directory; repeatable")
    a.add_argument("--input", action="append", default=[], help="input file or store; repeatable")
    a.add_argument("--output", action="append", default=[], help="output file; repeatable")
    a.add_argument("--started", help="UTC start time, e.g. 2026-10-07T08:00:00Z")
    a.add_argument("--note")
    a = actions.add_parser("check", help="recompute the digest; --files also rehashes every file")
    a.add_argument("path")
    a.add_argument("--files", action="store_true")
    p.set_defaults(func=cmd_provenance)

    p = sub.add_parser("compute", help="machine time per run, from provenance records (GENChase-style ledger)")
    p.add_argument("paths", nargs="+", help="provenance JSON files or directories to search")
    p.add_argument("--watts", type=float, help="assumed average power draw, for a Wh estimate")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_compute)

    p = sub.add_parser("ensemble", help="average several ink maps of one surface (mean, or rank mean across models)")
    p.add_argument("out", help="output map, .tif (uint16) or .npy (float32)")
    p.add_argument("maps", nargs="+", help="input maps on the same grid (.tif or .npy)")
    p.add_argument("--method", choices=ensemble.METHODS, default="mean",
                   help="mean: same model (seeds, checkpoints, z windows); rank: different models")
    p.add_argument("--weights", type=float, nargs="+", help="one weight per map (default equal)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ensemble)

    p = sub.add_parser("gate", help="Gate A: rank readers on PHerc0841's three crops by the roadmap's rule")
    p.add_argument("work", nargs="?", help="Mac work directory with <segment>/results/auc_*.json (default ~/scrolls-work if present)")
    p.add_argument("--results", default=str(gate.RESULTS), help="committed scores (docs/results.json)")
    p.add_argument("--min-lead", type=float, default=gate.MIN_LEAD, help="mean AUC lead that counts as a win")
    p.add_argument("--min-gap", type=float, default=gate.MIN_GAP, help="forward minus reverse AUC needed on every crop")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("layers", help="export a surface-volume zarr to 00.tif, 01.tif, ... (v8in's input)")
    p.add_argument("volume", help="surface-volume zarr, e.g. from vc_render_tifxyz --zarr-output")
    p.add_argument("out_dir")
    p.add_argument("--start", type=int, default=0, help="first layer to export")
    p.add_argument("--count", type=int, help="number of layers (default: all from --start)")
    p.add_argument("--level", default="0", help="OME-Zarr level when the store is a group")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="export only this window, in full-resolution pixels")
    p.add_argument("--shuffle", type=int, metavar="SEED", help="write the layers in a fixed random order (depth-shuffle control)")
    p.set_defaults(func=cmd_layers)

    p = sub.add_parser("shuffle", help="depth-shuffle control: copy a surface volume with its layers in a fixed random order")
    p.add_argument("volume", help="surface-volume zarr")
    p.add_argument("out", help="new zarr to write")
    p.add_argument("--seed", type=int, default=20261007)
    p.add_argument("--level", default="0")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"))
    p.set_defaults(func=cmd_shuffle)

    p = sub.add_parser("phantom", help="synthetic carbon-ink phantoms with known truth: make, stress-test a detector, calibrate AUC noise")
    p.add_argument("action", choices=["make", "stress", "calibrate"])
    p.add_argument("out", nargs="?", help="make: output folder (volume.npy, ink.npy, mask.npy, meta.json)")
    p.add_argument("--shape", type=int, nargs=2, metavar=("H", "W"))
    p.add_argument("--depth", type=int, default=26)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--n", type=int, default=8, help="stress, calibrate: number of phantoms")
    p.add_argument("--letter-px", type=int, default=64)
    p.add_argument("--ink-contrast", type=float, default=0.25)
    p.add_argument("--ink-bump", type=float, default=0.6)
    p.add_argument("--noise", type=float, default=1.0)
    p.add_argument("--quality", type=float, default=1.0, help="calibrate: simulated reader signal to noise")
    p.add_argument("--draws", type=int, default=200)
    p.add_argument("--block-px", type=int, default=107)
    p.add_argument("--save-maps", help="stress: folder for the detector maps (.npy)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_phantom)

    p = sub.add_parser("view", help="one static HTML page overlaying several ink maps, their disagreement and the labels")
    p.add_argument("out", help="output .html")
    p.add_argument("maps", nargs="+", help="NAME=PATH (.npy or .tif), same grid")
    p.add_argument("--labels", help="ink labels on the maps' grid (.npy or .tif)")
    p.add_argument("--mask", help="supervision mask on the maps' grid")
    p.add_argument("--title", default="Ink map viewer")
    p.add_argument("--max-side", type=int, default=viewer.MAX_SIDE)
    p.add_argument("--png", help="also write the panels side by side as a PNG")
    p.set_defaults(func=cmd_view)

    p = sub.add_parser("run", help="local experiment ledger (experiments/, gitignored)")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("init")
    a.add_argument("slug")
    a.add_argument("--scroll", required=True)
    a.add_argument("--question", required=True)
    a.add_argument("--readout", required=True, help="what will count as ink, written before looking")
    a.add_argument("--villa-commit")
    a = actions.add_parser("status")
    a.add_argument("slug")
    a.add_argument("status", choices=ledger.STATUSES)
    a.add_argument("--note", default="")
    a.add_argument("--announced", action="store_true", help="the prize result was officially announced")
    a = actions.add_parser("cost")
    a.add_argument("slug")
    a.add_argument("--usd", type=float, required=True)
    a.add_argument("--what", required=True)
    a = actions.add_parser("record", help="store a command line and SHA-256 of its files")
    a.add_argument("slug")
    a.add_argument("--command", required=True)
    a.add_argument("--file", action="append", default=[], help="checkpoint or output to hash; repeatable")
    a = actions.add_parser("check")
    a.add_argument("slug")
    actions.add_parser("list")
    a = actions.add_parser("local", help="run a local command and log wall time, CPU time and electricity cost")
    a.add_argument("slug")
    a.add_argument("--device", choices=sorted(localcost.DEVICE_WATTS), help="average-watts class (default: config or platform)")
    a.add_argument("--watts", type=float, help="override average watts")
    a.add_argument("--rate", type=float, help="USD per kWh (default: env var or local config)")
    a.add_argument("cmd", nargs="*", help="put the command after --")
    a = actions.add_parser("backfill", help="add estimated local-run costs from a JSON list of logged durations")
    a.add_argument("slug")
    a.add_argument("--file", required=True)
    a.add_argument("--rate", type=float)
    p.set_defaults(func=cmd_run)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Python 3.10 argparse mishandles a trailing nargs="*" after wrapper options.
    # Parse the wrapper separately, leaving every child flag and literal intact.
    if argv[:1] == ["run"] and "--" in argv:
        split = argv.index("--")
        args = parser.parse_args(argv[:split])
        if args.action == "local":
            args.cmd.extend(argv[split + 1:])
        else:
            args = parser.parse_args(argv)
    else:
        args = parser.parse_args(argv)
    return args.func(args)
