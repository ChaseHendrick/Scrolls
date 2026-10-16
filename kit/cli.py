"""Command line: python -m kit {prizes,doctor,plan,cost,fetch,verify,rowscore,auc,hpscore,overlap,collate,stackcheck,ensemble,fibertensor,gate,layers,shuffle,provenance,compute,run,surfacefix,phantom,view,letterread,letterlines,letterdemo,greeklm,releases}.

An installed package (pyproject.toml) has the same commands as console scripts: scrolls-workbench (every command;
gate and releases read the repository's docs/ and README.md, so they need a clone), and scrolls-letterread,
scrolls-letterlines and scrolls-letterdemo (one command each; CONSOLE_SCRIPTS).
"""

import argparse
import copy
import json
import sys
from pathlib import Path
from datetime import date

from . import autobatch, scancatalog, localcost, modalledger, meshaudit, auc, compute, ensemble, fibertensor, gate, hpscore, doctor, fetch, layers, overlap, provenance, ledger, plan, prizes, rowscore, verify, surfacefix, phantom, viewer, releases


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


def cmd_stackcheck(args):
    """Geometry checks of a stack of consecutive tifxyz segments against the umbilicus (kit/stackcheck.py)."""
    from . import stackcheck
    settings = {"planes": args.planes, "plane_z": args.plane_z, "ray_step_deg": args.ray_step_deg,
                "max_normal_um": args.max_normal_um, "coincide_um": args.coincide_um, "skip_frac": args.skip_frac,
                "min_count": args.min_count, "min_share": args.min_share, "upsample": args.upsample}
    log = (lambda m: print(m, file=sys.stderr, flush=True)) if args.verbose else None
    try:
        rep, segs, masks = stackcheck.run(args.segments, args.umbilicus, args.transform, args.catalog, args.voxel_um,
                                          args.stride, args.cache, settings, log)
        if args.flags:
            rep["flags_file"] = stackcheck.write_flags(args.flags, segs, masks, rep["frame"]["voxel_um"])
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(rep, indent=1))
        print(json.dumps(rep, indent=1) if args.json else stackcheck.format_report(rep))
    except verify.VerifyError as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:  # an output that cannot be written: exit 1 would read as flagged
        print(f"kit stackcheck could not read or write a file: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001  exit 1 means flagged, so an unexpected error must not exit 1
        import traceback
        traceback.print_exc()
        print("kit stackcheck stopped on an unexpected error (above)", file=sys.stderr)
        return 2
    return 0 if rep["summary"]["clean"] else 1


def cmd_meshaudit(args):
    """Mesh and cross-scan render audit (docs/plans/2026-10-07-mesh-hypothesis.md)."""
    try:
        cat = meshaudit.load_catalogue(args.catalogue)
    except (OSError, ValueError) as exc:
        print(f"meshaudit: cannot read the catalogue: {exc}. Give a metadata.json path or URL with --catalogue.",
              file=sys.stderr)
        return 2
    if not isinstance(cat, dict) or not isinstance(cat.get("samples"), dict):
        print("meshaudit: the catalogue has no samples object; give the bucket's metadata.json with --catalogue.",
              file=sys.stderr)
        return 2
    if args.action == "transforms":
        out = meshaudit.transforms_audit(cat)
        if not args.json:
            for r in out:
                loo = "-" if r["loo_rms_um"] is None else "%.1f" % r["loo_rms_um"]
                print("%-12s %s -> %s  landmarks %2d  LOO RMS %6s um  %s" % (
                    r["sample"], r["from_volume"], r["to_volume"], r["n_landmarks"], loo, r["tier"]))
    elif args.action == "canvas":
        rows, mesh_errors = meshaudit.canvas_audit(cat, samples=args.sample or None, workers=args.workers)
        out = {"rows": rows, "mesh_errors": mesh_errors}
        if not args.json:
            n = len(rows)
            ok = sum(r["reproducible"] for r in rows)
            named = sum(r["reproducible_by_named_variant"] for r in rows)
            print("surface volumes %d, reproducible from a published mesh %d, by a variant naming the volume %d"
                  % (n, ok, named))
    elif args.action == "plan":
        out = meshaudit.plan_depth(cat, per_combo=args.per_combo, seed=args.seed)
        if not args.json:
            for p in out:
                print("%-12s native %s cross %s  %d of %d segments" % (
                    p["sample"], p["native_volume"], p["cross_volume"], len(p["segments"]), p["segments_available"]))
    else:  # depth
        s = cat["samples"].get(args.sample)
        if not isinstance(s, dict):
            print(f"meshaudit: the catalogue has no sample {args.sample!r}; samples: {', '.join(sorted(cat['samples']))}",
                  file=sys.stderr)
            return 2
        seg = (s.get("segments") or {}).get(args.segment)
        if not isinstance(seg, dict):
            print(f"meshaudit: sample {args.sample} has no segment {args.segment!r} in the catalogue; "
                  f"check the id against samples.{args.sample}.segments in metadata.json", file=sys.stderr)
            return 2
        out = meshaudit.depth_segment(args.base, args.sample, seg, cross_ids=args.cross or None,
                                      n_tiles=args.tiles, seed=args.seed, reference=args.reference)
        if not args.json:
            for p in out["pairs"]:
                print("%s %s -> %s  tiles %s  median delta %s um  control %s" % (
                    args.segment, out["native_volume"], p["cross_volume"], p.get("tiles_with_peaks"),
                    p.get("delta_median_um"), p.get("location_control_pass")))
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1)
        except OSError as exc:
            print(f"meshaudit: cannot write {args.out}: {exc}. Give --out a path in an existing folder.",
                  file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(out, indent=1))
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


def cmd_compute(args):
    missing = [p for p in args.paths if not Path(p).exists()]
    if missing:
        print(f"no such file or folder: {', '.join(missing)}; check the paths", file=sys.stderr)
        return 2
    records = compute.collect(args.paths)
    if not records:
        print("no provenance records found", file=sys.stderr)
        return 2
    try:
        r = compute.rows(records, args.watts)
    except ValueError as exc:
        print(f"{exc}; leave that record out of the paths given", file=sys.stderr)
        return 2
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
    if not Path(args.results).is_file():
        print(f"cannot read the scores: no {args.results}. The gate reads the repository's docs/results.json, which "
              "an installed package does not have: run it from a clone (git clone "
              "https://github.com/ChaseHendrick/Scrolls), or give --results", file=sys.stderr)
        return 2
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


# The packages by name: scrolls-workbench is not on PyPI, so "pip install scrolls-workbench[reader]" from a clone would
# fetch whatever someone else published under that name
READER_INSTALL = "python -m pip install numpy pillow tifffile imagecodecs (the reader extra's packages)"


def import_advice(exc):
    """An ImportError's text, with the reader extra's install line when the missing module is one it brings."""
    names = {getattr(exc, "name", None), getattr(exc.__cause__, "name", None)}
    if any(n and n.split(".")[0] in ("numpy", "PIL", "tifffile", "imagecodecs") for n in names):
        return f"{exc}; {READER_INSTALL}"
    if any(n and n.split(".")[0] == "zarr" for n in names):
        return f'{exc}; python -m pip install zarr (Python 3.11 or newer)'
    return str(exc)


def cmd_letterread(args):
    say = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
    letter_px = net = None
    try:
        from . import letterread
        letterread.utf8_console()       # Greek letters print in a pipe and on a Windows console too
        if args.letter_px is not None and (args.letter_mm is not None or args.um_per_px is not None):
            raise ValueError("give the letter height once: --letter-px, or --letter-mm with --um-per-px")
        letter_px = args.letter_px
        if args.letter_mm is not None or args.um_per_px is not None:
            letter_px = letterread.letter_px_from_units(args.letter_mm, args.um_per_px)
            if letter_px < letterread.MIN_LETTER_PX:
                raise ValueError(f"--letter-mm {args.letter_mm:g} at --um-per-px {args.um_per_px:g} is a letter "
                                 f"{letter_px:.3g} px tall, under the {letterread.MIN_LETTER_PX} px the reader can read; "
                                 "check the units (the letter height in millimetres, the pixel size in micrometres)")
        elif letter_px is not None and not letter_px >= letterread.MIN_LETTER_PX:
            raise ValueError(f"--letter-px {letter_px}: give the letter height in image pixels, at least "
                             f"{letterread.MIN_LETTER_PX} (the network reads letters 16 px tall, so smaller letters "
                             "have no shape left to read)")
        if args.max_mpx <= 0 or args.overlay_max_side < 16:
            raise ValueError("--max-mpx must be positive and --overlay-max-side at least 16")
        if args.min_letters < 1:
            raise ValueError(f"--min-letters {args.min_letters}: give at least 1")
        if not 0 <= args.deskew < 45:
            raise ValueError(f"--deskew {args.deskew}: give an angle from 0 (off) to under 45 degrees")
        if not 0 <= args.nulls <= letterread.MAX_NULLS or args.beam < 1 or args.lm_weight < 0:
            raise ValueError(f"--nulls must be 0 to {letterread.MAX_NULLS}, --beam at least 1 and --lm-weight 0 or more")
        if args.p_min is not None and not 0 <= args.p_min <= 1:
            raise ValueError(f"--p-min {args.p_min}: give a confidence from 0 to 1")
        if args.columns not in ("auto", "off") and not (args.columns.isdigit() and int(args.columns) >= 1):
            raise ValueError(f"--columns {args.columns}: give auto, off or a number of columns, at least 1")
        # Check where the results go before the read, which can take minutes.
        if args.overlay:
            try:
                from PIL import Image
            except ImportError as exc:
                raise ImportError(f"--overlay needs Pillow: {exc}") from exc
            Image.init()
            if Path(args.overlay).suffix.lower() not in Image.registered_extensions():
                raise ValueError(f"--overlay {args.overlay}: give an image file name such as letters.png")
        for out in (args.out, args.overlay, args.csv, args.page_xml):
            if out and not Path(out).resolve().parent.is_dir():
                raise OSError(f"no such folder for {out}")
        for image in (args.image, args.control):   # before the weights, which may download
            if image and not Path(image).exists():
                raise OSError(f"{image}: no such file or folder")
        if args.letter_mm is not None:
            say(f"letter height {args.letter_mm:g} mm at {args.um_per_px:g} um per pixel: {letter_px:.2f} px")
        # the weights before the image, so a failed download costs no load
        net = letterread.load_weights(args.weights)
        lm = None
        if args.lm:
            from . import greeklm
            lm = greeklm.KNLetterLM.load(args.lm)
        exif = letterread.exif_orientation(args.image)
        if exif != 1:
            say(f"{Path(args.image).name}: EXIF orientation {exif} applied, so pixels, --crop and boxes are those of "
                "the image as a viewer shows it")
        img, k, shape = letterread.load_reduced(args.image, args.key, crop=args.crop, letter_px=letter_px,
                                                net_letter_px=net.letter_px, max_pixels=int(args.max_mpx * 1e6),
                                                progress=say)
        columns = args.columns if args.columns in ("auto", "off") else int(args.columns)
        if args.polarity == "auto":   # a quick read both ways decides (letterread.polarity_trial)
            say("polarity auto: a quick read as bright ink and as dark ink")
            a0, pinfo = letterread.normalize_auto(img, net, max_pixels=int(args.max_mpx * 1e6), letter_px=letter_px,
                                                  input_scale=k, seed=args.seed, columns=columns,
                                                  deskew_deg=args.deskew, lines=args.lines, rotate=args.rotate,
                                                  mirror=args.mirror, letter_px_fallback=False,
                                                  min_letters=args.min_letters)
            say(f"polarity auto: {pinfo['used']} ink ({letterread.trial_text(pinfo['trial'])})")
        else:
            a0, pinfo = letterread.normalize_for_reading(img, args.polarity, max_pixels=int(args.max_mpx * 1e6),
                                                         with_info=True)
        del img
        c0 = None
        if args.control:
            # the same window and the same block size as the image, so its pixels sit on the image's pixels
            cimg, ck, cshape = letterread.load_reduced(args.control, args.key, crop=args.crop, letter_px=letter_px,
                                                       net_letter_px=net.letter_px,
                                                       max_pixels=int(args.max_mpx * 1e6), progress=say)
            if (cshape, ck) != (shape, k):
                raise ValueError(f"--control {args.control}: {cshape[0]} x {cshape[1]} px, but the image is {shape[0]} x "
                                 f"{shape[1]}; give a map of the same surface on the same grid (such as its "
                                 "reverse-depth map)")
            letterread.check_control(cimg, f"--control {args.control}")
            # in the image's polarity, so --polarity auto cannot read the control map the other way round
            c0 = letterread.normalize_for_reading(cimg, pinfo["used"], max_pixels=int(args.max_mpx * 1e6))
            del cimg
        res = letterread.read(a0, net, normalized=True, input_scale=k, orientation=not args.no_orientation,
                              rotate=args.rotate, mirror=args.mirror, deskew_deg=args.deskew, polarity_info=pinfo,
                              letter_px=letter_px, polarity=pinfo["used"], nulls=args.nulls, seed=args.seed,
                              lines=args.lines, p_min=args.p_min, lm=lm, lm_weight=args.lm_weight if lm else 0.0,
                              beam=args.beam, letter_px_fallback=False, progress=say, control=c0,
                              min_letters=args.min_letters, columns=columns)
        del c0
        # file names only, never a folder, so a result can be shared without a local path
        res["source"] = {"file": Path(args.image).name, "key": args.key}
        res["options"]["max_mpx"] = args.max_mpx
        if args.control:
            res["control"]["control_map"]["file"] = Path(args.control).name
        res["input_shape"] = list(shape)   # the exact input window, including rows and columns under one block
        # the whole image's size, which places a --crop window in the image file (the CSV and PAGE exports)
        res["image_shape"] = list(letterread.image_shape(args.image, args.key)) if args.crop else list(shape)
        if exif != 1:
            res["exif_orientation"] = exif
        if args.letter_mm is not None:
            res["letter_mm"], res["um_per_px"] = args.letter_mm, args.um_per_px
        if args.crop:
            res["crop"] = list(args.crop)  # [Y0, Y1, X0, X1]; every row, column and box is relative to Y0, X0
        if args.overlay:
            res["overlay"] = dict(file=Path(args.overlay).name,
                                  **letterread.overlay_geometry(a0.shape, res, args.overlay_max_side))
    except MemoryError:
        net_px = getattr(net, "letter_px", 16)
        if letter_px is not None and float(letter_px) // (2 * net_px) <= 1:
            # block-averaging stops at letters twice the network's height (reduce_factor), so only a window helps
            print(f"out of memory reading {args.image}. Its letters ({float(letter_px):g} px tall) are too small to "
                  f"block-average (that needs letters at least {4 * net_px} px tall), so the image is loaded whole: "
                  "read a window with --crop Y0 Y1 X0 X1, or check the letter size.", file=sys.stderr)
        else:
            print(f"out of memory reading {args.image}. Give the letter size (--letter-px, or --letter-mm with "
                  "--um-per-px) so a big image is block-averaged while it loads, lower the budget with --max-mpx, "
                  "or read a window with --crop Y0 Y1 X0 X1.", file=sys.stderr)
        return 2
    except ImportError as exc:
        print(import_advice(exc), file=sys.stderr)
        return 2
    except (OSError, KeyError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    # The files first (their folders were checked before the read), then the screen: a console that
    # fails on a letter never loses a finished read.
    failed, wrote = [], []
    if args.out:
        try:
            Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            wrote.append(args.out)
        except OSError as exc:
            failed.append(exc)
    if args.csv or args.page_xml:
        from . import letterexport
        for out, write in ((args.csv, letterexport.write_csv), (args.page_xml, letterexport.write_page_xml)):
            if out:
                try:
                    write(res, out)
                    wrote.append(out)
                except (OSError, ValueError) as exc:
                    failed.append(exc)
    if args.overlay:
        try:
            # a colour photograph is drawn in colour; other images from the read image in their own polarity
            base = letterread.display_image(args.image, args.crop, k)
            letterread.overlay(a0, res, args.overlay, max_side=args.overlay_max_side, normalized=True,
                               base=base if base is not None and base.shape[:2] == a0.shape else None)
            wrote.append(args.overlay)
        except (ImportError, OSError, ValueError) as exc:
            failed.append(exc)
    for out in wrote:
        say(f"wrote {out}")
    print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else letterread.text_summary(res))
    for exc in failed:
        print(exc, file=sys.stderr)
    return 2 if failed else 0


def cmd_letterlines(args):
    say = (lambda msg: None) if getattr(args, "quiet", False) else (lambda msg: print(msg, file=sys.stderr, flush=True))
    try:
        from . import letterlines, letterread
        letterread.utf8_console()
        if args.action == "build":
            if not args.dry_run and not args.out:
                raise ValueError("give --out LINES.npz, or --dry-run to check the records and see what would be cut")
            for out in (args.out, args.preview):   # their folders are made once the records pass
                if out and Path(out).is_dir():
                    raise OSError(f"{out} is a folder; give a file name")
            if args.max_mpx <= 0:
                raise ValueError("--max-mpx must be positive")
            if args.preview:
                try:
                    import PIL  # noqa: F401
                except ImportError as exc:
                    raise ImportError(f"--preview needs Pillow: {exc}") from exc
            try:
                plans, warnings, meta = letterlines.build(args.records, args.out, split=args.split,
                                                          dry_run=args.dry_run, max_pixels=int(args.max_mpx * 1e6),
                                                          progress=say)
            except letterlines.RecordsError as exc:
                print(f"{len(exc.errors)} problem{'s' if len(exc.errors) > 1 else ''} in the records; nothing was cut:",
                      file=sys.stderr)
                for e in exc.errors:
                    print("error: " + e, file=sys.stderr)
                return 2
            if args.dry_run:
                print(letterlines.plan_text(plans, warnings))
                print("dry run: nothing was cut or written")
                return 0
            for w in warnings:
                say("warning: " + w)
            print(f"{args.out}: {meta['lines']} line{'' if meta['lines'] == 1 else 's'}, {meta['letters']} letters and "
                  f"{meta['wildcards']} '?', from {len(meta['images'])} image(s)")
            if args.preview:
                imgs, texts, _, _ = letterlines.load_lines(args.out)
                Path(args.preview).parent.mkdir(parents=True, exist_ok=True)
                letterlines.preview(args.preview, imgs, texts)
                print(f"{args.preview}: the first {min(100, len(imgs))} bands, each above its text; check that every "
                      "band holds its line")
            return 0
        if args.out and not Path(args.out).resolve().parent.is_dir():
            raise OSError(f"no such folder for {args.out}")
        res = letterlines.score_lines(args.lines, args.weights)
        if args.out:
            Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else letterlines.score_text(res))
    except ImportError as exc:
        print(import_advice(exc), file=sys.stderr)
        return 2
    except (OSError, KeyError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def cmd_greeklm(args):
    try:
        from . import greeklm, letterread
        letterread.utf8_console()
        if args.action == "build":
            lm, stats = greeklm.build(args.tei, order=args.order)
            lm.save(args.out)
            print(json.dumps(dict(stats, out=args.out, order=args.order), indent=2))
        else:
            lm = greeklm.KNLetterLM.load(args.model)
            text = greeklm.clean_text(" ".join(args.text))
            print(json.dumps({"letters": text, "bits_per_letter": round(lm.bits_per_letter(text), 3) if text else None},
                             ensure_ascii=False))
    except (ImportError, OSError, KeyError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def cmd_letterdemo(args):
    try:
        from . import letterdemo   # numpy; the core kit is standard library only
    except ImportError as exc:
        print(f"DEMO ERROR: the letter reader needs numpy ({exc}); {READER_INSTALL}", file=sys.stderr)
        return 2
    return letterdemo.run_cli(args)


# Console scripts that run one command (pyproject.toml's [project.scripts]): script name -> command.
CONSOLE_SCRIPTS = {"scrolls-letterread": "letterread", "scrolls-letterlines": "letterlines",
                   "scrolls-letterdemo": "letterdemo"}


def cmd_strokenet(args):
    try:
        import numpy as np
        from . import strokenet
        strokenet.check_pixel_mm(args.pixel_mm)                        # before the weights, which may download
        net = strokenet.load(args.weights)
        crop = None
        with strokenet.open_map(args.map, args.key) as img:          # keeps the dtype: exact pooling of integer maps
            if args.crop:
                used, moved = strokenet.snap_crop(args.crop, args.pixel_mm, shape=img.shape)
                y0, y1, x0, x1 = used
                img = img[y0:y1, x0:x1]
                crop = {"requested": list(args.crop), "used": used, "origin_moved_to_lattice": moved}
            res, grid = strokenet.analyze(img, args.pixel_mm, net, stride_px=args.stride, sample=args.sample,
                                          seed=args.seed, with_grid=True)
        if crop:
            res["crop"] = crop
        if args.grid:
            gpath = args.grid if args.grid.endswith(".npy") else args.grid + ".npy"   # np.save adds .npy
            np.save(gpath, grid)
            res["grid_file"] = gpath
    except (ImportError, OSError, KeyError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1) if args.json else strokenet.text_summary(res))
    return 0


def build_parser(prog="python -m kit", sub_progs=None):
    """The parser of every command; sub_progs maps a command to the program name its usage and errors show."""
    sub_progs = sub_progs or {}
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
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

    p = sub.add_parser("stackcheck", help="check consecutive tifxyz segments against the umbilicus: order, missing "
                                          "sectors, skipped windings, turn overlaps, stack ends (geometry only)")
    p.add_argument("segments", nargs="+", help="tifxyz folders or bucket URLs, inner to outer; NAME=PATH names one")
    p.add_argument("--umbilicus", required=True, help="the scroll's umbilicus JSON (path or URL)")
    p.add_argument("--transform", help="matrix JSON, or catalog:SAMPLE:FROM:TO, taking the segments into the "
                                       "umbilicus's volume")
    p.add_argument("--catalog", help="metadata.json path or URL for catalog:... (default: the public bucket's)")
    p.add_argument("--voxel-um", type=float, help="voxel size of the umbilicus's volume (default: its metadata)")
    p.add_argument("--stride", type=int, default=1, help="use every Nth grid row and column (default 1)")
    p.add_argument("--planes", type=int, help="planes of constant z for the rays, evenly over the stack (default 50)")
    p.add_argument("--plane-z", type=float, nargs=3, metavar=("START", "STOP", "STEP"),
                   help="explicit plane heights, instead of --planes")
    p.add_argument("--ray-step-deg", type=float, help="degrees between rays, at most 10 (default 1)")
    p.add_argument("--max-normal-um", type=float, help="farthest neighbour along a normal (default 600)")
    p.add_argument("--coincide-um", type=float, help="two segments this close cannot be told apart (default 20)")
    p.add_argument("--skip-frac", type=float, help="skipped winding: closer than this share of the pitch (default 0.5)")
    p.add_argument("--min-count", type=int, help="rays or vertices for a flag, at least 1 (default 10)")
    p.add_argument("--min-share", type=float, help="share of rays or vertices for a flag (default 0.01)")
    p.add_argument("--upsample", type=int, help="neighbour grids made this much denser for the normal search (default 2)")
    p.add_argument("--cache", default="work/stackcheck/cache", help="where bucket segments are kept")
    p.add_argument("--out", help="write the JSON report here (work/ is git-ignored)")
    p.add_argument("--flags", help="write per-vertex flag masks (.npz, added if missing) on each segment's input grid")
    p.add_argument("--json", action="store_true")
    p.add_argument("--verbose", action="store_true", help="progress to stderr")
    p.set_defaults(func=cmd_stackcheck)

    p = sub.add_parser("meshaudit", help="audit published meshes, cross-scan transforms and render depth offsets")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("transforms", help="refit catalogue affines from their landmarks: residual, leave-one-out, round trip")
    a = actions.add_parser("canvas", help="does a published mesh variant reproduce each surface volume's canvas size?")
    a.add_argument("--sample", action="append", help="limit to this sample (repeatable)")
    a.add_argument("--workers", type=int, default=16)
    a = actions.add_parser("plan", help="choose segments for the depth comparison (seeded)")
    a.add_argument("--per-combo", type=int, default=5)
    a.add_argument("--seed", type=int, default=meshaudit.SEED)
    a = actions.add_parser("depth", help="papyrus depth offset between a segment's native and cross-scan renders")
    a.add_argument("--sample", required=True)
    a.add_argument("--segment", required=True, help="catalogue segment id")
    a.add_argument("--cross", action="append", help="limit to this cross volume id (repeatable)")
    a.add_argument("--tiles", type=int, default=32)
    a.add_argument("--seed", type=int, default=meshaudit.SEED)
    a.add_argument("--base", default=meshaudit.BUCKET)
    a.add_argument("--reference", help="volume id whose render plays the native role (protocol amendment H3b)")
    for a in actions.choices.values():
        a.add_argument("--catalogue", help="metadata.json path or URL (default: the public bucket's)")
        a.add_argument("--out", help="write the JSON result here")
        a.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_meshaudit)

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

    p = sub.add_parser("gate", help="Gate A: rank readers on PHerc0841's three crops by the rule in kit/gate.py")
    p.add_argument("work", nargs="?", help="Mac work directory with <segment>/results/auc_*.json (default ~/scrolls-work if present)")
    p.add_argument("--results", default=str(gate.RESULTS), help="committed scores (docs/results.json)")
    p.add_argument("--min-lead", type=float, default=gate.MIN_LEAD, help="mean AUC lead that counts as a win")
    p.add_argument("--min-gap", type=float, default=gate.MIN_GAP, help="forward minus reverse AUC needed on every crop")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gate)

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

    p = sub.add_parser("strokenet", help="learned text-likeness score of a 2D ink map (StrokeNet), with rotation and IAAFT controls")
    p.add_argument("map", help=".npy, .npz, .tif or .png ink map on the organisers' 0 to 255 scale (ink bright)")
    p.add_argument("--pixel-mm", type=float, required=True,
                   help="map pixel size in mm (0.0024 for a 2.4 um map; an integer map at a whole fraction of "
                        "0.048 mm is pooled exactly as the training windows)")
    p.add_argument("--weights", default=None,
                   help="StrokeNet .npz, or a released model name (default strokenet-paris4-v1, downloaded once, SHA-256 checked)")
    p.add_argument("--key", help=".npz: array name (default: the first)")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="map pixels to keep; for an exact-pooling map the origin moves down to the 32 px training "
                        "lattice, and the end is clipped to the map (the result records both boxes). The window rule "
                        "then sees the crop alone; score the whole map for exactly the training rule")
    p.add_argument("--stride", type=int, default=32,
                   help="window step in 0.048 mm pixels (default 32, 1.5 mm, the training lattice)")
    p.add_argument("--sample", type=int, default=64,
                   help="kept windows drawn at random (with --seed) for the rotation and IAAFT controls (default 64)")
    p.add_argument("--top", type=int, dest="sample", default=argparse.SUPPRESS, help=argparse.SUPPRESS)  # old name
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--grid", help="also save the window logit grid as .npy (NaN where a window was skipped); its "
                                  "row and column starts are window_y_px and window_x_px in the result, every stride "
                                  "except the last, which ends at the map's edge")
    p.add_argument("--out", help="also write the result as JSON")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_strokenet)

    p = sub.add_parser("letterread", prog=sub_progs.get("letterread"), help="learned Greek letter reader for a 2D image, with null, control-map and orientation controls")
    p.add_argument("image", help=".npy, .npz, .tif, .png, .jpg or zarr (ink bright by default)")
    p.add_argument("--weights", required=True,
                   help="a released model name such as letters-v2-ccby (downloaded once, SHA-256 checked; a name is "
                        "looked up before any file of that name), or a linenet-v1 .npz path")
    p.add_argument("--key", help=".npz: array name (default: the first); zarr: array path or OME-Zarr level (default: "
                                 "level 0, full resolution); pixel values are then in that level's pixels")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="read only these rows and columns; every row, box and --lines value is then relative to Y0, X0")
    p.add_argument("--letter-px", type=float,
                   help="letter height in image pixels, at least 4 (default: estimated from the line pitch, with a "
                        "scale search; the read stops when the image shows no line pitch)")
    p.add_argument("--letter-mm", type=float, help="letter height in millimetres; needs --um-per-px")
    p.add_argument("--um-per-px", type=float, help="pixel size in micrometres (with --letter-mm)")
    p.add_argument("--max-mpx", type=float, default=64,   # letterread.MAX_PIXELS / 1e6; letterread needs numpy
                   help="pixel budget in millions of pixels: a bigger image is block-averaged while it loads "
                        "(default %(default)g)")
    p.add_argument("--polarity", choices=["bright", "dark", "auto"], default="bright",
                   help="bright: ink brighter than the ground, as in ink maps (default); dark: dark ink on a light "
                        "ground, as in photographs; auto: read quickly both ways and keep the polarity whose letters "
                        "stand further above its nulls")
    p.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0,
                   help="turn the image this many degrees clockwise before reading (after --mirror); boxes stay in "
                        "input pixels")
    p.add_argument("--mirror", action="store_true", help="flip the image left to right before reading")
    p.add_argument("--deskew", type=float, default=6.0, metavar="MAX_DEG",   # letterread.DESKEW_DEG
                   help="largest line tilt searched, degrees either way (default %(default)g; 0 turns deskew off)")
    p.add_argument("--lines", type=float, nargs="+",
                   help="centre rows of the lines in image pixels (in the turned image with --rotate or --mirror), "
                        "each its row at the image's horizontal middle, which the deskew turns about (give --deskew 0 "
                        "for level bands); default: found")
    p.add_argument("--columns", default="auto", help="auto (split at empty vertical gutters, default), off, or a number of columns")
    p.add_argument("--nulls", type=int, default=4, help="tile-shuffle and phase-randomised controls (default 4, at most 64)")
    p.add_argument("--control", metavar="MAP_REVERSE",
                   help="a second map of the same surface on the same grid, such as its reverse-depth ink map: read on "
                        "the image's lines at the same letter size and confidence floor; the status needs the image "
                        "to keep more than 3 times its letters for strong")
    p.add_argument("--min-letters", type=int, default=10,   # letterread.MIN_LETTERS
                   help="fewest confident letters a read or a column needs before its controls can pass (default "
                        "%(default)s; fewer is status too_few)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--p-min", type=float, help="letter confidence floor (default: set from the nulls, at least 0.5)")
    p.add_argument("--lm", help="letter language model .npz (python -m kit greeklm build); reported beside the ink-only decode")
    p.add_argument("--lm-weight", type=float, default=0.5,   # letterread.LM_WEIGHT
                   help="weight of the language model in its decode (default %(default)g)")
    p.add_argument("--beam", type=int, default=32)
    p.add_argument("--no-orientation", action="store_true", help="skip the mirrored and turned reads")
    p.add_argument("--out", help="also write the full result as JSON")
    p.add_argument("--csv", metavar="OUT.csv",
                   help="also write one row per letter: column, line, index, letter, p, kept and its box in the image "
                        "file's pixels (the crop's Y0 and X0 added)")
    p.add_argument("--page-xml", metavar="OUT.xml",
                   help="also write PAGE XML (2019 schema): a TextRegion per column, a TextLine per line, a Glyph per "
                        "letter with its confidence, in the image file's pixels; marked as model output")
    p.add_argument("--overlay", help="also write a PNG of the image with the letters drawn on it (needs Pillow)")
    p.add_argument("--overlay-max-side", type=int, default=4000,
                   help="longest side of the overlay image in pixels (default 4000); the JSON records its scale")
    p.add_argument("--quiet", action="store_true", help="no progress messages on stderr")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_letterread)

    p = sub.add_parser("letterlines", prog=sub_progs.get("letterlines"), help="training lines for the letter reader from your own transcribed lines, "
                                           "and scores on lines kept apart")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("build", help="records (JSON or CSV: image, text, y, letter_px, optional x0, x1, crop, key, "
                                         "polarity, split, id) to LINES.npz, as finetune_maps.py trains on")
    a.add_argument("records", help="a .json or .csv records file; relative image paths are relative to its folder")
    a.add_argument("--out", metavar="LINES.npz", help="the training lines to write")
    a.add_argument("--dry-run", action="store_true", help="check every record and print what would be cut; decode no "
                                                          "image and write nothing")
    a.add_argument("--split", help="keep only records whose split is this label (such as train or test)")
    a.add_argument("--preview", metavar="PNG", help="also write the first 100 bands, each above its text (needs Pillow)")
    a.add_argument("--max-mpx", type=float, default=64,   # letterread.MAX_PIXELS / 1e6
                   help="pixel budget for loading an image, as in letterread (default %(default)g)")
    a.add_argument("--quiet", action="store_true", help="no progress messages or warnings on stderr")
    a = actions.add_parser("score", help="character error of one or more models on the lines of a LINES.npz, such "
                                         "as lines kept apart from fine-tuning")
    a.add_argument("lines", help="LINES.npz (letterlines build --split test, say)")
    a.add_argument("--weights", action="append", required=True,
                   help="a released model name or a linenet-v1 .npz; repeat to compare models (the first is the "
                        "reference for the differences)")
    a.add_argument("--out", help="also write the result as JSON")
    a.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_letterlines)

    p = sub.add_parser("letterdemo", prog=sub_progs.get("letterdemo"),
                       help="offline check of the letter reader: synthetic Greek capitals and a noise image, "
                            "DEMO PASS or DEMO FAIL")
    p.add_argument("--weights", default="letters-v2-ccby",   # letterread.DEFAULT_WEIGHTS; letterread needs numpy
                   help="a released model name (downloaded once, SHA-256 checked) or a linenet-v1 .npz path "
                        "(default %(default)s)")
    p.add_argument("--out", help="folder for demo.json and, with Pillow, demo-page.png and demo-overlay.png")
    p.add_argument("--json", action="store_true", help="print the numbers as JSON instead of the report")
    p.add_argument("--quiet", action="store_true", help="no progress messages on stderr")
    p.set_defaults(func=cmd_letterdemo)

    p = sub.add_parser("greeklm", help="letter n-gram language model for Greek in scriptio continua")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("build", help="fit Kneser-Ney letter n-grams on TEI XML texts (e.g. PerseusDL canonical-greekLit)")
    a.add_argument("out", help="model .npz (keep it out of git)")
    a.add_argument("tei", nargs="+")
    a.add_argument("--order", type=int, default=5)
    a = actions.add_parser("score", help="bits per letter of a Greek string under a model")
    a.add_argument("model")
    a.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_greeklm)

    p = sub.add_parser("releases", help="the list of tools released from private work, and the README section made from it")
    releases.add_arguments(p)
    p.set_defaults(func=releases.run)

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


_PARSERS = {}


def _parser(prog="python -m kit", sub_progs=None):
    """build_parser, built once per (prog, sub_progs) in a process: it is over a thousand
    add_argument calls, and pipelines and tests call main() many times in one process."""
    key = (prog, tuple(sorted((sub_progs or {}).items())))
    if key not in _PARSERS:
        _PARSERS[key] = build_parser(prog, sub_progs)
    return _PARSERS[key]


def _parse(parser, argv):
    # deep-copy the namespace so a command that mutates a list default (default=[]) cannot
    # leak it into the next call, exactly as with a freshly built parser
    return copy.deepcopy(parser.parse_args(argv))


def main(argv=None, prog="python -m kit", sub_progs=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser(prog, sub_progs)
    # Python 3.10 argparse mishandles a trailing nargs="*" after wrapper options.
    # Parse the wrapper separately, leaving every child flag and literal intact.
    if argv[:1] == ["run"] and "--" in argv:
        split = argv.index("--")
        args = _parse(parser, argv[:split])
        if args.action == "local":
            args.cmd.extend(argv[split + 1:])
        else:
            args = _parse(parser, argv)
    else:
        args = _parse(parser, argv)
    return _run(args, f"{prog} {args.command}", args.command)


def _run(args, typed, name):
    """args.func(args), with the command line the user typed and its kit command in kit.verify.RUNNING while it
    runs, so a missing dependency's install hint names the command actually run."""
    before = verify.RUNNING
    verify.RUNNING = (typed, name)
    try:
        return args.func(args)
    finally:
        verify.RUNNING = before


def _console(script, argv=None):
    """Run the one command of a console script in CONSOLE_SCRIPTS, with its usage and errors under the script's name."""
    command = CONSOLE_SCRIPTS[script]
    parser = build_parser(sub_progs={command: script})
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    args = commands.choices[command].parse_args(sys.argv[1:] if argv is None else argv)
    return _run(args, script, command)


def workbench_main(argv=None):
    """Console script scrolls-workbench: every command of python -m kit."""
    return main(argv, prog="scrolls-workbench")


def letterread_main(argv=None):
    """Console script scrolls-letterread: python -m kit letterread."""
    return _console("scrolls-letterread", argv)


def letterlines_main(argv=None):
    """Console script scrolls-letterlines: python -m kit letterlines."""
    return _console("scrolls-letterlines", argv)


def letterdemo_main(argv=None):
    """Console script scrolls-letterdemo: python -m kit letterdemo."""
    return _console("scrolls-letterdemo", argv)
