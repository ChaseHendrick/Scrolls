"""Command line: python -m kit {prizes,doctor,plan,cost,fetch,verify,rowscore,auc,layers,provenance,compute,run}."""

import argparse
import json
import sys
from datetime import date

from . import auc, compute, ensemble, hpscore, doctor, fetch, layers, provenance, ledger, plan, prizes, rowscore, verify


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
        result = rowscore.score_files(args.forward, args.voxel_um, args.reverse)
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
                                 args.crop, args.surface_shape, args.keep_zero, args.inner)
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else auc.format_result(result))
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


def cmd_layers(args):
    try:
        result = layers.export_file(args.volume, args.out_dir, args.start, args.count, args.level, args.crop)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    window = f", rows {args.crop[0]}-{args.crop[1]}, columns {args.crop[2]}-{args.crop[3]}" if args.crop else ""
    print(f"{result['layers']} layers of {result['shape']} from layer {result['start']}{window} -> {result['out_dir']}")
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
        elif args.action == "list":
            for record in ledger.list_runs(root):
                print(f"{record['slug']:<28} {record['scroll']:<12} {record['status']:<10} ${ledger.total_cost(record):.2f}")
    except ledger.LedgerError as exc:
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
    p.add_argument("--json", action="store_true")
    p.add_argument("--slug", help="attach the result to this experiment")
    p.add_argument("--name", default="label-auc")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    p.set_defaults(func=cmd_auc)

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

    p = sub.add_parser("layers", help="export a surface-volume zarr to 00.tif, 01.tif, ... (v8in's input)")
    p.add_argument("volume", help="surface-volume zarr, e.g. from vc_render_tifxyz --zarr-output")
    p.add_argument("out_dir")
    p.add_argument("--start", type=int, default=0, help="first layer to export")
    p.add_argument("--count", type=int, help="number of layers (default: all from --start)")
    p.add_argument("--level", default="0", help="OME-Zarr level when the store is a group")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="export only this window, in full-resolution pixels")
    p.set_defaults(func=cmd_layers)

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
    p.set_defaults(func=cmd_run)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
