"""Agent tools for steps the VC3D tutorial leaves to a person: seed_check (is a seed on the surface prediction
and on papyrus), phantoms (prediction over empty CT), frame (which scan and frame a mesh is in), trim (drop the
parts of a surface over empty CT), volume_meta (the meta.json VC3D wants next to a local volume), merge_patch
(stitch a patch into a surface, on a copy) and merge_surfaces (the N-surface merge, in a work folder).
Self-intersections are already in check_surface. The numerical work is in kit/vc3d_prep.py, imported only when
a tool runs, so the CLI stays standard-library.

kit.vc3d_agent calls register(itself) at import. trace calls check_seed
before growing from an explicit seed.
"""

import math


def _volume(agent, ctx, location, what):
    from . import vc3d_audit, vc3d_region
    loc = location if agent.is_url(location) else str(agent.existing(ctx, location, what, "zarr"))
    try:
        return vc3d_region.Volume(loc)
    except (vc3d_region.RegionError, vc3d_audit.AuditError) as exc:
        raise agent.ToolError(f"{what} {location}: {exc}") from exc


def check_seed(agent, ctx, volume, seed, threshold=None, radius=8, ct=None, ct_radius=12, horizon=False):
    """The seed_check result for one seed; ToolError when a volume cannot be read."""
    if agent.vc3d_io.numpy_or_none() is None:
        raise agent.ToolError("seed_check needs numpy")
    from . import vc3d_audit, vc3d_prep, vc3d_region
    pred = _volume(agent, ctx, volume, "volume")
    ctv = _volume(agent, ctx, ct, "ct") if ct else None
    try:
        return vc3d_prep.seed_check(pred, seed, threshold=vc3d_prep.SURFACE_THRESHOLD if threshold is None
                                    else threshold, radius=radius, ct=ctv, ct_radius=ct_radius,
                                    horizon=horizon)
    except (vc3d_prep.PrepError, vc3d_audit.AuditError, vc3d_region.RegionError) as exc:
        raise agent.ToolError(f"seed check: {exc} (seed_check false skips the check)") from exc


def _ring_padded(agent, child, dest):
    """vc_merge_patch finds the child's rim by a distance transform to its invalid cells, and the grid's own
    edge does not count, so a child valid out to its edge has no rim and is refused ("child border is empty").
    When any edge cell is valid, write a copy with one ring of invalid cells (-1) around it to dest and return
    dest; otherwise return None."""
    import array
    import shutil
    io = agent.vc3d_io
    rasters = {a: io.read_tiff(child / f"{a}.tif") for a in "xyz"}
    h, w = rasters["x"].h, rasters["x"].w
    xs = rasters["x"].floats()
    edge = [xs[c] for c in range(w)] + [xs[(h - 1) * w + c] for c in range(w)]
    edge += [xs[r * w] for r in range(h)] + [xs[r * w + w - 1] for r in range(h)]
    if all(v == -1 for v in edge):
        return None
    shutil.copytree(child, dest, ignore=shutil.ignore_patterns("*.tif"))
    for a, ras in rasters.items():
        vals = ras.floats()
        out = array.array("f", [-1.0] * ((h + 2) * (w + 2)))
        for r in range(h):
            out[(r + 1) * (w + 2) + 1:(r + 1) * (w + 2) + 1 + w] = array.array("f", vals[r * w:(r + 1) * w])
        io.write_tiff(dest / f"{a}.tif", io.Raster(h + 2, w + 2, "f32", out))
    return dest


def catalog_candidates(agent, cat, src, scales):
    """Frame candidates from the open-data catalog for a mesh that may be in volume src (URL or id): src at each
    scale, then src through every stored transform out of it, in the target volume."""
    from . import vc3d_catalog
    hit = (vc3d_catalog.volume_for_url(cat, src) if agent.is_url(src)
           else vc3d_catalog.volume_by_id(cat, str(src).rstrip("/").split("/")[-1].split("-")[0]))
    if not hit or not hit[1].get("url"):
        raise agent.ToolError(f"{src} is not an open-data volume in the catalog")
    sample, row = hit
    out = [{"volume": row["url"], "scale_segmentation": s, "label": f"{row['volume']} x{s:g}"} for s in scales]
    for t in vc3d_catalog.transforms(cat, sample, row["volume"]):
        dest = vc3d_catalog.volume_by_id(cat, t["to"])
        if dest and dest[1].get("url") and t.get("matrix_xyz"):
            out.append({"volume": dest[1]["url"], "affine": t["matrix_xyz"],
                        "label": f"{row['volume']} -> {t['to']} (catalog matrix)"})
    return out


def villa_json(text):
    """The document villa's JSON parser (nlohmann) reads from text: a leading UTF-8 byte order mark is skipped;
    NaN and Infinity are refused, and so is a number that overflows a double (1e400), as nlohmann refuses them
    (parse_error 101, out_of_range 406); a whole number past the 64-bit range is read as a double, as nlohmann
    does. ValueError when villa would not parse it."""
    import json
    import math

    def refuse(word):
        raise ValueError(f"{word} is not JSON")

    def real(text):
        v = float(text)
        if not math.isfinite(v):
            raise ValueError(f"number overflow parsing {text[:20]!r}")
        return v

    def whole(text):
        n = int(text)
        return n if -2 ** 63 <= n < 2 ** 64 else real(text)
    return json.loads(text[1:] if text.startswith("\ufeff") else text, parse_constant=refuse, parse_float=real,
                      parse_int=whole)


def villa_refuses(name, text, level0=None):
    """Why villa's local Volume would refuse this meta.json or metadata.json (its text), or None when it opens.
    Volume::loadMetadata (core/src/Volume.cpp 1027-1067) reads meta.json and turns to metadata.json only when
    there is none. A metadata.json without a "scan" object is refused (1037-1040); its "scan" is merged into its
    root, and its format is "zarr" when it names none (1044-1048). Either must then have type "vol" and uuid,
    width, height and slices, which the constructor reads as integers (1016-1018). zarrOpen opens nothing unless
    format is the string "zarr" (1154-1155), and checks level 0's shape against those sizes, with padding of less
    than one chunk allowed (1146-1150, 1232-1263); level0 is kit.vc3d_audit's header for it (shape, chunks), None
    to skip that."""
    try:
        doc = villa_json(text)
    except ValueError:
        return f"{name} is not JSON"
    if not isinstance(doc, dict):
        return f"{name} is not a JSON object"
    if name == "metadata.json":
        if "scan" not in doc:
            return "metadata.json has no 'scan' key"
        if not isinstance(doc["scan"], dict):
            return "metadata.json's 'scan' is not an object"
        doc = {"format": "zarr", **doc, **doc["scan"]}
    if doc.get("type") != "vol":
        return f"{name} has type {doc.get('type')!r}, not 'vol'"
    missing = [k for k in ("uuid", "width", "height", "slices") if k not in doc]
    if missing:
        return f"{name} lacks {', '.join(missing)}"
    sizes = []
    for k in ("slices", "height", "width"):
        if not isinstance(doc[k], (int, float)) or not math.isfinite(doc[k]):
            return f"{name}: {k} {doc[k]!r} is not a number"
        sizes.append(int(doc[k]))
    if "format" not in doc:
        return f"{name} has no format: VC3D opens no zarr level from it, so it finds no level 0"
    if not isinstance(doc["format"], str):
        return f"{name}'s format {doc['format']!r} is not a string: VC3D throws on it"
    if doc["format"] != "zarr":
        return f"{name} has format {doc['format']!r}, not 'zarr': VC3D opens no zarr level from it"
    if level0 is not None:
        shape, chunks = [int(v) for v in level0["shape"][-3:]], [int(v) for v in level0["chunks"][-3:]]
        if not all(s >= e and s - e < max(1, c) for s, e, c in zip(shape, sizes, chunks)):
            return f"{name} gives slices, height, width {sizes}, but level 0's shape is {shape}"
    return None


VOXEL_KEYS = ("voxelsize", "voxel_size_um", "voxelSizeUm", "pixel_size_um", "pixelSizeUm", "resolution_um")


def _villa_number(v):
    """villa's asNumber (core/src/VoxelSizeMetadata.cpp 44-66): a number, or a string that holds only one, never
    a boolean; None otherwise."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and "_" not in v:
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _positive(v):
    n = _villa_number(v)
    return n if n is not None and math.isfinite(n) and n > 0 else None


def _walk(doc, *keys):
    for k in keys:
        if not isinstance(doc, dict) or k not in doc:
            return None
        doc = doc[k]
    return doc


def villa_voxel_size(doc):
    """The voxel size in um villa resolves from a metadata.json (its parsed document, before "scan" is merged),
    or None, when villa warns and uses 0. A port of voxelSizeFromStoreMetadata (core/src/VoxelSizeMetadata.cpp
    190-242), which Volume::loadMetadata applies (Volume.cpp 1043-1049, 67-82): a positive number, or a string
    holding one, at a root voxel size key, then at scan.voxelsize, then the acquisition record
    (tomo.acquisition.detector.samplePixelSize in mm, under scan or at the root), then the record of the volume a
    derived store was made from (source.metadata, scaled by 2 to the power source.resolution)."""
    def detector(root, level):
        for keys in (("scan", "tomo"), ("tomo",)):
            mm = _positive(_walk(root, *keys, "acquisition", "detector", "samplePixelSize"))
            if mm is not None:
                um = mm * 1000.0 * 2 ** level
                return um if math.isfinite(um) and um > 0 else None
        return None
    if not isinstance(doc, dict):
        return None
    for k in VOXEL_KEYS:
        if k in doc and _positive(doc[k]) is not None:
            return _positive(doc[k])
    scan = doc.get("scan")
    if isinstance(scan, dict) and _positive(scan.get("voxelsize")) is not None:
        return _positive(scan["voxelsize"])
    direct = detector(doc, 0)
    if direct is not None:
        return direct
    source = doc.get("source")
    if _walk(source, "metadata") is None or "resolution" not in source:
        return None
    level = _villa_number(source["resolution"])
    if level is None or not 0 <= level <= 31 or level != int(level):
        return None
    return detector(source["metadata"], int(level))


def register(agent):
    tool, STR, INT, NUM, BOOL, ARR = agent.tool, agent.STR, agent.INT, agent.NUM, agent.BOOL, agent.ARR
    ToolError = agent.ToolError

    @tool("seed_check", "Check a seed", "Is a seed point on the surface prediction, and on papyrus rather than "
          "air? The tutorial has a person pick the seed on the prediction overlay; the tracer itself only prints "
          "the value at an explicit seed and grows from it anyway. Reads the prediction at level 0 around the "
          "seed: the trilinear value against the tracer's own threshold (128, as its random seeds use), and the "
          "nearest voxel at or above it within radius. With ct, the CT value at the seed against the midpoint "
          "of its box's 10th and 90th percentiles (0 is air: outside the scan or its mask). trace runs the same "
          "check before growing from a seed.",
          {"volume": STR("surface prediction zarr (path or http/s3 URL)"),
           "seed": ARR("x, y, z in level-0 voxels", {"type": "number"}, minItems=3, maxItems=3),
           "threshold": NUM("prediction value that counts as on the surface (default 128)"),
           "radius": INT("voxels either side of the seed to search for the prediction (default 8)", minimum=1,
                         maximum=64),
           "ct": STR("CT volume in the same voxel frame (path or URL), for the papyrus or air check"),
           "ct_radius": INT("voxels either side of the seed for the CT box (default 12)", minimum=2, maximum=64),
           "horizon": BOOL("also triage the growth horizon (villa PR #2047's shells: SEED_VOID, SPARSE_REGION, "
                           "TRAPPED, HEALTHY, plus an edge flag); report only, reads a 65-voxel box (default "
                           "false)")},
          required=["volume", "seed"], readonly=True, openworld=True)
    def h_seed_check(ctx, a):
        return check_seed(agent, ctx, a["volume"], a["seed"], a.get("threshold"), a.get("radius", 8), a.get("ct"),
                          a.get("ct_radius", 12), a.get("horizon", False))

    @tool("trim", "Trim a surface over empty CT", "Copy a tifxyz surface with every vertex over CT value 0 "
          "(outside the scan, or outside a masked volume's mask) made invalid, plus dilate grid cells around "
          "them, then crop the copy to its valid cells with vc_tifxyz_trim when that tool is there. A render "
          "over CT zeros is blank there whatever the ink, so trim before ink or a blank-map judgment. The "
          "original is never changed.",
          {"surface": STR("tifxyz folder"),
           "ct": STR("CT volume the surface's coordinates are in (path or http/s3 URL)"),
           "level": INT("CT pyramid level to test (default 0; a coarser level reads less)", minimum=0),
           "scale_segmentation": NUM("multiply the surface coordinates first, as render does (default 1)"),
           "dilate": INT("grid cells to drop around each empty one (default 0)", minimum=0, maximum=64),
           "crop": BOOL("crop the copy to its valid cells with vc_tifxyz_trim (default true)"),
           "out": STR("folder for the trimmed copy (default work/vc3d/trims/<surface>-<time>/<surface>)")},
          required=["surface", "ct"], background=True, openworld=True)
    def h_trim(ctx, a):
        if agent.vc3d_io.numpy_or_none() is None:
            raise ToolError("trim needs numpy")
        from . import vc3d_audit, vc3d_prep, vc3d_region
        started = agent.now()
        surface = agent.existing(ctx, a["surface"], "surface", "tifxyz")
        ct = _volume(agent, ctx, a["ct"], "ct")
        if a.get("out"):
            out = agent.out_dir(ctx, a["out"])
        else:
            out = agent.out_dir(ctx, None, "trims", f"{agent.slug(surface.name)}-{agent.stamp()}") / surface.name
        try:
            res = vc3d_prep.trim_over_zero(surface, ct, out, level=a.get("level", 0),
                                           scale_segmentation=a.get("scale_segmentation", 1.0),
                                           dilate=a.get("dilate", 0))
        except (vc3d_prep.PrepError, vc3d_audit.AuditError, vc3d_region.RegionError,
                agent.vc3d_io.IOFormatError) as exc:
            raise ToolError(str(exc)) from exc
        res["ct"] = str(ct)
        res["missing_chunks"] = ct.missing
        steps = []
        tools = ctx.tools(required=False) if a.get("crop", True) else None     # crop false needs no VC3D tool
        if a.get("crop", True) and res["kept_vertices"] and tools is not None and tools.has("vc_tifxyz_trim"):
            log = out.parent / f"{out.name}-trim.log"
            argv = [str(out)]
            rc, seconds = agent.run_logged(ctx, tools.argv("vc_tifxyz_trim", *argv), log,
                                           env=agent.vc3d.headless_env(ctx.env, threads=1), timeout=1800)
            steps.append({"argv": argv, "exit": rc, "seconds": seconds})
            res["crop"] = {"exit": rc, "log": str(log)}
        elif a.get("crop", True):
            res["crop"] = {"skipped": "no vertex kept" if not res["kept_vertices"] else
                           "vc_tifxyz_trim not found; the copy keeps the full grid"}
        if res["trimmed_fraction"] > 0.5:
            res["note"] = "over half the surface lies over empty CT: check the surface's frame and scale first"
        res["receipt"] = agent.write_receipt(ctx, out.parent, "trim", a, steps, [str(out)], started)
        return res

    @tool("phantoms", "Flag phantom prediction", "Find phantom surface prediction: voxels at or above the "
          "threshold where the CT reads 0 (outside the scan or its mask), so no papyrus lies under them. Patchwise "
          "inference blends across the mask edge, so phantoms are expected in a one-chunk halo around the CT "
          "(about 15% of PHercParis4 m7's prediction chunks, none beyond, by herculaneum-scroll-tools' count). "
          "The scan counts in cells of one level-0 prediction chunk at any level, and flags each cell holding "
          "phantoms edge (CT in the cell), halo (CT one cell away) or beyond (no CT within a cell, which a blend "
          "halo cannot explain: check the two volumes share a frame). Do not seed a trace in halo or beyond cells; "
          "trim a surface grown there. The prediction and CT must have levels on one voxel grid. Read only.",
          {"volume": STR("surface prediction zarr (path or http/s3 URL)"),
           "ct": STR("CT volume the prediction was made from (path or URL)"),
           "level": INT("prediction level to scan (default: the finest with at most max_chunks chunks)", minimum=0),
           "box": ARR("[[z0, z1], [y0, y1], [x0, x1]] at that level (default the whole level)",
                      {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                      minItems=3, maxItems=3),
           "threshold": NUM("prediction value that counts as surface (default 128, the tracer's)"),
           "max_chunks": INT("refuse a scan over this many chunks (default 4096)", minimum=1)},
          required=["volume", "ct"], readonly=True, background=True, openworld=True)
    def h_phantoms(ctx, a):
        if agent.vc3d_io.numpy_or_none() is None:
            raise ToolError("phantoms needs numpy")
        from . import vc3d_audit, vc3d_prep, vc3d_region
        pred = _volume(agent, ctx, a["volume"], "volume")
        ct = _volume(agent, ctx, a["ct"], "ct")
        cap = a.get("max_chunks", 4096)
        level = a.get("level")
        if level is None:
            level = len(pred.levels) - 1
            for k in range(len(pred.levels)):
                m = pred.levels[k]["meta"]
                if math.prod(-(-int(s) // int(c)) for s, c in zip(m["shape"][-3:], m["chunks"][-3:])) <= cap:
                    level = k
                    break
        elif level >= len(pred.levels):
            raise ToolError(f"level {level}: the prediction has {len(pred.levels)} levels")
        try:
            res = vc3d_prep.phantom_scan(pred, ct, level=level, box=a.get("box"),
                                         threshold=a.get("threshold", vc3d_prep.SURFACE_THRESHOLD), max_chunks=cap)
        except (vc3d_prep.PrepError, vc3d_audit.AuditError, vc3d_region.RegionError) as exc:
            raise ToolError(f"phantoms: {exc}") from exc
        res.update(volume=str(pred), ct=str(ct), missing_chunks={"prediction": pred.missing, "ct": ct.missing})
        return res

    @tool("frame", "Pick a surface's frame", "Which scan and coordinate frame does a mesh belong to? A mesh "
          "in the wrong frame (another scan, a binned copy, a mirrored older scan) renders beside its sheet with "
          "no error. Scores each candidate frame the way check_surface scores seating, but without rendering: "
          "up to `points` vertices from a central window of the grid are mapped into the candidate (scale, then "
          "an affine when given), the CT is sampled along each normal, and the center layer must be brighter "
          "than the layers a gap away. Candidates come from `candidates`, from `volumes` times `scales`, and, "
          "with catalog_from, from the open-data catalog: that volume at each scale plus every stored transform "
          "out of it (the 2023 Paris 4 scans are mirror images of the 2026 ones, so their matrices have negative "
          "determinants). The best frame is called clear only when its score is at least 1.5 times the "
          "runner-up's; a mesh that seats nowhere is reported as such. Read only.",
          {"surface": STR("tifxyz folder"),
           "candidates": ARR("frames to score: {volume, scale_segmentation, affine (3x4 or 4x4 xyz), label}",
                             {"type": "object"}),
           "volumes": ARR("volumes (path or URL) to score at each of scales", {"type": "string"}),
           "scales": ARR("scale_segmentation values for volumes and catalog_from (default 1, 2, 4, 0.5, 0.25)",
                         {"type": "number"}),
           "catalog_from": STR("open-data volume (URL or id) the mesh may be in: scores it at scales and through "
                               "every catalog transform out of it"),
           "level": INT("CT level to sample (default: the coarsest with voxels of at most 10 um)", minimum=0),
           "half_layers": INT("layers either side (default about 280 um of them; 30 when the size is unknown)",
                              minimum=3, maximum=200),
           "window": INT("grid cells square round the center to draw points from (default 48)", minimum=4),
           "points": INT("at most this many points (default 3000)", minimum=50, maximum=20000)},
          required=["surface"], readonly=True, background=True, openworld=True)
    def h_frame(ctx, a):
        if agent.vc3d_io.numpy_or_none() is None:
            raise ToolError("frame needs numpy")
        from . import vc3d_audit, vc3d_catalog, vc3d_prep, vc3d_region
        surface = agent.existing(ctx, a["surface"], "surface", "tifxyz")
        scales = a.get("scales") or list(agent.FRAME_CANDIDATES)
        cands = [dict(c) for c in a.get("candidates") or []]
        for c in cands:
            if not c.get("volume"):
                raise ToolError("each candidate needs a volume")
        for v in a.get("volumes") or []:
            cands += [{"volume": v, "scale_segmentation": s} for s in scales]
        if a.get("catalog_from"):
            try:
                cat = vc3d_catalog.load(ctx.home / "cache")
            except vc3d_catalog.CatalogError as exc:
                raise ToolError(str(exc)) from exc
            cands += catalog_candidates(agent, cat, a["catalog_from"], scales)
        if len(cands) < 2:
            raise ToolError("give at least two candidate frames (candidates, volumes or catalog_from)")
        try:
            pts, normals, centre = vc3d_prep.surface_points(surface, a.get("window", 48), a.get("points", 3000))
        except (vc3d_prep.PrepError, agent.vc3d_io.IOFormatError) as exc:
            raise ToolError(str(exc)) from exc
        vols, rows = {}, []
        for c in cands:
            key = c["volume"]
            if key not in vols:
                vols[key] = _volume(agent, ctx, key, "volume")
                vols[key].voxel_um = agent._voxel_for(ctx, key)
            vol = vols[key]
            level = a.get("level")
            if level is None:
                level = vol.coarsest_within(10.0) if vol.voxel_um else 0
            eff = vol.level_um(level) if vol.voxel_um else None
            half = a.get("half_layers") or (min(200, max(3, math.ceil(280 / eff))) if eff else 30)
            ctx.say(f"frame: {c.get('label') or key + ' x' + format(c.get('scale_segmentation', 1.0), 'g')}")
            try:
                row = vc3d_prep.frame_score(vol, level, pts, normals, scale=float(c.get("scale_segmentation", 1.0)),
                                            affine=c.get("affine"), half=half)
            except (vc3d_audit.AuditError, vc3d_region.RegionError, ValueError) as exc:
                row = {"score": -1.0, "error": str(exc)}
            row.update(volume=key, level=level, half_layers=half, voxel_um=eff,
                       **({"label": c["label"]} if c.get("label") else {}))
            rows.append(row)
        order, best = vc3d_prep.rank_frames(rows)
        ranked = [rows[i] for i in order]
        per_volume = {}
        for key in dict.fromkeys(r["volume"] for r in rows):
            mine = [r for r in rows if r["volume"] == key]
            if len(mine) > 1:
                o, b = vc3d_prep.rank_frames(mine, key="score")
                per_volume[key] = {"best": mine[o[0]].get("label") or f"x{mine[o[0]]['scale_segmentation']:g}",
                                   "clear": b["clear"], "why": b["why"]}
        res = {"surface": str(surface), "grid_centre_row_col": centre, "points": len(pts), "best": ranked[0],
               "clear": best["clear"], "why": best["why"], "candidates": ranked,
               "note": ("seating is an interpretation of brightness; compare frames, do not trust one number. Across "
                        "scans the ranking uses relative_score (contrast over the scan's own spread); raw score "
                        "compares frames of one volume only (per_volume)")}
        if per_volume:
            res["per_volume"] = per_volume
        return res

    @tool("volume_meta", "Write a volume's meta.json", "Write the meta.json VC3D reads next to a local zarr "
          "volume (a surface prediction, say) that has none. Without it VC3D makes one up with voxel size 0, so "
          "the tracer cannot apply min_area_cm and the app's volume package does not list the volume. Takes the "
          "shape from level 0's header (or the bare array's) and the voxel size given. An existing meta.json or "
          "metadata.json is never changed. VC3D reads meta.json first, so a metadata.json it refuses (no 'scan' "
          "key, as the published surface predictions have, no format 'zarr', or sizes that are not level 0's) "
          "gets a meta.json beside it; one it opens is left alone, with a note when it gives no voxel size. The "
          "result says what is there and why VC3D refuses it.",
          {"volume": STR("local OME-Zarr folder (or bare zarr array)"),
           "voxel_um": NUM("level 0 voxel size in um", exclusiveMinimum=0),
           "name": STR("volume name (default the folder's name)")},
          required=["volume", "voxel_um"])
    def h_volume_meta(ctx, a):
        import json
        import uuid
        from . import vc3d_audit
        vol = agent.existing(ctx, a["volume"], "volume", "zarr")
        try:
            store = vc3d_audit.open_store(str(vol))
            levels, _ = vc3d_audit.levels(store)
            head, unread = (levels[0]["meta"] if levels else None), "no readable level 0 header"
        except vc3d_audit.AuditError as exc:
            head, unread = None, str(exc)
        res = {"volume": str(vol)}
        for existing in ("meta.json", "metadata.json"):
            if (vol / existing).is_file():
                text = (vol / existing).read_text()
                why = villa_refuses(existing, text, head)
                res["existing"] = existing
                if why:
                    res["villa_refuses"] = why
                if existing == "meta.json" or not why:
                    try:
                        res["meta"] = villa_json(text)
                    except ValueError:
                        res["meta"] = None
                    if why:   # VC3D reads meta.json first; this tool never changes it
                        res["note"] = ("VC3D refuses this volume until its meta.json is fixed by hand, or removed "
                                       "and volume_meta run again")
                    elif existing == "metadata.json" and villa_voxel_size(res["meta"]) is None:
                        res["note"] = ("VC3D opens this metadata.json but finds no voxel size in it (no positive "
                                       "voxelsize at its root or under scan, no acquisition or source record), so "
                                       "it may use 0 and the tracer cannot apply min_area_cm. This tool leaves a "
                                       "metadata.json VC3D opens alone: write a meta.json beside it by hand, with "
                                       "the voxel size, if the volume needs one")
                    return dict(res, written=False)
                break
        agent.writable(ctx, vol / "meta.json")
        if head is None:
            raise ToolError(f"{vol}: {unread}")
        slices, height, width = (int(v) for v in head["shape"][-3:])
        meta = {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, str(vol.resolve()))), "name": a.get("name") or vol.name,
                "type": "vol", "format": "zarr", "width": width, "height": height, "slices": slices,
                "voxelsize": float(a["voxel_um"]), "min": 0.0, "max": 255.0}
        (vol / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
        if "existing" in res:
            res["note"] = "metadata.json is left as it is; VC3D reads meta.json first, so it no longer reads it"
        return dict(res, written=True, meta=meta)

    @tool("merge_patch", "Merge a patch into a surface", "Stitch a small child surface into a parent with "
          "vc_merge_patch: the child's rim is aligned to the parent (RANSAC similarity, then a thin-plate warp), "
          "blended over blend_cells and its interior replaces the parent there. Anchors come only from the "
          "rim, so keep border_cells narrower than the distance from the child's edge to the part being "
          "replaced; a child valid to its grid edge gets a ring of invalid cells first (villa sees no rim "
          "otherwise). vc_merge_patch overwrites the parent in place, so this tool first copies the parent to out and merges into the copy; neither input "
          "changes. Check the result with check_surface before using it.",
          {"parent": STR("tifxyz folder to patch (copied, never changed)"),
           "child": STR("tifxyz folder whose border overlaps the parent"),
           "border_cells": INT("child rim width in cells used for anchors (default 16)", minimum=1),
           "blend_cells": INT("blend ramp width in parent cells (default 6)", minimum=0),
           "seed": INT("RANSAC seed (default 1, so a rerun gives the same surface; 0 is nondeterministic)",
                       minimum=0),
           "out": STR("folder for the merged copy (default work/vc3d/merges/<parent>-<time>/<parent>)")},
          required=["parent", "child"], background=True)
    def h_merge_patch(ctx, a):
        import shutil
        tools = ctx.tools()
        if not tools.has("vc_merge_patch"):
            raise ToolError(f"vc_merge_patch is not in {tools.bindir}")
        started = agent.now()
        parent = agent.existing(ctx, a["parent"], "parent", "tifxyz")
        child = agent.existing(ctx, a["child"], "child", "tifxyz")
        if parent.resolve() == child.resolve():
            raise ToolError("parent and child are the same surface")
        if a.get("out"):
            out = agent.writable(ctx, a["out"])
            if out.exists():
                raise ToolError(f"{out} exists; give a new folder")
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out = agent.out_dir(ctx, None, "merges", f"{agent.slug(parent.name)}-{agent.stamp()}") / parent.name
        shutil.copytree(parent, out)
        try:
            padded = _ring_padded(agent, child, out.parent / f"{child.name}-ring" / child.name)
        except (agent.vc3d_io.IOFormatError, OSError) as exc:
            raise ToolError(f"child {child}: {exc}") from exc
        argv = ["--parent", str(out), "--child", str(padded or child), "--border-cells", str(a.get("border_cells", 16)),
                "--blend-cells", str(a.get("blend_cells", 6)), "--ransac-seed", str(a.get("seed", 1))]
        log = out.parent / f"{out.name}-merge.log"
        rc, seconds = agent.run_logged(ctx, tools.argv("vc_merge_patch", *argv), log,
                                       env=agent.vc3d.headless_env(ctx.env), timeout=3600)
        res = {"exit": rc, "seconds": seconds, "parent": str(parent), "child": str(child), "out": str(out),
               "log": str(log), "log_tail": agent.tail(log, 15)}
        if padded:
            res["child_ring"] = (f"{padded}: the child is valid to its grid edge, which vc_merge_patch does not "
                                 "count as a rim, so it ran on a copy with one ring of invalid cells added")
        if rc == 0:
            try:
                res["surface"] = agent.tifxyz_stats(out)
            except (agent.vc3d_io.IOFormatError, OSError, KeyError) as exc:
                res["surface"] = {"error": str(exc)}
        res["receipt"] = agent.write_receipt(ctx, out.parent, "merge_patch", a,
                                             [{"argv": argv, "exit": rc, "seconds": seconds}], [str(out)], started)
        return res

    @tool("merge_surfaces", "Merge a grid of surfaces", "Merge several overlapping tifxyz surfaces into one with "
          "vc_merge_tifxyz (per-edge overlap and anchors, RANSAC similarity, a joint affine, a thin-plate warp per "
          "surface, distance-transform blend). Give the surfaces as a grid in rows, the way they sit side by side "
          "(null for a gap); neighbors in the grid are the edges it aligns, and the grid must be connected. The "
          "tool builds the volume-package layout the villa tool wants (merge.json and a paths folder of links to "
          "the inputs) in a work folder, so no input changes. Check the result with check_surface.",
          {"rows": ARR("grid of tifxyz folders, row-major; null for an empty cell",
                       {"type": "array", "items": {"type": ["string", "null"]}}, minItems=1),
           "ref": STR("folder name of the reference surface (default: the one with most valid cells)"),
           "out": STR("work folder (default work/vc3d/merges/<first>-<time>)"),
           "timeout": INT("seconds (default 6 h)", minimum=1)},
          required=["rows"], background=True)
    def h_merge_surfaces(ctx, a):
        import json
        tools = ctx.tools()
        if not tools.has("vc_merge_tifxyz"):
            raise ToolError(f"vc_merge_tifxyz is not in {tools.bindir}")
        started = agent.now()
        grid, by_name = [], {}
        for row in a["rows"]:
            names = []
            for cell in row:
                if cell is None:
                    names.append(None)
                    continue
                p = agent.existing(ctx, cell, "surface", "tifxyz")
                if p.name in by_name and by_name[p.name] != p.resolve():
                    raise ToolError(f"two surfaces share the folder name {p.name}; the villa tool names them by it")
                by_name[p.name] = p.resolve()
                names.append(p.name)
            grid.append(names)
        if len(by_name) < 2:
            raise ToolError("merge_surfaces needs at least two surfaces")
        first = min(by_name)
        out = agent.out_dir(ctx, a.get("out"), "merges", f"{agent.slug(first)}-{agent.stamp()}")
        paths = out / "paths"
        paths.mkdir(parents=True, exist_ok=True)
        for name, src in by_name.items():
            link = paths / name
            if not link.exists():
                link.symlink_to(src, target_is_directory=True)
        (out / "merge.json").write_text(json.dumps({"rows": grid}, indent=1))
        before = {p.name for p in paths.iterdir()}
        argv = ["--merge", str(out / "merge.json"), "--paths-dir", str(paths)]
        if a.get("ref"):
            argv += ["--ref", a["ref"]]
        log = out / "merge.log"
        rc, seconds = agent.run_logged(ctx, tools.argv("vc_merge_tifxyz", *argv), log,
                                       env=agent.vc3d.headless_env(ctx.env), timeout=a.get("timeout", 6 * 3600))
        made = sorted(p for p in paths.iterdir() if p.name not in before and p.is_dir() and not p.is_symlink())
        res = {"exit": rc, "seconds": seconds, "out": str(out), "grid": grid, "log": str(log),
               "log_tail": agent.tail(log, 15), "merged": [str(p) for p in made]}
        surfaces = []
        for p in made:
            try:
                surfaces.append(agent.tifxyz_stats(p))
            except (agent.vc3d_io.IOFormatError, OSError, KeyError) as exc:
                surfaces.append({"path": str(p), "error": str(exc)})
        res["surfaces"] = surfaces
        if rc == 0 and not made:
            res["note"] = "the merge exited 0 but wrote no surface under paths/; read the log"
        res["receipt"] = agent.write_receipt(ctx, out, "merge_surfaces", a,
                                             [{"argv": argv, "exit": rc, "seconds": seconds}],
                                             [str(p) for p in made], started)
        return res
