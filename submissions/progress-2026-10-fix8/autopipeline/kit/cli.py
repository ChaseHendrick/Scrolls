"""Command line: python -m kit {prizes,live,style,doctor,vc3d,snap,meshqa,autopipeline,normalaxis,surfacepred,surfbench,switchfix,labelxfer,canvasorient,dirtrend,fetch,verify,auc,inkfilter,overlap,collate,provenance,ensemble,inkensemble,layers,shuffle,run}."""

import argparse
import contextlib
import copy
import json
import sys
from pathlib import Path
from datetime import date

from . import inkfilter, autobatch, scancatalog, localcost, modalledger, auc, ensemble, inkensemble, doctor, fetch, layers, overlap, provenance, ledger, prizes, verify


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
    anchor = None
    try:
        result = auc.score_files(args.prediction, args.labels, args.mask, args.control, args.level,
                                 args.crop, args.surface_shape, args.keep_zero, args.inner,
                                 args.bootstrap, args.block_px, args.compare, args.seed,
                                 exclude=args.exclude, exclude_margin=args.exclude_margin, offset=args.label_offset)
        if args.anchor:
            from . import anchors
            try:
                anchor = anchors.auc_check(result, args.anchor, args.anchor_device)
            except anchors.AnchorError as exc:
                print(f"kit auc: {exc}", file=sys.stderr)
                return 2
            result["anchor"] = anchor
        if args.slug:
            ledger.add_check(args.slug, args.name, result, root=args.root)
    except (verify.VerifyError, ledger.LedgerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else auc.format_result(result))
    if anchor is not None:
        from . import anchors
        if anchor["status"] != anchors.OK:
            for line in anchors.drift_lines(anchor):
                print(line, file=sys.stderr)
            return anchors.EXIT_DRIFT
        if not args.json:
            print(f"anchor {anchor['id']}: holds")
    return 0


def cmd_inkfilter(args):
    try:
        recipe = args.recipe
        if args.recipe_file:
            recipe = inkfilter.check_recipe(json.loads(Path(args.recipe_file).read_text(encoding="utf-8")))
        if args.pool is not None or args.reverse_depth is not None:
            # one map for AutoPipeline's ink tool (vc3d_catalog.BUILTIN_MODELS["inkfilter"], engine command)
            if args.level != 0 or args.crop or args.villa_names or not args.no_control:
                raise inkfilter.InkFilterError("--pool and --reverse-depth read level 0 whole and write one map: "
                                               "give --level 0 and --no-control, without --crop or --villa-names")
            result = inkfilter.engine_map(args.volume, args.output, reverse=bool(args.reverse_depth),
                                          pool=args.pool or 1, recipe=recipe)
            print(json.dumps(result, indent=2) if args.json else
                  f"ink map ({result['recipe_name']}, {'reverse-depth control' if result['reverse'] else 'forward'}"
                  f", pool {result['pool']}): {result['output']}\nrecord: {result['record']}\n"
                  "A filter output, not a reading.")
            return 0
        result = inkfilter.run(args.volume, args.output, level=args.level, crop=args.crop, recipe=recipe,
                               control=not args.no_control, voxel_um=args.voxel_um, villa_names=args.villa_names,
                               model=args.model, scale=args.scale, villa_date=args.villa_date,
                               villa_overwrite=args.villa_overwrite)
    except (inkfilter.InkFilterError, ValueError, OSError) as exc:
        print(f"inkfilter: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else inkfilter.format_result(result))
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
    except RecursionError:
        print(f"{args.path}: malformed record: nested too deeply", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"problem: {problem}")
    if problems:
        return 1
    n = provenance.files_listed(record)
    files = (f", {n} listed files unchanged" if n else ", no files listed to check") if args.files else ""
    print(f"{args.path}: ok (the record matches its digest {record['digest']}{files}; "
          "a self-check, not proof of who wrote it)")
    return 0


def cmd_ensemble(args):
    try:
        result = ensemble.from_args(args)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else ensemble.format_result(result))
    return 0


def cmd_inkensemble(args):
    try:
        result = inkensemble.from_args(args)
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else inkensemble.format_result(result))
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


def cmd_batch(args):
    try:
        if args.action == "catalog":
            doc = scancatalog.fetch(prizes.load(), live=not args.no_live_prizes)
            scancatalog.write(doc, args.out)
            print(json.dumps(scancatalog.summary(doc), indent=1))
            print(f"wrote {args.out}")
            return 0
        if args.action == "watch":
            res = autobatch.watch(args.state)
            if args.json:
                print(json.dumps(res, indent=1))
            else:
                for q in res["queued"]:
                    print(f"{q['change']:<8} {q['key']:<32} {q['status']:<8} {q['voxel_um']} um "
                          f"{' '.join(q['readers']) or '-'} typical {q['usd']['typical']} USD"
                          + (f" ({q['reason']})" if q["reason"] else ""))
                print(f"{len(res['queued'])} queued (dry run, nothing launched), {len(res['gone'])} gone, "
                      f"{res['catalog_volumes']} volumes in the catalog" + (" (first run: all are new)" if res["first_run"] else ""))
                for q in res["rejected"]:
                    print(f"rejected {q['key']}: {q['reason']}")
            # a row that failed to plan needs a look as much as a new one, and it is retried on the next run
            return 3 if (args.exit_code and (res["queued"] or res["failed"])) else 0
        if args.status:
            rows = autobatch.status_table(args.state)
            for r in rows:
                print(f"{r['key']:<32} {r['status']:<9} {r['typical_usd']:>7} USD  {r['reason'] or ''}")
            print(f"{len(rows)} scans, typical total {round(sum(r['typical_usd'] for r in rows if r['status'] in ('planned', 'approved')), 2)} USD to run")
            return 0
        if args.approve:
            n = autobatch.approve(args.state, args.approve)
            print(f"approved {n} scans of plan {args.approve}; nothing launched")
            return 0
        if args.refresh:
            autobatch.load_catalog(args.state, refresh=True)
        plan = autobatch.plan_all(args.state, only=args.only, include_superseded=args.include_superseded)
        if args.json:
            print(json.dumps(plan, indent=1))
        else:
            print(autobatch.plan_markdown(plan))
            for q in plan["rejected"]:
                print(f"rejected {q['key']}: {q['reason']}")
            print(f"counts {plan['counts']}; plan digest {plan['digest']} (approve with: python -m kit run all "
                  f"--approve {plan['digest']}); nothing launched")
        return 0
    except (autobatch.BatchError, scancatalog.ScanCatalogError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def cmd_run(args):
    if args.action in ("all", "watch", "catalog"):
        if not (Path(__file__).resolve().parent / "autopipe.py").is_file():
            print(f"error: kit run {args.action} plans AutoPipeline runs, and this kit ships without AutoPipeline",
                  file=sys.stderr)
            return 2
        return cmd_batch(args)
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
            return _run_check(args, root)
        elif args.action == "local":
            cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
            code, item = localcost.run(args.slug, cmd, root=root, device=args.device,
                                       watts=args.watts, rate=args.rate)
            cpu = "unavailable" if item["cpu_s"] is None else f"{item['cpu_s']:.1f} s"
            print(f"{args.slug}: {item['wall_s']:.1f} s wall, {cpu} CPU, "
                  f"{item['kwh']:.4f} kWh, ${item['usd_exact']:.4f} (exit {code})", file=sys.stderr)
            if "ledger_error" in item:
                print(f"{args.slug}: the command exited {code}, but its cost was not written to the ledger: "
                      f"{item['ledger_error']}. Record it with kit run backfill, using the wall time above.",
                      file=sys.stderr)
                return code or 2
            return code
        elif args.action == "backfill":
            try:
                with open(args.file, encoding="utf-8") as fh:
                    items = json.load(fh)
            except (OSError, ValueError) as exc:
                raise localcost.CostError(f"cannot read backfill {args.file}: {exc}") from exc
            hours, usd = localcost.backfill(args.slug, items, root=root, rate=args.rate)
            print(f"{args.slug}: backfilled {len(items)} entries, {hours:.3f} h, ${usd:.4f} (estimated from logs)")
        elif args.action == "modal-row":
            try:
                with open(args.file, encoding="utf-8") as fh:
                    spec = json.load(fh)
            except (OSError, ValueError) as exc:
                raise modalledger.LedgerRowError(f"cannot read {args.file}: {exc}") from exc
            if not isinstance(spec, dict) or not isinstance(spec.get("row"), dict) or not spec.get("key"):
                raise modalledger.LedgerRowError(f"{args.file} is a JSON object with key, row and optionally generic")
            wrote = modalledger.append(args.ledger, spec["row"], str(spec["key"]), public=args.public_generic,
                                       generic=spec.get("generic") is True)
            print(f"{args.ledger}: {'row added' if wrote else 'already holds this row; nothing written'} "
                  f"({modalledger.KEY_MARK}{spec['key']})")
        elif args.action == "list":
            for record in ledger.list_runs(root):
                print(f"{record['slug']:<28} {record['scroll']:<12} {record['status']:<10} ${ledger.total_cost(record):.2f}")
    except (ledger.LedgerError, localcost.CostError, modalledger.LedgerRowError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _run_check(args, root):
    """run check: the ledger record (SLUG), the preregistration's hashed files (--prereg, or the record's prereg
    field), or both. A readout file that changed fails (exit 1, as a bad record does); a plumbing file that changed
    without a dated deviation line is attention (exit 3); see check_prereg in kit/preregsets.py."""
    from . import preregsets
    if not args.slug and not args.prereg:
        print("run check needs SLUG, --prereg PATH, or both", file=sys.stderr)
        return 2
    codes, out, prereg, extra = [], {}, args.prereg, []
    if args.slug:
        problems = ledger.check(args.slug, root=root)
        codes.append(1 if problems else 0)
        out["ledger"] = {"slug": args.slug, "problems": problems}
        if not args.json:
            for problem in problems:
                print(f"problem: {problem}")
            if not problems:
                print(f"{args.slug}: ok")
        record = ledger.load(args.slug, root=root)
        prereg = prereg or record.get("prereg")
        try:
            extra = preregsets.record_deviations(record.get("deviations") or [])
        except preregsets.PreregError as exc:
            print(f"run check: {args.slug}: {exc}", file=sys.stderr)
            return 2
    if prereg:
        path = Path(prereg)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(preregsets.ROOT.resolve())
            except ValueError:
                print(f"run check: {prereg} is not inside {preregsets.ROOT}", file=sys.stderr)
                return 2
        try:
            report = preregsets.check_prereg(preregsets.ROOT, path.as_posix(), args.at, args.record, extra)
        except preregsets.PreregError as exc:
            print(f"run check: {exc}", file=sys.stderr)
            return 2
        codes.append(report["exit"])
        out["prereg"] = report
        if not args.json:
            print(preregsets.format_prereg(report))
    code = 1 if 1 in codes else 3 if 3 in codes else 0
    if args.json:
        print(json.dumps(dict(out, exit=code), indent=2))
    return code


def _shape(v):
    return (v[0], v[1]) if v else (384, 384)


class _LazyParser(argparse.ArgumentParser):
    """A subcommand parser whose arguments come from its module's build_parser, run on first use.

    build_parser(lazy=True) leaves those modules unimported until their subcommand is parsed or its
    help is printed, so `python -m kit --help` and the light subcommands skip about 40 heavy
    imports (numpy among them). The finished parser is the same as the eager one."""

    _kit_module = None

    def _kit_build(self):
        deferred, self._kit_module = self._kit_module, None
        if deferred:
            # eager order: the module's arguments first, then cli's set_defaults on top
            cli_defaults = dict(self._defaults)
            _build(self, *deferred)
            self.set_defaults(**cli_defaults)

    def parse_known_args(self, args=None, namespace=None):
        self._kit_build()
        return super().parse_known_args(args, namespace)

    def format_usage(self):
        self._kit_build()
        return super().format_usage()

    def format_help(self):
        self._kit_build()
        return super().format_help()


def _build(p, module, builder, func):
    mod = __import__(module, fromlist=["x"])
    getattr(mod, builder)(p)
    if func:
        p.set_defaults(func=getattr(mod, func))


def _defer(p, module, lazy, builder="build_parser", func=None):
    """Add a module's subcommand arguments (module.builder(p), and func=module.func if given) to p
    now, or (lazy) when p is first used."""
    if lazy:
        p._kit_module = (module, builder, func)
    else:
        _build(p, module, builder, func)


def build_parser(lazy=False):
    parser = argparse.ArgumentParser(prog="python -m kit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_LazyParser)

    p = sub.add_parser("prizes", help="open prizes from the dated snapshot")
    p.add_argument("--json", action="store_true")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_prizes)

    p = sub.add_parser("live", help="run a command (after --) or page piped output in a full-screen, mouse-driven "
                                    "view in the Scrolls look")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="the command to run, after --")
    p.set_defaults(func=lambda a: __import__("kit.termview", fromlist=["x"]).main(a.cmd))

    p = sub.add_parser("style", help="the Scrolls terminal look: hook install|remove|status (style every script in "
                                     "a checkout), demo")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    p.set_defaults(func=lambda a: __import__("kit.termstyle", fromlist=["x"]).main(a.cmd))

    p = sub.add_parser("doctor", help="check GPU, disk, tools and villa paths")
    p.add_argument("--disk", default=".", help="path whose free space to check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("vc3d", help="headless VC3D: find, run and self-test the tools; agent tools over MCP "
                                     "(mcp) or a shell (tools, call)")
    _defer(p, "kit.vc3d", lazy)
    p.set_defaults(func=lambda a: __import__("kit.vc3d", fromlist=["x"]).cmd_vc3d(a))

    p = sub.add_parser("snap", help="snap a tifxyz mesh along its normals onto the nearest predicted sheet (or the CT sheet midline), regularized")
    _defer(p, "kit.snap", lazy)
    p.set_defaults(func=lambda a: __import__("kit.snap", fromlist=["x"]).cmd_snap(a))

    p = sub.add_parser("meshqa", help="mesh and prediction checks: VC3D-exact tifxyz validity and bbox, winding audit, garbage prediction cubes")
    _defer(p, "kit.meshqa", lazy)
    p.set_defaults(func=lambda a: __import__("kit.meshqa", fromlist=["x"]).cmd_meshqa(a))

    p = sub.add_parser("autopipeline", aliases=["autopipe"],
                       help="AutoPipeline, the automatic pipeline on one released scan: axis, seeds, trace, checks, "
                            "flatten, render, ink, score (autopipe: its earlier name)")
    _defer(p, "kit.autopipe", lazy)
    p.set_defaults(func=lambda a: __import__("kit.autopipe", fromlist=["x"]).cmd_autopipe(a))

    p = sub.add_parser("normalaxis", help="scroll axis from a scan's normal grids with numpy alone (no villa build): "
                                          "one slice, an axis over slices, or the planted self-check")
    __import__("kit.normalaxis", fromlist=["x"]).build_parser(p)
    p.set_defaults(func=lambda a: __import__("kit.normalaxis", fromlist=["x"]).cmd_normalaxis(a))

    p = sub.add_parser("surfacepred", help="surface prediction for scans without one: patch plan, level, packaging "
                                           "for VC3D, Dice, normal-grid and seating checks against published data")
    _defer(p, "kit.surfacepred", lazy)
    p.set_defaults(func=lambda a: __import__("kit.surfacepred", fromlist=["x"]).cmd_surfacepred(a))

    p = sub.add_parser("surfbench", help="geometry benchmark: score a traced tifxyz against the PHerc0139 hand windings, "
                                         "with controls that must be able to fail")
    _defer(p, "kit.surfbench", lazy)
    p.set_defaults(func=lambda a: __import__("kit.surfbench", fromlist=["x"]).cmd_surfbench(a))

    p = sub.add_parser("switchfix", help="flag sheet switches in a traced tifxyz from the surface prediction alone and "
                                         "cut the trace back to its seed's winding (no references)")
    _defer(p, "kit.switchfix", lazy)
    p.set_defaults(func=lambda a: __import__("kit.switchfix", fromlist=["x"]).cmd_switchfix(a))

    p = sub.add_parser("labelxfer", help="carry a published segment's ink labels onto a traced surface's render canvas "
                                         "by 3D proximity, check the carrying, and score maps on the carried labels")
    _defer(p, "kit.labelxfer", lazy)
    p.set_defaults(func=lambda a: __import__("kit.labelxfer", fromlist=["x"]).cmd_labelxfer(a))

    p = sub.add_parser("canvasorient", help="turn a surface's render canvas into the published layout (+z down the "
                                            "rows) before ink detection, and the maps back; self-check")
    _defer(p, "kit.canvasorient", lazy)
    p.set_defaults(func=lambda a: __import__("kit.canvasorient", fromlist=["x"]).cmd_canvasorient(a))
    p = sub.add_parser("dirtrend", help="forward against depth-reversed ink maps: area ratio at rising thresholds, its "
                                        "trend, and CT coverage before any blank call")
    _defer(p, "kit.dirtrend", lazy)
    p.set_defaults(func=lambda a: __import__("kit.dirtrend", fromlist=["x"]).cmd_dirtrend(a))

    p = sub.add_parser("fetch", help="mirror a public bucket prefix over HTTPS (no AWS CLI needed)")
    p.add_argument("prefix", help="bucket prefix, e.g. PHerc0139/segments/..., or 'w035' / 'w045' for the PHerc0139 surface volumes (w035: an ink_9um training segment; w045: unseen by v8in, but ink_9um trained on its 2.4 um render)")
    p.add_argument("dest", help="local directory")
    p.add_argument("--workers", type=int, default=16)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("verify", help="compare two ink maps (e.g. CPU vs MPS) with a control")
    p.add_argument("reference", help="reference map, e.g. the CPU run")
    p.add_argument("candidate", help="map to check, e.g. the MPS run")
    p.add_argument("--control", help="a map that must NOT agree, e.g. the reverse-direction output")
    p.add_argument("--tolerance", type=float, default=verify.DEFAULT_TOLERANCE, help="gray levels (0-255)")
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
    p.add_argument("--mask", required=True, help="supervision.zarr: where ink and non-ink were both labeled")
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
    p.add_argument("--anchor", metavar="ID",
                   help="check the result against this known-answer anchor (kit anchors list); exit 3 on drift")
    p.add_argument("--anchor-device", metavar="DEVICE",
                   help="the device the map was made on; the anchor's same-device tolerance applies when it matches")
    p.set_defaults(func=cmd_auc)

    p = sub.add_parser("inkfilter", help="hand-designed ink map of a surface volume window (no model), with its "
                                         "reverse-depth control")
    p.add_argument("volume", help="surface volume: local zarr directory or https/s3 URL (OME-Zarr or bare array)")
    p.add_argument("--output", required=True, help="map to write (.tif or .npy); the control and a JSON record go "
                                                   "next to it")
    p.add_argument("--level", type=int, default=1, help="pyramid level to read (default 1, the level the recipe was "
                                                        "chosen on)")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="window on the level's grid (default: the whole surface; keep it to about 2048 px a side)")
    p.add_argument("--recipe", default=None, help="named recipe (default: the shipped default)")
    p.add_argument("--recipe-file", help="JSON recipe to use instead of a named one")
    p.add_argument("--no-control", action="store_true", help="skip the reverse-depth control map")
    p.add_argument("--voxel-um", type=float, help="level 0 voxel size, recorded only")
    p.add_argument("--villa-names", metavar="SEGDIR",
                   help="also write the map and its control as villa's uint8 predictions "
                        "SEGDIR/preds/<seg>_<model>_forward_<ddmmyy>.tif and _reverse_ (level 0, the whole surface), "
                        "and register the map in SEGDIR/ink-detections.json for VC3D's Ink Detection overlay when "
                        "SEGDIR is a tifxyz segment; the float32 map is still written")
    p.add_argument("--model", metavar="NAME", help="with --villa-names: the model name in villa's file names "
                                                   "(default inkfilter-<recipe name>)")
    p.add_argument("--scale", metavar="minmax|pLO-pHI",
                   help="with --villa-names: the values that become 0 and 255, from the map's rendered pixels: "
                        "minmax (default) or percentiles such as p1-p99; the control uses the map's limits")
    p.add_argument("--villa-date", metavar="DDMMYY", help="with --villa-names: the date in the names (default today, "
                                                          "as villa writes it)")
    p.add_argument("--villa-overwrite", action="store_true", help="with --villa-names: replace files already at "
                                                                  "villa's names")
    p.add_argument("--pool", type=int, metavar="N",
                   help="with --level 0 --no-control: read level 0 whole, average N x N pixels (2 on a 2.4 um render "
                        "is the grid the recipe was chosen on), and repeat the map back onto level 0's grid "
                        "(AutoPipeline's ink engine)")
    p.add_argument("--reverse-depth", type=int, choices=(0, 1), metavar="0|1",
                   help="with --level 0 --no-control: 1 writes the reverse-depth control at --output instead of the "
                        "forward map (AutoPipeline's {reverse})")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inkfilter)

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

    p = sub.add_parser("inkensemble", help="AutoPipeline's ink-ensemble stage: member maps z-scored inside the mask "
                       "(mean and SD, or --robust median and MAD), combined by a weighted or trimmed mean, with provenance")
    p.add_argument("out", help="output map, .tif (uint16, valid 1..65535) or .npy (float32)")
    p.add_argument("maps", nargs="+", help="member maps on one grid, NAME=PATH (or PATH, named map1, map2, ...)")
    p.add_argument("--robust", action="store_true", help="each member's median and MAD x 1.4826 instead of mean and SD")
    p.add_argument("--combine", choices=inkensemble.COMBINES, default="mean",
                   help="mean (default): weighted mean of the z-scores; trimmed: drop floor(trim x n) at each end per pixel")
    p.add_argument("--trim", type=float, help=f"share trimmed at each end with --combine trimmed (default {inkensemble.DEFAULT_TRIM})")
    p.add_argument("--weights", type=float, nargs="+", help="one weight per member, in the order given (default equal)")
    p.add_argument("--decode", action="append", metavar="[NAME=]ls|none", help="as kit ensemble (default none)")
    p.add_argument("--mask", metavar="MASK", help="only pixels where this mask map is above 0, or a surface volume (zarr) "
                   "is above 0 in every layer; never a label file")
    p.add_argument("--keep-zero", action="store_true", help="count raw 0 as a prediction")
    p.add_argument("--raw-out", metavar="FILE.npy", help="also save the unscaled combined z (float32, NaN where invalid)")
    p.add_argument("--provenance", metavar="REC.json", help="where the provenance record goes (default OUT with the "
                   "suffix .provenance.json)")
    p.add_argument("--run", default="inkensemble", help="run name in the provenance record")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inkensemble)

    p = sub.add_parser("layers", help="export a surface-volume zarr to 00.tif, 01.tif, ... (v8in's input)")
    p.add_argument("volume", help="surface-volume zarr, e.g. from vc_render_tifxyz --zarr-output")
    p.add_argument("out_dir", help="folder for the layer TIFFs; it must not already hold numbered TIFFs")
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
    a = actions.add_parser("check", help="a record's consistency, and a preregistration's hashed files (readout "
                                         "changes fail, plumbing changes need a dated deviation line)")
    a.add_argument("slug", nargs="?", help="the experiment to check (optional with --prereg)")
    a.add_argument("--prereg", help="a preregistration whose code-sha256 blocks to check (default: the record's "
                                    "prereg field)")
    a.add_argument("--at", help="compare the hashed files at this commit (default: the working tree)")
    a.add_argument("--record", action="append", default=[],
                   help="a run record holding a deviations block; repeatable")
    a.add_argument("--json", action="store_true", help="print JSON")
    actions.add_parser("list")
    # local and backfill: the same commands as public Scrolls (kit/localcost.py is the same file in both)
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
    a = actions.add_parser("modal-row", help="append one Modal job's row to a Modal ledger CSV, once per key "
                                             "(kit/modalledger.py)")
    a.add_argument("file", help="JSON object: key (unique per launch), row (column: value), generic (true or false)")
    a.add_argument("--ledger", default="docs/compute/modal-ledger.csv", help="ledger CSV (default %(default)s)")
    a.add_argument("--public-generic", action="store_true",
                   help="write the public ledger: refused unless the row is marked generic and names no title, "
                        "target, preregistered or held-out work")
    a = actions.add_parser("all", help="AutoPipeline over every released scan: catalog, per-scan config, priced plan, "
                                        "resumable queue (kit/autobatch.py); launches nothing")
    a.add_argument("--state", default=str(autobatch.STATE), help="batch folder (default work/autobatch, git-ignored)")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="plan and price every scan (the default action)")
    g.add_argument("--status", action="store_true", help="per-scan status and totals")
    g.add_argument("--approve", metavar="DIGEST", help="record the owner's approval of that priced plan")
    a.add_argument("--refresh", action="store_true", help="rebuild the catalog from the bucket first")
    a.add_argument("--only", help="SAMPLE or SAMPLE/VOLUME")
    a.add_argument("--include-superseded", action="store_true", help="plan superseded volumes too")
    a.add_argument("--json", action="store_true")
    a = actions.add_parser("watch", help="for a scheduled routine: find new or changed volumes in the bucket, queue "
                                          "them priced in dry run, print them (launches nothing)")
    a.add_argument("--state", default=str(autobatch.STATE))
    a.add_argument("--json", action="store_true")
    a.add_argument("--exit-code", action="store_true", help="exit 3 when something new was queued")
    a = actions.add_parser("catalog", help="write the catalog of every volume in the open-data bucket")
    a.add_argument("--out", default=str(autobatch.STATE / "catalog.json"))
    a.add_argument("--no-live-prizes", action="store_true", help="use the dated prizes snapshot only")
    p.set_defaults(func=cmd_run)
    return parser


_PARSER = None


def _parser():
    """The kit parser, built once per process: it is about 1,400 add_argument calls (~0.1 s), and
    tests and pipelines call main() hundreds of times in one process."""
    global _PARSER
    if _PARSER is None:
        _PARSER = build_parser(lazy=True)
    return _PARSER


def _parse(parser, argv):
    # parse with the shared parser, then deep-copy so a command that mutates a list default
    # (default=[]) cannot leak it into the next call, exactly as with a freshly built parser
    return copy.deepcopy(parser.parse_args(argv))


def main(argv=None):
    if argv is None and sys.stdout.isatty():
        # The Scrolls terminal look, on a terminal only (kit/termstyle.py; Chase, 23 Oct 2026). Never loaded for
        # pipes, logs or containers, so frozen runs import nothing new.
        from . import termstyle
        termstyle.auto()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    # Python 3.10 argparse mishandles a trailing nargs="*" after wrapper options.
    # Parse the wrapper separately, leaving every child flag and literal intact.
    if argv[:1] == ["live"]:
        return __import__("kit.termview", fromlist=["x"]).main(argv[1:])
    if argv[:1] == ["style"]:
        return __import__("kit.termstyle", fromlist=["x"]).main(argv[1:])
    if argv[:1] == ["run"] and "--" in argv:
        split = argv.index("--")
        args = _parse(parser, argv[:split])
        if args.action == "local":
            args.cmd.extend(argv[split + 1:])
        else:
            args = _parse(parser, argv)
    else:
        args = _parse(parser, argv)
    return args.func(args)
