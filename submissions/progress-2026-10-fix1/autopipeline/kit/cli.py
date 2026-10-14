"""Command line: python -m kit {prizes,doctor,vc3d,snap,meshqa,autopipeline,surfacepred,surfbench,switchfix,labelxfer,canvasorient,fetch,verify,auc,overlap,collate,provenance,ensemble,layers,shuffle,run}."""

import argparse
import json
import sys
from pathlib import Path
from datetime import date

from . import auc, compute, ensemble, fibertensor, gate, hpscore, doctor, fetch, layers, overlap, provenance, ledger, plan, prizes, rowscore, verify, surfacefix, phantom, viewer


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


def cmd_auc(args):
    try:
        result = auc.score_files(args.prediction, args.labels, args.mask, args.control, args.level,
                                 args.crop, args.surface_shape, args.keep_zero, args.inner,
                                 args.bootstrap, args.block_px, args.compare, args.seed,
                                 exclude=args.exclude, exclude_margin=args.exclude_margin, offset=args.label_offset)
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else auc.format_result(result))
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


def cmd_ensemble(args):
    try:
        result = ensemble.from_args(args)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else ensemble.format_result(result))
    return 0


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
        elif args.action == "list":
            for record in ledger.list_runs(root):
                print(f"{record['slug']:<28} {record['scroll']:<12} {record['status']:<10} ${ledger.total_cost(record):.2f}")
    except ledger.LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _shape(v):
    return (v[0], v[1]) if v else (384, 384)


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

    p = sub.add_parser("vc3d", help="headless VC3D: find, run and self-test the tools; agent tools over MCP "
                                     "(mcp) or a shell (tools, call)")
    __import__("kit.vc3d", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.vc3d", fromlist=["x"]).cmd_vc3d(a))

    p = sub.add_parser("snap", help="snap a tifxyz mesh along its normals onto the nearest predicted sheet (or the CT sheet midline), regularised")
    __import__("kit.snap", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.snap", fromlist=["x"]).cmd_snap(a))

    p = sub.add_parser("meshqa", help="mesh and prediction checks: VC3D-exact tifxyz validity and bbox, winding audit, garbage prediction cubes")
    __import__("kit.meshqa", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.meshqa", fromlist=["x"]).cmd_meshqa(a))

    p = sub.add_parser("autopipeline", aliases=["autopipe"],
                       help="AutoPipeline, the automatic pipeline on one released scan: axis, seeds, trace, checks, "
                            "flatten, render, ink, score (autopipe: its earlier name)")
    __import__("kit.autopipe", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.autopipe", fromlist=["x"]).cmd_autopipe(a))

    p = sub.add_parser("surfacepred", help="surface prediction for scans without one: patch plan, level, packaging "
                                           "for VC3D, Dice, normal-grid and seating checks against published data")
    __import__("kit.surfacepred", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.surfacepred", fromlist=["x"]).cmd_surfacepred(a))

    p = sub.add_parser("surfbench", help="geometry benchmark: score a traced tifxyz against the PHerc0139 hand windings, "
                                         "with controls that must be able to fail")
    __import__("kit.surfbench", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.surfbench", fromlist=["x"]).cmd_surfbench(a))

    p = sub.add_parser("switchfix", help="flag sheet switches in a traced tifxyz from the surface prediction alone and "
                                         "cut the trace back to its seed's winding (no references)")
    __import__("kit.switchfix", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.switchfix", fromlist=["x"]).cmd_switchfix(a))

    p = sub.add_parser("labelxfer", help="carry a published segment's ink labels onto a traced surface's render canvas "
                                         "by 3D proximity, check the carrying, and score maps on the carried labels")
    __import__("kit.labelxfer", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.labelxfer", fromlist=["x"]).cmd_labelxfer(a))
    p = sub.add_parser("canvasorient", help="turn a surface's render canvas into the published layout (+z down the "
                                            "rows) before ink detection, and the maps back; self-check")
    __import__("kit.canvasorient", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.canvasorient", fromlist=["x"]).cmd_canvasorient(a))
    p = sub.add_parser("fetch", help="mirror a public bucket prefix over HTTPS (no AWS CLI needed)")
    p.add_argument("prefix", help="bucket prefix, e.g. PHerc0139/segments/..., or 'w035' / 'w045' for the PHerc0139 surface volumes (w035: an ink_9um training segment; w045: unseen by v8in, but ink_9um trained on its 2.4 um render)")
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
    p.add_argument("--exclude", type=int, nargs=4, action="append", metavar=("Y0", "Y1", "X0", "X1"),
                   help="remove this box of the surface grid (the frame of --crop) from the supervision mask for every "
                        "map scored; repeatable")
    p.add_argument("--exclude-margin", type=int, default=0, metavar="PX",
                   help="grow every --exclude box by this many pixels on each side (clipped to the surface)")
    p.add_argument("--label-offset", type=int, nargs=2, metavar=("DY", "DX"),
                   help="move the labels by (dy, dx) surface pixels before scoring: label[y, x] = stretched[y - dy, "
                        "x - dx]; the vacated edge leaves the mask")
    p.add_argument("--json", action="store_true")
    p.add_argument("--slug", help="attach the result to this experiment")
    p.add_argument("--name", default="label-auc")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    p.set_defaults(func=cmd_auc)

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

    p = sub.add_parser("ensemble", help="combine several ink maps of one surface (mean, rank mean, or Nieuwlaar's z-score mean across models)")
    p.add_argument("out", nargs="?", help="output map, .tif (uint16, valid 1..65535) or .npy (float32); "
                   "zscore may leave it out to save only --stats-out")
    p.add_argument("maps", nargs="*", help="input maps on the same grid (.tif, .png or .npy); for zscore NAME=PATH, "
                   "one per model, summed in this order")
    p.add_argument("--method", choices=ensemble.METHODS, default="mean",
                   help="mean: same model (seeds, checkpoints, z windows); rank: different models; zscore: each "
                        "model's pooled mean and SD, then the mean z-score (scaled min..max to the output, never clipped)")
    p.add_argument("--weights", type=float, nargs="+", help="one weight per map (default equal; not for zscore)")
    p.add_argument("--decode", action="append", metavar="[NAME=]ls|none",
                   help="ls: label-smoothed villa maps, uint8 v -> clip((v-64)/128,0,1), else clip((p-0.25)/0.5,0,1); "
                        "none (default): uint8 v/255, uint16 v/65535, floats as they are for zscore (for mean and rank a float map above 1 is still divided by 255 or 65535). Repeat NAME=... for one zscore model")
    p.add_argument("--valid-from", metavar="SURFACE.zarr",
                   help="also leave out pixels where the surface volume is 0 in any layer (or a mask map is 0)")
    p.add_argument("--keep-zero", action="store_true",
                   help="count raw 0 as a prediction (with --valid-from: Nieuwlaar's validity rule exactly)")
    p.add_argument("--pool", action="append", metavar="NAME=PATH",
                   help="zscore: a map pooled into model NAME's statistics (repeat; a quoted glob is expanded, sorted); "
                        "the k-th map of every model is one depth of the display stretch")
    p.add_argument("--stats", metavar="FILE.json", help="zscore: apply statistics saved by --stats-out (e.g. the reading "
                   "side's, to the blind side)")
    p.add_argument("--stats-out", metavar="FILE.json", help="zscore: save the statistics (from --pool, else the maps)")
    p.add_argument("--raw-out", metavar="FILE.npy", help="also save the unscaled combined values (zscore: mean z), "
                   "float32, NaN where invalid")
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
    p.add_argument("--shuffle", type=int, metavar="SEED", help="write the layers in a fixed random order (depth-shuffle control)")
    p.set_defaults(func=cmd_layers)

    p = sub.add_parser("shuffle", help="depth-shuffle control: copy a surface volume with its layers in a fixed random order")
    p.add_argument("volume", help="surface-volume zarr")
    p.add_argument("out", help="new zarr to write")
    p.add_argument("--seed", type=int, default=20261007)
    p.add_argument("--level", default="0")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"))
    p.set_defaults(func=cmd_shuffle)

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
