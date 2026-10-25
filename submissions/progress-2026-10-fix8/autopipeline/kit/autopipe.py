"""AutoPipeline, the automatic pipeline: from a released CT scan to checked surfaces, renders and ink maps with no
person in between. `python -m kit autopipeline` and the agent tool `autopipeline` run it (`autopipe`, its name
before 9 Oct 2026, still works for both); see a note of the source repository.

Scanning itself happens at a beamline and is not software we run. The pipeline starts from what the organizers
release: the CT volume, its surface prediction and its normal grids in the open-data bucket. Each stage below
replaces a step the VC3D tutorial or our own docs left to a person, or connects two tools that had to be called
one at a time:

  acquire    resolve the scan, its surface prediction and normal grids from the catalog, or a prediction and
             grids the plan names from outside it (external_prediction: checked against the scan's shape and
             level when the plan is made, and against the headers it froze here); check the zarr headers
  umbilicus  the catalog's scroll axis, or one estimated from the published normal grids with villa's
             vc_gen_umbilicus, outliers dropped by a fixed rule (tool `umbilicus`); measured against the
             catalog's axes on three scrolls in a note of the source repository; or, with source centerlines, the scan's line
             from the published center lines dataset (kit/centerlines.py)
  seeds      seed points on the prediction, inside a radial band around the axis, on papyrus, spaced apart,
             checked like `seed_check` (tool `seeds`); a published segment can replace seeds and trace
  trace      vc_grow_seg_from_seed from every seed (tool `trace`)
  qa         a fixed acceptance rule per surface: grid sanity, self-intersections, normal sign, seating at
             several windows, the winding audit (sheet switches) and VC3D's own validity rules
  flatten    vc_flatten (ABF++) on accepted surfaces, kept only when its measured distortion passes the plan's
             limits (tool `distortion`); otherwise the unflattened surface goes on, measured against the same
             limits, and the record says so (a warning when it fails; refused at render under strict)
  render     a chunk audit of the volume under the surface, then the team-order render (tool `render`); a surface
             over too many missing chunks is refused, or, with render.trim, trimmed to the scanned part (tool
             `trim`) and the copy rendered when it keeps enough area and passes its own audit
  ink        each planned model with the reverse and shuffle controls (tool `ink`), or, where this machine has
             no model or GPU, a job file for the Modal runner (a script of the source repository)
  score      benchmark runs on labeled segments: pixel AUC with the reverse map as control (kit auc); with
             score.transfer, the run's own traces on labels carried from published labeled segments by 3D
             proximity (kit labelxfer, carried at render before any map exists), with reverse, shuffled and
             displaced controls and the published segment's map on the same pixels
  report     one summary with every stage's record, and a provenance digest over it; with the optional triage,
             each accepted surface's ink maps scored by kit rowscore (Bullo27's text-row periodicity score), the
             reverse and shuffled maps beside, and the surfaces ranked: a reading order, not a verdict

Rules kept (AGENTS.md): outputs go under work/ or experiments/ only; a target run needs a ledger experiment
fixed before any map exists, and its outputs go under experiments/<slug>/; every ink map comes with its
reverse control; nothing goes outward and Modal runs only where the user has set KIT_ALLOW_MODAL=1. The plan is
frozen when the run starts (its digest is in every record), so the thresholds that accept or reject a surface
cannot move after a result is seen. Every surface, map and score here is model output, not a reading.

numpy only where a stage computes (umbilicus smoothing, seeds, distortion); the CLI imports with the standard
library.
"""

import hashlib
import http.client
import json
import math
import os
import random
import shutil
import struct
import sys
import time
from pathlib import Path

from . import apstackcheck, axispolish, centerlines, kithome, qareasons, tracebudget, vc3d_catalog, vc3d_io, vc3d_orient

PLAN_VERSION = 2                 # 2: the trace reads normal grids, seeds can be given, a prediction's level is kept
READ_VERSIONS = (1, 2)           # plans a run folder may hold; a version 1 plan traced with no normal grids
STAGES = ("acquire", "umbilicus", "seeds", "trace", "bench", "qa", "flatten", "render", "ink", "score", "report")
SURFACE_THRESHOLD = 128          # the tracer's own seed threshold (kit/vc3d_prep.py)

DEFAULTS = {
    "purpose": "benchmark",
    "experiment": None,
    "volume": None,              # catalog volume id; default: the scan nearest 9 um that has a surface prediction
    "prediction": None,          # surface prediction model id; default m7 (20260413222639) when published
    "segment": None,             # a published segment id: replaces seeds and trace (labeled benchmarks)
    "umbilicus": {"source": "auto", "every": 500, "repeats": 3, "seed": 1, "window": 5, "max_jump_um": None},
    "seeds": {"count": 4, "z_range": None, "radius_um": [1500.0, None], "level": 4, "min_spacing_um": 2000.0,
              "seed": 0, "max_planes": 24, "ct_check": True, "points": None},
    "trace": {"generations": 60, "min_area_cm": 0.0, "threads": None, "timeout": 3 * 3600,
              "normal_grids": "auto", "params": {}},
    "qa": {"windows": 5, "min_valid_fraction": 0.5, "require_seated": "all", "max_selfcross": 0,
           "windaudit": "auto", "wind_pitch": None, "validity": True, "published": "record",
           "require_data_term": True},
    "flatten": {"enabled": True, "iterations": 10, "downsample": 1, "max_p95_stretch": 0.25,
                "max_shear_deg_p95": 20.0, "min_area_ratio": 0.8, "max_area_ratio": 1.25},
    "render": {"preset": "9um", "audit": True, "format": "zarr", "max_missing": 0.05},
    # ink.models: Reader v2 since 15 Oct 2026 (ink_9um seed 42 before). Through this chain on published PHerc0841
    # w00 it beat seed 42 by 0.127 in whole-map AUC and d9v2 matched it within 0.002 (Model output, development
    # data; the README's results). A plan that names its models keeps them; one that does not now resolves Reader
    # v2, so its plan and digest differ from one made before. Upright canvases (ink.orient, in OPTIONAL) stay opt in
    "ink": {"models": ["reader-v3"], "variants": ["f", "r", "s"], "where": "auto"},
    "score": {"inner": 64},
}
QA_SEATED = ("all", "any", "none")
QA_PUBLISHED = ("record", "gate")      # a published segment's checks: recorded only, or the same gate as a trace
QA_WIND = ("auto", "required", "off")   # auto: a patch too small for the audit to fit a winding pitch (under about
                                        # one turn) is recorded as not audited; one of a turn or more that it fits
                                        # no pitch to is not audited, with a warning (rejected under
                                        # strict.windaudit_unfit); any other audit failure rejects
TRACE_GRIDS = ("auto", "required", "off")   # the catalog's normal grids for the trace: when published (auto), always
                                            # (required: a plan without them is refused), or never (off)
FREE_SETTINGS = ("trace.params",)           # settings taken as given: extra tracer parameters (z_min, z_max, ...)
# Settings a plan holds only when it asks for them. They are not in DEFAULTS, so a plan that does not use them (and
# every plan made before they existed) keeps its content and its digest. A value given is merged over these
# defaults (true takes them as they are; null or false leaves the setting out) and stored whole, so the digest
# covers every threshold the run decides by.
OPTIONAL = {
    # a surface prediction and its normal grids from outside the catalog (a local folder or an https or s3 URL,
    # such as kit surfacepred's packaged output): replaces the catalog's; see resolve_external
    # box: a box prediction (kit surfacepred over one box) holds sheets only inside its box, so seeds and traces are
    # kept inside it (Run.box): "auto" takes the box from the prediction's run.json when it has one, "off" never
    # bounds, or a box "z0:z1,y0:y1,x0:x1" in level-0 voxels. Seeds keep seed_margin voxels inside it; the tracer
    # is bounded by its own x_min to z_max at the box (villa e0bbb8b core/src/GrowPatch.cpp 3522-3527, 4889-4892);
    # an axis estimated from the plan's grids reads axis_slices slices inside the box (s_umbilicus)
    "external_prediction": {"zarr": None, "normal_grids": None, "box": "auto", "seed_margin": 16,
                            "axis_slices": 9},
    # a surface the chunk audit refuses is trimmed to the scanned part and the copy rendered, when the copy keeps
    # at least min_area_share of the area and its own audit passes render.max_missing (Run.trim_for_render)
    "render.trim": {"min_area_share": 0.5, "dilate": 1, "level": 2},
    # Checks added on 9 Oct 2026, after plans had been frozen. A plan without this setting records what they find
    # as a warning, so its acceptance rule decides as it did; each one true here rejects instead.
    # windaudit_unfit: a patch of a turn or more to which the winding audit fits no pitch (meshqa's concentration
    # test: a crushed sheet, an axis off the core, or not one winding) is rejected at qa (Run.qa_one).
    # render_distortion: a surface that goes to render unflattened and fails the flatten limits, or could not be
    # measured, is refused at render (Run.render_distortion); a published segment is measured, never refused.
    "strict": {"windaudit_unfit": True, "render_distortion": True},
    # Score the run's own traced surfaces on labels carried from published labeled segments (kit/labelxfer.py):
    # after render, each accepted trace's canvas gets every listed segment's labels where the two surfaces are
    # within max_gap_vox and their normals within max_normal_deg; score then scores each model's forward,
    # reverse and shuffled maps on them, and the forward map on the labels displaced displace_mm in four
    # directions. A trace with less than min_area_cm2 of carried labels is recorded as not scorable. references
    # names, per segment, "run" (render and ink the published segment in this run too, surface ref-<key>) or
    # {model: path} (a map of it from the same reader), scored on the same carried pixels and compared by a
    # paired block bootstrap (kit auc's). Thresholds: a note of the source repository
    "score.transfer": {"segments": None, "max_gap_vox": 4.0, "max_normal_deg": 30.0, "min_area_cm2": 0.25,
                       "displace_mm": 2.0, "lattice_px": 4, "references": None,
                       "bootstrap": {"draws": 2000, "block_px": 107, "seed": 20261009}},
    # Trace each seed this many times with the same settings (added 10 Oct 2026: the tracer does not give the same
    # surface twice, a note of the source repository, "Dry run"). A whole number; with more
    # than 1 the surfaces are t00-r0, t00-r1, ... in launch order (seed by seed, repeats in turn), with 1 or absent
    # t00, t01, ... as before
    "trace.repeats": 1,
    # Settings of an ink recipe (docs/plans/2026-10-09-autopipeline-bars.md, stage 1), so that one recipe is one plan.
    # render.snap: each accepted surface is moved along its normals before its chunk audit and render (kit snap;
    # a note of the source repository): onto the plan's surface prediction (source pred: Nieuwlaar's snap_meshes.py, with
    # max_off, threshold, jump, sigma, level) or onto the CT band midline (source ct: RectoRefine's midline at
    # kit snap's defaults, the run's umbilicus giving the outward sense); with source ct, "mode": "face" snaps with
    # kit snap --mode face instead (the band face snap) onto "target" recto (the face toward the umbilicus, the
    # default), mid or verso; mode and target are absent unless given (OPTIONAL_EXTRA). check: kit snap --check against
    # check_reference (snapped: the snap of the unmoved surface, for a surface that does not sit on a sheet;
    # original: the input) must pass with both its controls caught or the surface is not rendered (required), is
    # recorded only (record), or is not run (off). sham: the control arm, every vertex moved by minus its snap
    # displacement (kit snap --sham). The snapped grid must keep the input's shape and valid vertices, and a
    # benchmark segment's render the published surface volume's shape, or the render is refused (Run.snap_one).
    "render.snap": {"source": "pred", "check": "required", "check_reference": "snapped", "sham": False,
                    "max_off": 15, "threshold": 1.0, "jump": 6.0, "sigma": 1.0, "level": 0},
    # ink.layers: every planned model reads each [start, stop) window of the rendered layers (the ink tool's
    # layers; villa center-crops a longer window to its own depth); with more than one window the maps of each
    # variant are combined by kit ensemble (combine: mean or rank), as Nieuwlaar's z-window ensemble (windows
    # 0:20 3:23 5:25 8:27 on 28 layers, docs/tricks.md). ink.ensemble: the planned models' maps of each variant
    # combined into one more map (kit ensemble, method mean or rank; or kit inkensemble, method zscore: the PHerc.
    # 343 winner's z-score ensemble, with the optional keys robust, combine, trim and weights), scored as the model
    # "ensemble".
    "ink.layers": {"windows": [[6, 23]], "combine": "mean"},
    "ink.ensemble": {"method": "mean"},
    # Repair instead of only rejecting (Run.repair_one): a trace qa rejects for a sheet switch (transverse
    # self-intersections, or full-turn or broad fusions in the winding audit) is cut back to its seed's winding by
    # kit switchfix (the repository's switch repair on real traces, a note of the source repository; it cuts, it does not mend,
    # and it fails its own planted test: a note of the source repository). The cut copy is checked again by the same qa rule and
    # replaces the trace only when it passes and keeps at least min_area_share of the trace's area (VC3D's
    # area). The trace itself is kept unchanged beside it. method: barrier (the default since 22 Oct 2026, the
    # owner's decision: `kit switchfix barrier` keeps the seed's part under kit.sheetgap's contact barrier, chosen on
    # development data) or switchfix (`kit switchfix repair`, the method before)
    "qa.repair": {"method": "barrier", "min_area_share": 0.5},
    # Region crop instead of whole-trace rejection (added 21 Oct 2026, kit/regioncrop.py; development and test in
    # a note of the source repository). selfcross_per_cm2: the self-intersection test becomes a rate,
    # transverse crossings per cm2 of the trace (VC3D's area at the plan's voxel size), calibrated on published
    # meshes, in place of qa.max_selfcross (null keeps max_selfcross). A trace qa still rejects for its
    # self-intersections, its seating or the winding audit (decided, not unmeasured) is then cut by kit meshqa crop
    # (Run.crop_one): both quads of every located crossing grown by dilate cells, jump edges of the plan's
    # prediction, and every piece more than max_off_share off that prediction rejected whole (kit/regioncrop.py's
    # frozen settings). Optional, and off by default because on published windings they cut clean surface:
    # seating ("check": cut check_surface's windows that are not seated; "grid": tiles of window_cells quads on the
    # plan's CT) and off-sheet blobs of at least off_min_cells vertices. Every piece of at least min_area_cm2 (and
    # at least trace.min_area_cm) is written under cropped/<sid>/ as a VC3D tifxyz, checked again by the same qa
    # rule (check_surface on the piece), and each that passes joins the run as surface <sid>-rNN. The trace itself
    # stays rejected, with the crop on its record.
    "qa.crop": {"selfcross_per_cm2": 65.0, "dilate": 2, "max_off_share": 0.30, "min_area_cm2": 0.05,
                "seating": "off", "window_cells": 10, "off_min_cells": None},
    # Edge extension (added 23 Oct 2026, Run.extend_one): an accepted trace of the run is grown past its edges by
    # villa's vc_extend_edge (VC3D Manual Add's edge extension walked along structure tensor sheet normals; fork
    # branch vc3d-auto-extend), `rounds` rounds of `cells` vertices on each of `sides`. normals: "prediction" (the
    # plan's surface prediction, the default) or "ct" (the scan). It has no stop rule. The grown copy is checked again by the same qa rule and
    # replaces the trace (kept at surface_before_extend) only when it passes; otherwise the trace stands as it was.
    "qa.extend": {"sides": ["up", "down", "left", "right"], "cells": 10, "rounds": 8, "normals": "prediction",
                  "timeout": 7200},
    # Triage (added 13 Oct 2026): at report, each accepted surface's ink maps scored with kit rowscore (Bullo27's
    # text-row periodicity score): each planned model's forward map and the mean of the models' forward maps, and the
    # same for the reverse and shuffled maps as controls. Surfaces are ranked by the forward score of the mean, so a
    # person looks first at the maps with the most row structure; a reading order, not a verdict (Run.triage).
    # method: rowscore (the only one so far)
    "triage": {"method": "rowscore"},
    # Crackle Check (added 23 Oct 2026): at report, each accepted surface's ink maps judged by Crackle Check's
    # control-set gate (kit/crackle.py, ink-lens-gate-v1, the rule of the public Space SharpMeow/crackle-check): the
    # mean of the planned models' forward maps against the mean of their reverse-depth maps, over the papyrus of the
    # render's middle layer, on the whole surface and in tiles of tile_px (640, the size the rule was checked at).
    # Each surface gets the Space's answer (Yes, Maybe, No signal found, Too small) and a kept-ink overlay; a check
    # that can fail, not a reading (Run.crackle).
    # rule: ink-lens-gate-v1 (the only one so far)
    "crackle": {"rule": "ink-lens-gate-v1", "tile_px": 640},
    # Upright canvases (added 13 Oct 2026): at ink, each accepted trace's render is turned in plane so that +z runs
    # down the rows, as on published segments (the layout the released readers were trained on), the planned
    # models read the turned render (forward, reverse and shuffled alike), and each map is taken back to the
    # render's own canvas with the inverse turn (kit canvasorient, a note of the source repository; Run.orient_one). The
    # angle comes from the rendered tifxyz alone (no labels, no map) and is applied only when the canvas passes
    # min_consistency and min_vertical and the normal vote is clear; otherwise the trace is inked as rendered
    # and the record says why. order: 1 bilinear, 0 nearest. Published segments are never turned.
    # method: upright (the only one so far)
    "ink.orient": {"method": "upright", "min_consistency": 0.9, "min_vertical": 0.5, "order": 1},
    # Axis backends (added 15 Oct 2026, kit/apbackends.py; the plan setting `backends` writes these). estimator: what
    # makes the axis when the plan estimates one: villa (vc_gen_umbilicus on the normal grids, as before), centrenet
    # (our scroll center finder on CT slices, scripts/umbilicus, release umbilicus-v1) or normals (kit normalaxis on
    # the normal grids, numpy only); a list is tried in order, and the record says which ran and why the others did
    # not. shadow: backends also run on the same scan (catalog among them) and measured against the axis the run uses
    # (axis_distance); recorded only, never used downstream, so swapping the axis backend can be judged before it is
    # swapped. Absent: villa alone and no shadow, as before
    "umbilicus.estimator": "villa",
    "umbilicus.shadow": [],
    # Coverage polish of an estimated axis (added 22 Oct 2026, kit/axispolish.py): one slice every `every`, the axis
    # point moved to the highest winding coverage within 8 mm on the scan's published normal grids, then robust_axis.
    # Never applied to a catalog or given line (people's). Without grids, numpy or 2 polished slices the estimate is
    # kept as it was and the record says why. It was tested on the centre finder's line only (a
    # frozen test of the source repository).
    # version: the polish rule (axispolish.VERSION)
    "umbilicus.polish": axispolish.DEFAULTS,
    # Published center lines (added 23 Oct 2026, kit/centerlines.py): with umbilicus.source "centerlines" the axis is
    # the scan's line from the dataset SharpMeow/vesuvius-center-lines at the pinned revision, the first source of
    # `prefer` that has one, its sha256 checked against kit/data/centerlines.json. All 22 prize-eligible scans have
    # one; a scan with none is refused unless umbilicus.estimator names a fallback, and only that estimate is ever
    # polished. Chase, 23 Oct 2026: released tools are wired into AutoPipeline
    "umbilicus.centerlines": centerlines.DEFAULTS,
    # Trace budgets and partial surfaces (added 18 Oct 2026, kit/tracebudget.py, a note of the source repository). On fresh
    # scrolls AutoPipeline's traces ran into a timeout fixed per plan and kept nothing: villa saves a trace only at
    # its end. With this setting each trace writes its whole surface every snapshot_interval generations (villa's
    # snapshot-interval), is given a time budget from a cost model of seconds per vertex (at least trace.timeout and
    # at most max(max_s, trace.timeout), unless a work deadline, KIT_AUTOPIPE_DEADLINE, leaves less: then the first
    # repeat of every seed shares what is left before any second repeat, and a trace whose share is too small is
    # deferred), passes time_limit_s to a tracer built with a villa patch of the source repository so it stops at a
    # generation boundary and saves, and sets VC_GRID_CACHE_BYTES from the machine's memory and the generations. A
    # trace stopped by its limit, AP's timeout or a cancel keeps its last complete surface as a partial result
    # (state["partial_traces"], kinds in tracebudget.PARTIAL_KINDS), which qa checks like any other surface; a
    # container lost mid-trace leaves its snapshot to the restart (preempted); a signal kit did not send is an
    # infrastructure failure. generations is never lowered to fit the time: it shapes the trace (villa sizes its work
    # grid and its generation-8 solve from it). The trace tool's plans only: a trace method runs its own loop.
    # Absent, a plan traces as before. Nothing adds it on its own: a plan names it, the plan action adds it when
    # asked (new_defaults, NEW_PLAN_DEFAULTS), and kit run all (kit/autobatch.py) names it for every scan
    "trace.budget": tracebudget.DEFAULTS,
    # Stack check (added 23 Oct 2026, Chase: released tools are wired into AutoPipeline): at report, public Scrolls'
    # kit stackcheck over the accepted traces, ordered by median distance from the run's umbilicus
    # (kit/apstackcheck.py, Run.stackcheck). Its order and coincident-pair checks mean the same on any traces; the
    # stack checks assume consecutive windings, so the record keeps them apart. Optional, off unless given; needs
    # public Scrolls' kit/stackcheck.py (SCROLLS_PUBLIC_ROOT or ../Scrolls), else the report says it was not run.
    "stackcheck": apstackcheck.DEFAULTS,
}
# Optional settings the plan action (the autopipeline tool and `kit autopipe plan`) adds to a plan when asked with
# new_defaults (--new-defaults), under settings that do not name them (null leaves one out): the recommended settings
# for a new plan on a fresh scroll: budgets and partial surfaces, and the polished centre finder for the axis. Opt in,
# never on its own (review of 18 Oct 2026):
# preregistered and scripted callers (preregistered comparisons, the frozen specs'
# documented `kit autopipe plan` digest checks, an approved kit run all batch) must get exactly the plan their
# settings describe. Not added to a target plan (its preregistration fixes its recipe: AGENTS.md rule 3, so it names
# trace.budget itself), a published segment's plan (it traces nothing) or a plan with a trace method.
# Since 22 Oct 2026 (the owner's decision of that day) also the axis: our scroll centre
# finder first, villa's estimator when the finder cannot run (no torch, a scan outside 8 to 10 um or off the bucket),
# and the coverage polish on whichever estimate is used, only where the plan's umbilicus.source is auto or estimate
# and the plan names neither estimator nor polish. A catalog axis still comes first under source auto
NEW_PLAN_DEFAULTS = {"trace.budget": True, "umbilicus.estimator": ["centrenet", "villa"], "umbilicus.polish": True}
# Upright canvases stay opt in: a check of them as the default, on 15 Oct 2026, read NO-GO by its rule fixed before
# the run. On our trace t00-r2 of PHerc0841 w00 the turn raised Reader v2's AUC on the carried labeled pixels from
# 0.851 to 0.911 (d9v2 0.846 to 0.896), but for Reader v2 it did not beat a sham turn 45 degrees off upright (0.872;
# upright minus sham 0.039, 95% interval -0.005 to 0.091). The turn also raised the reversed controls, Reader v2's
# from 0.476 to 0.709 and d9v2's from 0.464 to 0.567. Development pixels and one trace, Model output.
# fallback "unturned", asked for with an object ({"fallback": "unturned"}): a trace whose turn fails (kit canvasorient
# cannot measure or apply it, for one, without numpy, tifffile and zarr in kit's own Python) is inked as rendered,
# the failure kept in its orient record and on its maps, rather than left uninked as without it
ORIENT_FALLBACKS = ("unturned",)
# Keys a plan may add to an optional object beyond OPTIONAL's own settings, kept only when given: so a plan can ask for
# the fallback with an object of its own, and the settings of a plan that holds ink.orient merge again to themselves
# render.snap's mode, target and per_vertex are kept as given, so a snap plan that names none of them keeps its
# digest: mode midline (RectoRefine, the default for source ct) or face (kit snap --mode face, technique D), and with
# face the target recto (the band face toward the scroll axis, the default), mid or verso, and per_vertex true for
# kit snap --face-per-vertex (no jump rejection and no support rule).
OPTIONAL_EXTRA = {"ink.orient": ("fallback",), "render.snap": ("mode", "target", "per_vertex"),
                  # method zscore's options (kit inkensemble), kept only when given so other plans keep their digest
                  "ink.ensemble": ("robust", "combine", "trim", "weights")}
SNAP_MODES = ("midline", "face")
SNAP_TARGETS = ("recto", "mid", "verso")
# Trace methods: optional settings trace.<name> that replace the trace tool for each seed with a method of its own
# (a loop around it, say). An extension module (kit/autopipe_ext_*.py, loaded at the end of this module) registers
# one with register_trace_method; a plan that names a method this kit lacks is refused.
TRACE_METHODS = {}
# Tool actions: an extension module adds actions to the autopipeline agent tool and commands to `kit autopipeline`
# with register_actions; this kit's own actions are listed in register.
ACTION_EXTENSIONS = []
PLAIN_OPTIONAL = frozenset(OPTIONAL)     # the optional settings of this module, before any method adds its own
REPAIR_METHODS = ("barrier", "switchfix")
TRIAGE_METHODS = ("rowscore",)
ORIENT_METHODS = ("upright",)
TRIAGE_VARIANTS = ("f", "r", "s")       # forward, then the reverse and shuffled controls
TRIAGE_SOURCE = "https://github.com/Bullo27/first-letters-survey (analysis/rowscore.py, ported in kit/rowscore.py)"
TRIAGE_NOTE = ("A reading order, not a verdict: surfaces ranked by the row score of the mean of the planned models' "
               "forward maps (kit rowscore, after Bullo27's text-row periodicity score), with the reverse and shuffled "
               "maps scored beside as controls. A high score is a place to look, not ink: fibres and other repeating "
               "structure can score well, and a low score on a small surface proves little. Look at the maps. Model "
               "output, not a reading.")
TRIAGE_VERSION = 1                      # triage.json's scores are reused only from a record of this version
CRACKLE_RULES = ("ink-lens-gate-v1",)
CRACKLE_VERSION = 1                     # crackle.json's records are reused only from a record of this version
CRACKLE_NOTE = ("Crackle Check's answer for each surface: is the mean of the planned models' ink maps stronger than "
                "the same models run on the layers reversed (the control)? Yes at 3 or more times the control's share "
                "of pixels above its own 99th percentile, Maybe from 1.5 to 3, judged on the whole surface and in "
                "tiles. A Yes is a place to look, not text; a No does not prove there is no ink. Model output, not a "
                "reading.")
# The scrolls whose triage lists are public: those with published ink labels that AutoPipeline benchmarks on
# (BENCHMARKS, and kit surfbench's windings). Any other scroll's list, a target run's above all, is private
TRIAGE_PUBLIC = ("PHerc0139", "PHerc0841")
TRIAGE_PRIVATE = ("a triage list of a scroll without published labels, a target scroll's above all: it stays in this "
                  "run folder, which git ignores (under experiments/<experiment>/ for a target run), and is never "
                  "copied into a tracked folder or shown outside (AGENTS.md rule 1)")
SWITCH_REASONS = ("self-intersections: ", "winding audit: ")   # qa reasons a sheet switch gives (Run.qa_one)
MAX_REPEATS = 10
# What stopped a trace, a qa check, a render or a stage, as the readout of a note of the source repository
# reads it (its amendment of 10 Oct 2026): "ours" when AutoPipeline's own chain decided (the seed check refused the
# seed; the tracer exited non-zero, ran past trace.timeout or wrote no surface; a qa check that ran rejected the
# surface; the render was refused or exited non-zero; no seed, trace, surface or render was left), a FAIL;
# "infrastructure" for anything else (a fetch, the relay, a 404, a missing or unstartable tool, a qa rejection
# resting only on checks that could not run (Run.qa_one), a cancellation, a lost driver, a time limit, an error the
# code does not mark as ours), a VOID
FAILURE_KINDS = ("ours", "infrastructure")
# Labeled surfaces that stay unscored here: 0841-ag405 is the ink bar's report surface, scored once by one frozen
# recipe (docs/plans/2026-10-09-autopipeline-bars.md, section 1). PHerc0139's report windings (w043, w044, w047 to
# w059) are not labeled segments and cannot be named here.
REPORT_ONLY = {"0841-ag405": "the ink bar's report surface, scored once by one frozen recipe; its labels are never "
                             "read here"}
SNAP_CHECKS = ("required", "record", "off")
ENSEMBLE_METHODS = ("mean", "rank")
MODEL_ENSEMBLE_METHODS = ENSEMBLE_METHODS + ("zscore",)   # ink.ensemble only: zscore runs kit inkensemble
EXTERNAL_HEADERS = (".zgroup", ".zattrs", "meta.json", "metadata.json", "run.json")
LOCAL_OPEN_ONLY = ("metadata.json", "no meta.json", "meta.json")   # kit surfacepred check_package findings that
                                                                     # concern VC3D's local open only


class AutoError(ValueError):
    """A problem with a plan, an input or a stage that the caller can fix. kind, when given, is one of
    FAILURE_KINDS: who decided a stage's failure (the run records it; a stage error without one is
    "infrastructure")."""

    def __init__(self, message, kind=None):
        super().__init__(message)
        self.kind = kind


# The trace tool's own refusals of a seed (kit/vc3d_agent.py _trace): the only chain decisions it raises as an error;
# anything else it raises means it could not run
_SEED_REFUSED = ("is off the surface prediction", "is on air in the CT")


def trace_failure(exc=None, res=None, budget=None, min_area_cm=None):
    """{"kind", "reason"} for a seed that gave no surface: from the trace tool's error `exc`, or its result `res`
    when the tracer ran (FAILURE_KINDS). budget: the plan's trace.budget, under which a timeout says that the trace
    left no complete snapshot (a trace that left one is a partial surface, not a failure), a partial surface under
    min_area_cm is refused as villa refuses a small final save, and a signal kit did not send (the out-of-memory
    killer, an operator) is an infrastructure failure, retried on a rerun, with the snapshot left on disk."""
    if exc is not None:
        text = str(exc)
        if text.startswith("seed [") and any(k in text for k in _SEED_REFUSED):
            return {"kind": "ours", "reason": f"seed check refused it: {text}"[:600]}
        return {"kind": "infrastructure", "reason": f"the trace tool could not run: {text}"[:600]}
    rc = (res or {}).get("exit")
    stop = (res or {}).get("stop") or {}
    if budget is not None and stop.get("partial") and not budget.get("keep_partial", True):
        return {"kind": "ours", "reason": f"the trace stopped short ({stop.get('reason')}) and its partial surface "
                                          "was not kept: trace.budget.keep_partial is false"[:600]}
    if budget is not None and stop.get("partial") and Run.below_min_area(stop, {"min_area_cm": min_area_cm}):
        return {"kind": "ours", "reason": f"the trace stopped short ({stop.get('reason')}) with a partial surface of "
                                          f"{stop.get('area_cm2')} cm2, under trace.min_area_cm {min_area_cm} (villa "
                                          "applies it only at a normal end)"[:600]}
    if budget is not None and rc in tracebudget.KILL_SIGNALS:
        left = f"; its last snapshot is left at {stop['snapshot_left']}" if stop.get("snapshot_left") else ""
        return {"kind": "infrastructure", "reason": f"the tracer was killed by signal {-rc}, which kit did not send "
                                                    f"(possibly out of memory){left}; a rerun traces it again"[:600]}
    if rc == 0:
        return {"kind": "ours", "reason": "the tracer exited 0 but wrote no surface"}
    if isinstance(rc, int) and not isinstance(rc, bool):
        return {"kind": "ours", "reason": f"the tracer exited {rc}"}
    if rc == "timeout":
        if budget is not None:
            why = stop.get("no_snapshot") or "no snapshot"
            return {"kind": "ours", "reason": f"the tracer ran past its time budget and left no complete snapshot "
                                              f"({why})"[:600]}
        return {"kind": "ours", "reason": "the tracer ran past trace.timeout"}
    return {"kind": "infrastructure", "reason": f"the tracer did not run to an end: {rc}"[:600]}


def new_plan_settings(settings):
    """(settings, added): the given settings with NEW_PLAN_DEFAULTS put under them where they say nothing, and the
    names added. A target plan, a published segment's plan and a plan with a trace method get none."""
    s = json.loads(json.dumps(settings or {}))
    if not isinstance(s, dict) or s.get("purpose", DEFAULTS["purpose"]) == "target" or s.get("segment"):
        return s, []
    trace = s.get("trace", {})
    if not isinstance(trace, dict) or "trace.budget" in s:
        return s, []
    if any(k not in DEFAULTS["trace"] and f"trace.{k}" not in PLAIN_OPTIONAL for k in trace):
        return s, []        # a trace method (or an unknown setting, which make_plan refuses)
    added = []
    for key, value in NEW_PLAN_DEFAULTS.items():
        if not key.startswith("trace."):
            continue
        name = key.split(".", 1)[1]
        if name not in trace:
            trace[name] = value
            added.append(key)
    if added:
        s["trace"] = trace
    u = s.get("umbilicus", {})
    # the axis defaults go only to a plan that leaves the axis to AutoPipeline: source auto or estimate, no backends
    # shorthand for it, no external prediction (its grids may cover one box, too little for coverage), and neither
    # setting named (null names one: it stays out)
    if (isinstance(u, dict) and u.get("source", DEFAULTS["umbilicus"]["source"]) in ("auto", "estimate")
            and "umbilicus" not in (s.get("backends") or {}) and not s.get("external_prediction")):
        took = []
        for key, value in NEW_PLAN_DEFAULTS.items():
            name = key.split(".", 1)[1]
            if key.startswith("umbilicus.") and name not in u:
                u[name] = json.loads(json.dumps(value))
                took.append(key)
        if took:
            s["umbilicus"] = u
            added += took
    return s, added


def trace_sid(index, repeat, repeats):
    """The surface id of seed `index`'s trace number `repeat` (trace.repeats)."""
    return f"t{index:02d}" if repeats == 1 else f"t{index:02d}-r{repeat}"


def trace_entries(state):
    """Every planned trace in launch order, where it stands: [{"sid", "seed_index", "repeat", "accepted",
    "rendered", "failure"}], failure being None or {"stage", "kind", "reason"} for the step that stopped it (a run
    with nothing planned yet gives [], and a state from before plans were recorded gives its traces by name).
    Standard library only: kit labelxfer readout reads it from a state.json alone."""
    surfaces = state.get("surfaces") or {}
    planned = state.get("planned_traces")
    if planned is None:
        planned = [{"sid": sid, "seed_index": int(sid[1:3]) if sid[1:3].isdigit() else None, "repeat": 0}
                   for sid in sorted(surfaces) if sid.startswith("t")]
    failures = state.get("trace_failures") or {}
    stages = state.get("stages") or {}
    out = []
    for p in planned:
        sid = p["sid"]
        s = surfaces.get(sid)
        e = {"sid": sid, "seed_index": p.get("seed_index"), "repeat": p.get("repeat", 0), "accepted": None,
             "rendered": False, "failure": None}
        partial = (((s or {}).get("trace") or {}).get("stop") or {}).get("partial")
        if partial:
            e["partial"] = partial      # a partial surface (tracebudget.PARTIAL_KINDS), checked by qa like any other
        if s is None:
            f = failures.get(sid)
            if f is None:
                ran = (stages.get("trace") or {}).get("status")
                f = {"kind": "infrastructure", "reason": f"no record of this trace (the trace stage is {ran})"}
            if f.get("deferred"):
                e["deferred"] = True        # trace.budget: not run, for want of time or as a repeat that would stop short
            e["failure"] = {"stage": "trace", **f}
        elif "qa" not in s:
            e["failure"] = {"stage": "qa", "kind": "infrastructure",
                            "reason": f"not checked: the qa stage is {(stages.get('qa') or {}).get('status')}"}
        elif not s.get("accepted"):
            q = s["qa"]
            f = q.get("failure") or {"kind": "ours"}
            e.update(accepted=False, failure={"stage": "qa", "kind": f["kind"],
                                              "reason": "rejected by qa: " + "; ".join(q.get("reasons")
                                                                                       or ["not checked"])})
            # the failed checks with their measured values and thresholds, and any exception (kit/qareasons.py)
            e["failure"]["checks"] = qareasons.failed_checks(q)
            if q.get("exception"):
                e["failure"]["exception"] = q["exception"]
        else:
            e["accepted"] = True
            r = s.get("render") or {}
            if r.get("zarr"):
                e["rendered"] = True
            elif r.get("refused"):
                e["failure"] = {"stage": "render", "kind": "ours", "reason": f"not rendered: {r['refused']}"}
            elif r.get("failure"):
                e["failure"] = {"stage": "render", **r["failure"]}
            else:
                e["failure"] = {"stage": "render", "kind": "infrastructure", "reason":
                                f"not rendered: the render stage is {(stages.get('render') or {}).get('status')}"}
        out.append(e)
    return out


def _np():
    np = vc3d_io.numpy_or_none()
    if np is None:
        raise AutoError("this step needs numpy")
    return np


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


# ---------------------------------------------------------------- umbilicus

def grid_slices(n_slices, every, z_range=None):
    """Slice indices for an axis estimate: every `every`-th slice inside z_range ([z0, z1), default the scan)."""
    if every < 1:
        raise AutoError("umbilicus every must be at least 1")
    z0, z1 = (0, n_slices) if not z_range else (max(0, int(z_range[0])), min(n_slices, int(z_range[1])))
    if z1 <= z0:
        raise AutoError(f"empty z range {z_range} for a scan of {n_slices} slices")
    first = z0 + (every - z0 % every) % every
    return list(range(first, z1, every))


def _line_at(zs, vs, z):
    """Siegel's repeated-median line through (zs, vs), evaluated at z: robust to just under half the points
    being wrong, and exact on a straight axis, so an estimate is judged against its neighbors' trend."""
    n = len(zs)
    slopes = []
    for i in range(n):
        s = sorted((vs[j] - vs[i]) / (zs[j] - zs[i]) for j in range(n) if j != i and zs[j] != zs[i])
        if s:
            slopes.append(s[len(s) // 2] if len(s) % 2 else 0.5 * (s[len(s) // 2 - 1] + s[len(s) // 2]))
    if not slopes:
        return sorted(vs)[n // 2]
    slopes.sort()
    k = len(slopes)
    slope = slopes[k // 2] if k % 2 else 0.5 * (slopes[k // 2 - 1] + slopes[k // 2])
    icpt = sorted(v - slope * zz for zz, v in zip(zs, vs))
    b = icpt[n // 2] if n % 2 else 0.5 * (icpt[n // 2 - 1] + icpt[n // 2])
    return b + slope * z


def robust_axis(points, window=5, max_jump=None, floor=1.0):
    """Drop estimates that sit far from their neighbors along z. points: [(z, y, x)] in any order. Each point is
    compared with a robust line (Siegel's repeated median) through the `window` points nearest it in z, itself
    left out; a point farther from that line than max_jump, or by default than the median such distance plus 4
    robust deviations (1.4826 x MAD, at least `floor` voxels), is dropped. Returns (kept, dropped), each sorted
    by z, every dropped point with its distance."""
    pts = sorted((float(z), float(y), float(x)) for z, y, x in points)
    if len(pts) < 3:
        return pts, []
    k = max(2, min(int(window), len(pts) - 1))
    dist = []
    for i, (z, y, x) in enumerate(pts):
        near = sorted((j for j in range(len(pts)) if j != i), key=lambda j: (abs(pts[j][0] - z), j))[:k]
        zs = [pts[j][0] for j in near]
        ly = _line_at(zs, [pts[j][1] for j in near], z)
        lx = _line_at(zs, [pts[j][2] for j in near], z)
        dist.append(math.hypot(y - ly, x - lx))
    if max_jump is None:
        med = vc3d_io.percentile(sorted(dist), 50)
        mad = vc3d_io.percentile(sorted(abs(d - med) for d in dist), 50) * 1.4826
        limit = med + 4 * max(mad, floor)
    else:
        limit = float(max_jump)
    kept = [p for p, d in zip(pts, dist) if d <= limit]
    dropped = [{"z": p[0], "y": p[1], "x": p[2], "distance": round(d, 2)} for p, d in zip(pts, dist) if d > limit]
    return kept, dropped


def axis_distance(a, b, zs=None):
    """Horizontal distance between two axes ([(z, y, x)] control points, linear between them) at heights zs
    (default: the z of a's points inside b's z span). Returns {n, median, p95, max} in the points' units."""
    pa, pb = sorted(a), sorted(b)
    if zs is None:
        zs = [p[0] for p in pa if pb[0][0] <= p[0] <= pb[-1][0]] or [p[0] for p in pa]
    d = sorted(math.dist(vc3d_orient.centre_at(pa, z), vc3d_orient.centre_at(pb, z)) for z in zs)
    if not d:
        raise AutoError("no heights to compare the two axes at")
    return {"n": len(d), "median": round(vc3d_io.percentile(d, 50), 2), "p95": round(vc3d_io.percentile(d, 95), 2),
            "max": round(d[-1], 2)}


def download(url, dest, opener=None, tries=None, optional=False):
    """One object to dest with S3's false 404s retried (kit/s3retry.py); a real 404 raises, or returns False
    when optional."""
    import urllib.error
    import urllib.request
    from . import s3retry
    req = urllib.request.Request(url, headers={"User-Agent": "kit-autopipe"})
    kw = {"tries": tries} if tries else {}
    try:
        with s3retry.open_url(req, opener, timeout=120, **kw) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        # a key S3 kept answering with a false 404 (open_url's last try) is not missing: it raises like any failure
        if optional and exc.code == 404 and not s3retry.false_404(404, exc.read() or b""):
            return False
        raise AutoError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise AutoError(f"{url}: {getattr(exc, 'reason', exc)!s:.200} ({type(exc).__name__})") from exc
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = part_name(dest)
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


def part_name(dest):
    """A temporary name beside dest that no other process or thread uses. Workers that fetch the same object at
    once (a layer-separation run's extraction, 12 Oct 2026) shared dest.part: one renamed it away and the other's
    rename failed, or one truncated the file the other then renamed into place, so a reader saw part of it."""
    import threading
    dest = Path(dest)
    return dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.part")


def fetch_grids(grids_url, dest, slices, workers=16, opener=None):
    """The xy normal grids of the given slices (NNNNNN.grid, as villa's vc_gen_normalgrids writes them) and the
    folder's metadata.json when it has one, into dest, from a URL or a local folder. Files already there are
    kept. Returns (fetched, missing)."""
    import concurrent.futures
    base = str(grids_url).rstrip("/")
    local = None if "://" in base else Path(base)
    dest = Path(dest)
    (dest / "xy").mkdir(parents=True, exist_ok=True)

    def get(rel, to):
        if local is None:
            return download(f"{base}/{rel}", to, opener, optional=True)
        if not (local / rel).is_file():
            return False
        if (local / rel).resolve() != to.resolve():
            shutil.copyfile(local / rel, to)
        return True

    get("metadata.json", dest / "metadata.json")

    def one(z):
        f = dest / "xy" / f"{z:06d}.grid"
        if f.is_file() and f.stat().st_size:
            return z, True
        return z, get(f"xy/{z:06d}.grid", f)

    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
        got = list(pool.map(one, slices))
    return [z for z, ok in got if ok], [z for z, ok in got if not ok]


# the metadata fields VC3D's Umbilicus::LoadJsonFile reads to place a file in a volume's frame (villa ccb43181)
FRAME_METADATA = ("voxelsize_um", "volume", "volume_width", "volume_height", "volume_slices")


def umbilicus_json(points, provenance=None, metadata=None):
    """villa's control_points JSON (as vc_gen_umbilicus writes and Umbilicus::FromFile reads). metadata keeps the
    frame vc_gen_umbilicus stamped (FRAME_METADATA), so VC3D and `kit umbilicus export` need not guess it."""
    out = {"control_points": [{"x": x, "y": y, "z": z} for z, y, x in sorted(points)]}
    frame = {k: metadata[k] for k in FRAME_METADATA if isinstance(metadata, dict) and k in metadata}
    if frame:
        out["metadata"] = {**frame, "total_points": len(out["control_points"])}
    if provenance:
        out["kit_autopipe"] = provenance
    return out


# ---------------------------------------------------------------- distortion

def grid_distortion(surface, max_vertices=4_000_000):
    """How far a tifxyz surface's grid is from an isometric map of the plane. A tifxyz grid is a parameterization:
    neighboring grid points are meant to be one grid step (1 / meta scale voxels) apart on the surface. For each
    quad of four valid vertices this measures the 3D length of its row and column edges in grid steps (stretch;
    1 is isometric), the angle between them (shear; 0 is orthogonal) and its area in grid cells. A flattening
    that tears, folds or squeezes the sheet shows up here, and so does a trace whose step drifts. Returns
    medians, 95th percentiles, the mean cell area (area_ratio: the surface's 3D area over its area in grid cells)
    and the share of cells beyond 25 % stretch or 20 degrees shear."""
    np = _np()
    p = Path(surface)
    meta = json.loads((p / "meta.json").read_text()) if (p / "meta.json").is_file() else {}
    scale = meta.get("scale") or [None, None]
    # the size from x.tif's header, before any grid is decoded: an oversized grid is refused without first taking
    # 24 bytes a vertex for three float64 copies (it now runs on every surface that goes to render unflattened)
    try:
        info = vc3d_io.tiff_info(p / "x.tif")
    except (struct.error, IndexError, KeyError) as exc:     # as read_tiff reports a truncated or tagless file
        raise vc3d_io.IOFormatError(f"{p / 'x.tif'}: truncated TIFF ({exc!r})") from exc
    H, W = info["height"], info["width"]
    if H * W > max_vertices:
        raise AutoError(f"{p}: {H} x {W} grid is over {max_vertices} vertices; downsample first")
    X, Y, Z = (np.asarray(vc3d_io.read_tiff(p / f"{a}.tif").floats(), dtype=np.float64) for a in "xyz")
    X, Y, Z = X.reshape(H, W), Y.reshape(H, W), Z.reshape(H, W)
    valid = np.isfinite(X) & np.isfinite(Y) & np.isfinite(Z) & ~((X == -1) & (Y == -1) & (Z == -1)) & (Z > 0)
    if not (scale[0] and scale[1]):
        raise AutoError(f"{p}: meta.json has no grid scale")
    step_c, step_r = 1.0 / float(scale[0]), 1.0 / float(scale[1])
    q = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1]
    if not q.any():
        raise AutoError(f"{p}: no cell with three valid corners")
    P = np.stack([X, Y, Z], axis=-1)
    u = (P[:-1, 1:] - P[:-1, :-1])[q]
    v = (P[1:, :-1] - P[:-1, :-1])[q]
    lu = np.linalg.norm(u, axis=1) / step_c
    lv = np.linalg.norm(v, axis=1) / step_r
    cos = np.abs(np.einsum("ij,ij->i", u, v)) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1),
                                                         1e-12)
    shear = 90.0 - np.degrees(np.arccos(np.clip(cos, 0, 1)))
    area = np.linalg.norm(np.cross(u, v), axis=1) / (step_c * step_r)
    stretch = np.abs(np.log(np.concatenate([lu, lv])))

    def pct(a, k):
        return round(float(np.percentile(a, k)), 4)

    return {"surface": str(p), "grid": [H, W], "cells": int(q.sum()), "grid_step_voxels": [step_c, step_r],
            "valid_fraction": round(float(valid.mean()), 4),
            "stretch_col": {"median": pct(lu, 50), "p5": pct(lu, 5), "p95": pct(lu, 95)},
            "stretch_row": {"median": pct(lv, 50), "p5": pct(lv, 5), "p95": pct(lv, 95)},
            "abs_log_stretch": {"median": pct(stretch, 50), "p95": pct(stretch, 95)},
            "shear_deg": {"median": pct(shear, 50), "p95": pct(shear, 95)},
            "area_ratio": round(float(area.sum() / q.sum()), 4),
            "cells_over_25pct_stretch": round(float(((np.abs(np.log(lu)) > math.log(1.25)) |
                                                     (np.abs(np.log(lv)) > math.log(1.25))).mean()), 4),
            "cells_over_20deg_shear": round(float((shear > 20).mean()), 4),
            "note": "1 grid step per grid step is isometric. Measures the parameterization only, not whether the "
                    "surface is on one sheet."}


def grid_kept(before, after):
    """Does a moved tifxyz keep the grid of the one it came from: the same rows and columns, the same valid
    vertices, and the same declared scale? A snap moves vertices along their normals and may change nothing else,
    so labels drawn on the original grid still sit on a render of the copy."""
    from . import snap as ksnap
    np = _np()
    a, b = ksnap.load_mesh(before), ksnap.load_mesh(after)
    out = {"shape": list(a[0].shape), "valid_vertices": int(a[3].sum())}
    why = []
    if a[0].shape != b[0].shape:
        why.append(f"grid {list(b[0].shape)} instead of {list(a[0].shape)}")
    elif not np.array_equal(a[3], b[3]):
        why.append(f"{int((a[3] != b[3]).sum())} vertices changed between valid and invalid")
    scales = []
    for d in (before, after):
        try:
            scales.append(json.loads((Path(d) / "meta.json").read_text()).get("scale"))
        except (OSError, json.JSONDecodeError):
            scales.append(None)
    if scales[0] != scales[1]:
        why.append(f"declared scale {scales[1]} instead of {scales[0]}")
    if not why and a[3].any():
        moved = np.sqrt(sum((b[k][a[3]].astype(np.float64) - a[k][a[3]]) ** 2 for k in range(3)))
        out["moved_voxels"] = {"median": round(float(np.median(moved)), 4),
                               "p90": round(float(np.percentile(moved, 90)), 4), "max": round(float(moved.max()), 4)}
    out.update(kept=not why, why="; ".join(why) or None)
    return out


def distortion_passes(d, limits):
    """(ok, reasons) for a grid_distortion result against the plan's flatten limits."""
    reasons = []
    if d["abs_log_stretch"]["p95"] > math.log1p(limits["max_p95_stretch"]):
        reasons.append(f"95th percentile stretch {math.expm1(d['abs_log_stretch']['p95']):.1%} is over "
                       f"{limits['max_p95_stretch']:.0%}")
    if d["shear_deg"]["p95"] > limits["max_shear_deg_p95"]:
        reasons.append(f"95th percentile shear {d['shear_deg']['p95']:.1f} deg is over {limits['max_shear_deg_p95']}")
    if not limits["min_area_ratio"] <= d["area_ratio"] <= limits["max_area_ratio"]:
        reasons.append(f"area ratio {d['area_ratio']} is outside [{limits['min_area_ratio']}, "
                       f"{limits['max_area_ratio']}]")
    return not reasons, reasons


# ---------------------------------------------------------------- seeds

def _axis_at(axis, z):
    x, y = vc3d_orient.centre_at(axis, z)
    return x, y


def propose_seeds(pred, axis, count, shape_zyx, voxel_um, z_range=None, radius_um=(1500.0, None), level=4,
                  min_spacing_um=2000.0, seed=0, max_planes=24, ct=None, check=None, log=None, box_yx=None):
    """Seed points on a surface prediction with no person picking them. pred is a kit.vc3d_region.Volume of the
    prediction (0 to 255), axis the umbilicus [(z, y, x)] in level-0 voxels. Planes are drawn at random heights
    inside z_range (default the middle 80 % of the scan); on each, a coarse slice at `level` gives the predicted
    sheet pixels whose distance from the axis is inside radius_um; candidates are taken in a seeded random order,
    refined to the brightest level-0 voxel within half a coarse voxel, and kept when that voxel reaches the
    tracer's threshold, `check` (seed_check's rule, with the CT when given) passes, and every kept seed is at
    least min_spacing_um from the others. Returns (seeds, stats); each seed has its xyz, prediction value,
    radius and check. box_yx [[y0, y1], [x0, x1]] (level-0 voxels, half-open) keeps candidates inside it, for a
    prediction made over one box. Deterministic for a given seed and data."""
    np = _np()
    rng = random.Random(seed)
    nz = int(shape_zyx[0])
    if z_range:
        z0, z1 = max(0, int(z_range[0])), min(nz, int(z_range[1]))
    else:
        z0, z1 = int(nz * 0.1), int(nz * 0.9)
    if z1 <= z0:
        raise AutoError(f"empty z range {z_range}")
    level = min(int(level), len(pred.levels) - 1)
    f = pred.factors[level]                       # level voxels per level-0 voxel, (z, y, x)
    lshape = pred.shape(level)
    rmin = (radius_um[0] or 0.0) / voxel_um
    rmax = (radius_um[1] / voxel_um) if radius_um[1] else math.inf
    spacing = min_spacing_um / voxel_um
    planes = sorted({rng.randrange(z0, z1) for _ in range(max_planes * 3)})
    rng.shuffle(planes)
    planes = planes[:max_planes]
    seeds, stats = [], {"planes": 0, "candidates": 0, "below_threshold": 0, "refused": 0, "too_close": 0,
                        "level": level, "radius_voxels": [round(rmin, 1), None if rmax == math.inf else round(rmax, 1)]}
    for zp in planes:
        if len(seeds) >= count:
            break
        stats["planes"] += 1
        lz = min(lshape[0] - 1, int((zp + 0.5) * f[0]))
        sl = pred.read(level, [[lz, lz + 1], [0, lshape[1]], [0, lshape[2]]])[0]
        ys, xs = np.nonzero(sl >= SURFACE_THRESHOLD)
        if not len(ys):
            continue
        cx, cy = _axis_at(axis, zp)
        X0 = (xs + 0.5) / f[2] - 0.5
        Y0 = (ys + 0.5) / f[1] - 0.5
        r = np.hypot(X0 - cx, Y0 - cy)
        inside = (r >= rmin) & (r <= rmax)
        if box_yx:
            (by0, by1), (bx0, bx1) = box_yx
            inside &= (Y0 >= by0) & (Y0 < by1) & (X0 >= bx0) & (X0 < bx1)
        band = np.nonzero(inside)[0]
        if not len(band):
            continue
        order = list(band)
        rng.shuffle(order)
        tried = 0
        for i in order:
            if len(seeds) >= count or tried >= 6:
                break
            x, y = float(X0[i]), float(Y0[i])
            if any(math.dist((x, y, zp), s["xyz"]) < spacing for s in seeds):
                stats["too_close"] += 1
                continue
            tried += 1
            stats["candidates"] += 1
            half = [max(1, int(math.ceil(0.5 / f[k]))) for k in range(3)]
            box = [[zp - half[0], zp + half[0] + 1], [int(y) - half[1], int(y) + half[1] + 1],
                   [int(x) - half[2], int(x) + half[2] + 1]]
            blk = pred.read(0, box)
            if blk.size == 0 or int(blk.max()) < SURFACE_THRESHOLD:
                stats["below_threshold"] += 1
                continue
            # the brightest voxel nearest the box center
            idx = np.argwhere(blk == blk.max())
            ctr = np.array([half[0], half[1], half[2]])
            k = idx[np.argmin(((idx - ctr) ** 2).sum(axis=1))]
            xyz = [float(box[2][0] + k[2]), float(box[1][0] + k[1]), float(box[0][0] + k[0])]
            if box_yx and not (box_yx[0][0] <= xyz[1] < box_yx[0][1] and box_yx[1][0] <= xyz[0] < box_yx[1][1]):
                stats["outside_box"] = stats.get("outside_box", 0) + 1
                continue
            if any(math.dist(xyz, s["xyz"]) < spacing for s in seeds):
                stats["too_close"] += 1
                continue
            res = check(xyz) if check else None
            if res is not None and (not res.get("on_prediction") or res.get("ct", {}).get("verdict") == "air"):
                stats["refused"] += 1
                continue
            cxs, cys = _axis_at(axis, xyz[2])
            seeds.append({"xyz": xyz, "value": int(blk.max()), "radius_voxels": round(math.hypot(xyz[0] - cxs,
                                                                                                   xyz[1] - cys), 1),
                          "plane": zp, "check": res})
            if log:
                log(f"seed {len(seeds)}/{count} at {[round(v) for v in xyz]}")
    return seeds, stats


# ---------------------------------------------------------------- labeled benchmark segments

# The scoring windows of mac-w045.sh (scripts/mac-w045.sh, SEGMENT table): the 640 px crop of densest labeled
# ink (y0 y1 x0 x1) and the 9 um surface volume's shape (rows, columns). Labels sit on the 2.4 um render, read at
# level 2 by kit auc. surface_volume is the published render of the segment that render_check compares ours with.
SV841 = "9.366um-1.2m-113keV-volume-20250821151531.zarr"
BENCHMARKS = {
    "0841-w00": {"sample": "PHerc0841", "segment": "w00", "volume": "20250821151531",
                 "labels": "PHerc0841/segments/20260220213127-w00/ink-labels/2.403um-volume-20260319124803/20260918",
                 "crop": [2624, 3264, 2688, 3328], "surface_shape": [4220, 4760],
                 "surface_volume": "PHerc0841/segments/20260220213127-w00/surface-volumes/" + SV841},
    "0841-ag896": {"sample": "PHerc0841", "segment": "auto_grown_20260220144552896", "volume": "20250821151531",
                   "labels": "PHerc0841/segments/20260220214732-auto_grown_20260220144552896/ink-labels/"
                             "2.403um-volume-20260319124803/20260918",
                   "crop": [2496, 3136, 1600, 2240], "surface_shape": [4640, 4720],
                   "surface_volume": "PHerc0841/segments/20260220214732-auto_grown_20260220144552896/surface-volumes/"
                                     + SV841},
    "0841-ag405": {"sample": "PHerc0841", "segment": "auto_grown_20260220174252405", "volume": "20250821151531",
                   "labels": "PHerc0841/segments/20260221022814-auto_grown_20260220174252405/ink-labels/"
                             "2.403um-volume-20260319124803/20260918",
                   "crop": [1024, 1664, 2496, 3136], "surface_shape": [3760, 4900],
                   "surface_volume": "PHerc0841/segments/20260221022814-auto_grown_20260220174252405/surface-volumes/"
                                     + SV841},
}
# Published segments no plan here scores, by (sample, segment id): the report surfaces above (REPORT_ONLY), and any
# this checkout reserves in RESERVED_FILE, such as a held-out set kept for one final score. That file, when present,
# is a JSON list of {"sample", "segment", "why"}; a released copy may ship without it. A plan that names one, as its
# segment or under score.transfer, is refused when it is made, and a plan frozen before the list grew is refused when
# it runs (check_plan)
RESERVED_FILE = Path(__file__).resolve().parent / "data" / "autopipe-reserved.json"


def reserved_segments(path=None):
    """{(sample, segment id): why} for every segment no plan here scores; a malformed reserve file stops planning."""
    out = {(BENCHMARKS[k]["sample"], BENCHMARKS[k]["segment"]): why for k, why in REPORT_ONLY.items()}
    path = Path(path) if path else RESERVED_FILE
    if not path.exists():
        return out
    try:
        entries = json.loads(path.read_text())
        for e in entries:
            if not all(isinstance(e.get(k), str) and e[k] for k in ("sample", "segment", "why")):
                raise ValueError(f"entry {e!r} needs non-empty sample, segment and why")
            out[(e["sample"], e["segment"])] = e["why"]
    except (OSError, ValueError, TypeError, AttributeError) as e:
        raise AutoError(f"reserved segments: {path} is not a JSON list of {{sample, segment, why}} ({e}); "
                        "fix it before planning") from None
    return out


def reserved(sample, segment):
    """Why a run here never scores this published segment (a BENCHMARKS key or a segment id on sample), or None."""
    if segment in REPORT_ONLY:
        return REPORT_ONLY[segment]
    return reserved_segments().get((sample, BENCHMARKS[segment]["segment"] if segment in BENCHMARKS else segment))


def _corr(a, b):
    np = _np()
    a, b = a.astype(np.float64).ravel(), b.astype(np.float64).ravel()
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def render_check(ours, published, window, shift=64, min_corr=0.99, max_control=0.5):
    """Does our render reproduce a published surface volume? Pearson correlation over every layer of a window, with
    two controls that must fail, or the check proves nothing: the same window with its layers reversed, and our
    window moved by `shift` pixels along both axes. Passes when the match is at least min_corr and both controls
    are under max_control."""
    np = _np()
    from . import vc3d_region
    a, b = vc3d_region.Volume(str(ours)), vc3d_region.Volume(str(published))
    if a.shape(0) != b.shape(0):
        return {"passes": False, "why": f"our render is {a.shape(0)}, the published one {b.shape(0)}"}
    nz = a.shape(0)[0]
    y0, y1, x0, x1 = window
    mine = a.read(0, [[0, nz], [y0, y1], [x0, x1]])
    pub = b.read(0, [[0, nz], [y0, y1], [x0, x1]])
    moved = a.read(0, [[0, nz], [y0 + shift, y1 + shift], [x0 + shift, x1 + shift]])
    out = {"window": list(window), "shape": a.shape(0), "corr": round(_corr(mine, pub), 7),
           "control_layers_reversed": round(_corr(mine[::-1], pub), 4),
           f"control_moved_{shift}px": round(_corr(moved, pub), 4),
           "equal_fraction": round(float((mine == pub).mean()), 5),
           "mean_abs_diff": round(float(np.abs(mine.astype(np.int64) - pub.astype(np.int64)).mean()), 4),
           "missing_chunks_read": a.missing + b.missing, "min_corr": min_corr, "max_control": max_control}
    out["passes"] = bool(out["corr"] >= min_corr and out["control_layers_reversed"] < max_control
                         and out[f"control_moved_{shift}px"] < max_control)
    return out


def _auc(ctx, fwd, rev, lab, extra):
    import subprocess
    argv = [sys.executable, "-m", "kit", "auc", str(fwd), "--control", str(rev), "--labels", str(lab / "inklabels.zarr"),
            "--mask", str(lab / "supervision.zarr"), "--level", "2", *map(str, extra), "--json"]
    p = subprocess.run(argv, capture_output=True, text=True, cwd=str(ctx.root), env=kithome.python_env())
    if p.returncode == 0 and p.stdout.strip():
        return json.loads(p.stdout)
    return {"exit": p.returncode, "stderr": p.stderr[-800:]}


def score_maps(ctx, fwd, rev, lab, bench, inner, scratch):
    """A benchmark segment's forward and reverse maps against its labels, two ways: the whole map (no edge left
    out; results.json's "whole" rows) and the densest-ink window of mac-w045.sh with `inner` pixels of edge left
    out (its "crop" rows), cut from the whole map when the render has the published surface volume's shape."""
    out = {"whole": _auc(ctx, fwd, rev, lab, [])}
    try:
        import tifffile
    except ImportError:
        out["crop"] = {"skipped": "tifffile is not installed"}
        return out
    f, r = tifffile.imread(str(fwd)), tifffile.imread(str(rev))
    shape = list(f.shape[-2:])
    if shape != list(bench["surface_shape"]):
        out["crop"] = {"skipped": f"the render is {shape}, the published surface volume {bench['surface_shape']}: "
                                  "the window's place is not the same"}
        return out
    y0, y1, x0, x1 = bench["crop"]
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    cf, cr = scratch / f"crop-f-{Path(fwd).stem}.tif", scratch / f"crop-r-{Path(rev).stem}.tif"
    tifffile.imwrite(str(cf), f[..., y0:y1, x0:x1])
    tifffile.imwrite(str(cr), r[..., y0:y1, x0:x1])
    out["crop"] = _auc(ctx, cf, cr, lab, ["--crop", *bench["crop"], "--surface-shape", *shape, "--inner", inner])
    return out


# ---------------------------------------------------------------- plans

def _merge(base, over, path=""):
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        key = f"{path}{k}"
        if key in OPTIONAL and not isinstance(OPTIONAL[key], dict):
            # an optional value (trace.repeats): absent unless given, null leaves it out, make_plan checks it
            out.pop(k, None)
            if v is not None:
                out[k] = v
            continue
        if key in OPTIONAL:
            # absent unless asked for: null or false leaves it out, true takes its defaults, an object is merged over
            # them, with any OPTIONAL_EXTRA keys it gives (ink.orient's fallback) kept as given
            out.pop(k, None)
            if v is None or v is False:
                continue
            if v is not True and not isinstance(v, dict):
                raise AutoError(f"{key} is an object (or true for its defaults)")
            v = {} if v is True else v
            extra = {x: v[x] for x in OPTIONAL_EXTRA.get(key, ()) if x in v}
            out[k] = _merge(OPTIONAL[key], {x: y for x, y in v.items() if x not in extra}, f"{key}.")
            out[k].update(extra)
            continue
        if k not in out:
            raise AutoError(f"unknown plan setting {key}")
        if key in FREE_SETTINGS:
            if not isinstance(v, dict):
                raise AutoError(f"{path}{k} is an object")
            out[k] = v
        elif isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v, f"{path}{k}.")
        else:
            out[k] = v
    return out


def pick_volume(cat, sample, volume=None, target_um=9.0):
    """The catalog row of the scan to work on: the one named, else the scan nearest target_um that has a surface
    prediction and is not superseded."""
    rows = vc3d_catalog.volumes(cat, sample)
    if not rows:
        raise AutoError(f"{sample}: no volumes in the catalog")
    if volume:
        hit = [r for r in rows if r["volume"] == str(volume) or r["long_id"].startswith(str(volume))]
        if not hit:
            raise AutoError(f"{sample}: no volume {volume}; volumes: {', '.join(r['volume'] for r in rows)}")
        return hit[0]
    usable = [r for r in rows if r.get("surface_prediction_zarr") and not r.get("superseded_by")]
    if not usable:
        raise AutoError(f"{sample}: no scan with a published surface prediction; a prediction has to be made first "
                        "(a GPU job: kit surfacepred plans one, and the plan's external_prediction takes its result)")
    return min(usable, key=lambda r: (abs(math.log(r["voxel_um"] / target_um)), r["volume"]))


def pick_prediction(row, model=None):
    preds = row.get("surface_prediction_zarr") or []
    if model:
        hit = [p for p in preds if p.get("model") == str(model) or str(model) in p.get("url", "")]
        if not hit:
            raise AutoError(f"volume {row['volume']}: no prediction {model}")
        return hit[0]
    m7 = [p for p in preds if "surface-m7" in p.get("url", "")]
    return (m7 or preds)[0] if preds else None


# ---------------------------------------------------------------- a prediction from outside the catalog

def _location(loc, root=None):
    """A prediction or grid location as the plan records it: an https URL with one trailing slash (s3:// as the
    bucket's https URL), or an absolute local path (a relative one taken from root, default the working folder)."""
    text = str(loc or "").strip()
    if not text:
        raise AutoError("an empty location")
    if text.lower().startswith("s3://"):
        from . import vc3d_audit
        return vc3d_audit.s3_https(text) + "/"
    if text.lower().startswith(("http://", "https://")):
        return text.rstrip("/") + "/"
    if "://" in text:
        raise AutoError(f"{text}: a local folder, or an https or s3 URL")
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = Path(root or Path.cwd()) / p
    return str(p.resolve())


def _store(location, store_kw=None):
    from . import vc3d_audit
    kw = (store_kw or {}) if "://" in location else {}
    try:
        return vc3d_audit.open_store(location, **kw)
    except vc3d_audit.AuditError as exc:
        raise AutoError(f"{location}: {exc}") from exc


def _read(store, location, key):
    from . import vc3d_audit
    try:
        return store.read(key)
    except (vc3d_audit.AuditError, OSError) as exc:
        raise AutoError(f"{location}{'' if location.endswith('/') else '/'}{key}: does not read ({exc})") from exc


def prediction_headers(location, store_kw=None):
    """The small files that define a prediction volume, {relative path: bytes}: the root's .zgroup, .zattrs,
    meta.json, metadata.json and run.json where present, and the .zarray of every level its OME multiscales list.
    Local folder or URL (anonymous, S3's false 404s asked again: kit/vc3d_audit.py HttpStore)."""
    store = _store(location, store_kw)
    files = {}
    for key in EXTERNAL_HEADERS:
        raw = _read(store, location, key)
        if raw is not None:
            files[key] = raw
    try:
        attrs = json.loads(files.get(".zattrs") or b"{}")
        paths = [str(d["path"]) for d in attrs["multiscales"][0]["datasets"]]
    except (ValueError, KeyError, IndexError, TypeError):
        paths = []
    for p in paths:
        if not p or p in (".", "..") or not all(c.isalnum() or c in "_.-" for c in p):
            raise AutoError(f"{location}: level path {p!r} in .zattrs is not a plain folder name")
        raw = _read(store, location, f"{p}/.zarray")
        if raw is not None:
            files[f"{p}/.zarray"] = raw
    return files


def _json_or_none(raw):
    try:
        out = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return out if isinstance(out, dict) else None


def _scan_id(url):
    """The volume id at the head of a scan folder's name (".../20241024131838-7.910um-53keV-masked.zarr/")."""
    if not url:
        return None
    return str(url).rstrip("/").rsplit("/", 1)[-1].split("-")[0] or None


def external_run_record(files):
    """What the prediction's run.json (kit surfacepred package's record) says it was made from: scan, level, box,
    threshold; None when it has none."""
    run = _json_or_none(files.get("run.json"))
    if run is None:
        return None
    return {k: run[k] for k in ("scan", "level", "bbox", "threshold", "effective_um", "arm", "preset", "spec")
            if k in run}


def grids_level(meta):
    """The pyramid level of the prediction a vc_gen_normalgrids folder was made from: its metadata.json's
    "input-level" (villa apps/src/vc_gen_normalgrids.cpp 1285-1298), or the source's for a store vc_gen_normalgrids
    pyramid derived ("format": "normal-grid-multiscale" keeps it under "source-metadata", 767-771); None when the
    folder does not record it."""
    if meta.get("format") == "normal-grid-multiscale":
        meta = meta.get("source-metadata") or {}
    v = meta.get("input-level")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def resolve_external(prediction, grids, row, files=None, root=None, store_kw=None, catalog_grids=False):
    """Resolve and check a surface prediction (and its normal grids) from outside the catalog against the scan
    `row` it is meant for; the plan's record of them, or AutoError. The prediction must be one VC3D opens: a
    local folder by every rule of kit/surfacepred.py check_package (meta.json, uint8, fill 0, ceil-shaped levels;
    villa core/src/Volume.cpp 1027-1067, 1140-1150 and 1232-1263), a URL by the level-header rules only (VC3D's
    Volume::NewFromUrl, 1282-1401, takes the sizes from the first level and checks no level shapes; it reads a
    meta.json or metadata.json only for other fields, under a try that only warns, 84-116 and 1343-1359, and
    keeps the level's sizes over theirs, 1353-1355). Either way its level 0 must be
    the scan's level-0 shape by the rule VC3D applies to a level against its meta.json (paddedShapeOK, 1146-1150:
    at least the scan's size, padded by less than one chunk). Its run.json, when it has one, must name this scan
    and level 0. The grids must record that they were made from level 0 (anything else is in other voxels). The
    headers' and the grid metadata's SHA-256 enter the plan, so the acquire stage can tell when the files changed
    after the plan was made."""
    import tempfile
    from . import surfacepred
    loc = _location(prediction, root)
    if files is None:
        files = prediction_headers(loc, store_kw)
    with tempfile.TemporaryDirectory() as tmp:
        for k, v in files.items():
            (Path(tmp) / k).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / k).write_bytes(v)
        problems = surfacepred.check_package(tmp)
    if "://" in loc:
        # VC3D opens a URL with Volume::NewFromUrl (Volume.cpp 1282-1401): sizes from the first level, no level-shape
        # check, and a meta.json or metadata.json read only for other fields, a failure there a warning (84-116,
        # 1343-1359). The rules of its local open (loadMetadata, zarrOpen) apply to a local folder only
        problems = [p for p in problems if not p.startswith(LOCAL_OPEN_ONLY) and not p.endswith("(ceil rule)")]
    if problems:
        raise AutoError(f"{loc}: VC3D would not open this prediction (kit surfacepred check): " + "; ".join(problems))
    attrs = json.loads(files[".zattrs"])
    zarray = _json_or_none(files.get(f"{attrs['multiscales'][0]['datasets'][0]['path']}/.zarray")) or {}
    shape, chunks = list(zarray["shape"]), zarray.get("chunks")
    # the rule compares each axis with its own chunk: a chunks list of another length would leave axes unchecked
    if not (isinstance(chunks, list) and len(chunks) == 3
            and all(isinstance(c, int) and not isinstance(c, bool) and c > 0 for c in chunks)):
        raise AutoError(f"{loc}: level 0's .zarray gives chunks {chunks!r}, not three positive whole numbers, so its "
                        "shape cannot be checked by VC3D's rule")
    if not row.get("shape_zyx") or len(row["shape_zyx"]) != 3:
        raise AutoError(f"scan {row['volume']}: the catalog gives no shape, so a prediction cannot be checked "
                        "against it")
    scan = list(row["shape_zyx"])

    def fits(want):
        return all(surfacepred.shape_ok(a, e, c) for a, e, c in zip(shape, want, chunks))

    if not fits(scan):
        made = [k for k in range(1, 8) if fits(surfacepred.ceil_shape(scan, k))]
        why = (f"it is the scan's level {made[0]} shape: a prediction made on level {made[0]}, {2 ** made[0]}x "
               "coarser per axis, and the trace works in level-0 voxels" if made else
               "it is no level of this scan either: another scan, or another frame")
        raise AutoError(f"{loc}: level-0 shape {shape} is not scan {row['volume']}'s level-0 shape {scan} (VC3D's "
                        f"rule: at least that size, padded by less than one chunk); {why}")
    run = external_run_record(files)
    if run is not None and run.get("level") not in (None, 0):
        raise AutoError(f"{loc}: its run.json says it was made on level {run['level']} of the scan; the trace works "
                        "in level-0 voxels")
    if run is not None and run.get("scan") and _scan_id(run["scan"]) != str(row["volume"]):
        raise AutoError(f"{loc}: its run.json says it was made from scan {_scan_id(run['scan'])}, not "
                        f"{row['volume']}")
    out = {"zarr": loc, "level0_shape": shape, "level0_chunks": chunks, "levels": len(attrs["multiscales"][0]["datasets"]),
           "headers": sorted(files), "headers_sha256": headers_digest(files), "run_record": run,
           "normal_grids": None, "grids_input_level": None, "grids_metadata_sha256": None, "axis_grids": None}
    if grids:
        gloc = _location(grids, root)
        raw = _read(_store(gloc, store_kw), gloc, "metadata.json")
        meta = _json_or_none(raw)
        if meta is None:
            raise AutoError(f"{gloc}: no readable metadata.json, so not a normal-grid folder (VC3D's NormalGridVolume "
                            "refuses one without it: core/src/NormalGridVolume.cpp 75-78)")
        lv = grids_level(meta)
        if lv is None:
            raise AutoError(f"{gloc}: metadata.json records no input-level, so the level the grids were made on "
                            "cannot be checked; make them again with vc_gen_normalgrids, which records it")
        if lv != 0:
            raise AutoError(f"{gloc}: the grids were made on level {lv} of their prediction ({2 ** lv}x coarser per "
                            "axis); the trace needs grids in level-0 voxels")
        out.update(normal_grids=gloc, grids_input_level=lv, grids_metadata_sha256=hashlib.sha256(raw).hexdigest())
        # the axis estimate reads the catalog's grids of this scan when it publishes level-0 ones (the umbilicus
        # tool's rule; make_plan says which), else these
        out["axis_grids"] = None if catalog_grids else gloc
    return out


def plan_box(ext, external, shape_zyx):
    """(box, where it came from) for external_prediction.box: [[z0, z1], [y0, y1], [x0, x1]] half-open in level-0
    voxels, clipped to the scan, or (None, why not)."""
    from . import surfacepred
    want = ext.get("box", "auto")
    m, n = ext.get("seed_margin", 16), ext.get("axis_slices", 9)
    if not (_whole(m) and 0 <= m <= 256):
        raise AutoError("external_prediction.seed_margin is a whole number of voxels from 0 to 256")
    if not (_whole(n) and 3 <= n <= 200):
        raise AutoError("external_prediction.axis_slices is a whole number from 3 to 200")
    if want in (None, False, "off"):
        return None, "off"
    if want == "auto":
        text = (external.get("run_record") or {}).get("bbox")
        if not text:
            return None, "the prediction's run.json names no box"
        source = "run.json"
    else:
        text, source = want, "plan"
    try:
        box = surfacepred.parse_bbox(text)
    except surfacepred.SurfacePredError as exc:
        raise AutoError(f"external_prediction.box: {exc}") from exc
    box = [[max(0, a), min(int(n_), b)] for (a, b), n_ in zip(box, shape_zyx)]
    if any(b - a <= 2 * m for a, b in box):
        raise AutoError(f"external_prediction.box {text} leaves nothing inside the scan once seed_margin {m} is kept")
    return box, source


def in_box(xyz, box, margin=0):
    """Whether an [x, y, z] point lies inside a [[z0, z1], [y0, y1], [x0, x1]] box, margin voxels in."""
    return all(lo + margin <= v < hi - margin for v, (lo, hi) in zip(reversed(list(xyz)), box))


def box_trace_params(box, given=None):
    """The tracer's bounds at a box (villa GrowPatch.cpp: a new vertex whose neighbors' mean lies outside
    [x_min, x_max] and the rest is not grown), under any bound the plan gives in trace.params."""
    (z0, z1), (y0, y1), (x0, x1) = box
    out = {"z_min": z0, "z_max": z1 - 1, "y_min": y0, "y_max": y1 - 1, "x_min": x0, "x_max": x1 - 1}
    out.update(given or {})
    return out


CROP_REASONS = ("self-intersections: ", "winding audit: ", "seating: ")   # qa reasons qa.crop cuts by


def crop_reasons(rec):
    """The decided qa reasons qa.crop cuts by (Run.crop_one): self-intersections, seating and the winding audit,
    never one that rests on a check that could not run; [] when anything else (validity, orientation, the data
    term, the valid fraction) rejects the trace too, since cutting cannot mend those."""
    if (rec.get("failure") or {}).get("kind") == "infrastructure":
        return []
    unmeasured = set(rec.get("unmeasured") or [])
    reasons = rec.get("reasons") or []
    if any(r in unmeasured or not r.startswith(CROP_REASONS) for r in reasons):
        return []
    return list(reasons)


def switch_reasons(rec):
    """The qa reasons of a sheet switch in a rejection the rule decided: none for a rejection resting only on checks
    that could not run, and never a switch check that could not run itself, beside a reason that was decided (a trace
    rejected for its seating whose self-crossings went unmeasured has no measured switch to repair)."""
    if (rec.get("failure") or {}).get("kind") == "infrastructure":
        return []
    unmeasured = set(rec.get("unmeasured") or [])     # "self-intersections: not measured (...)" is no switch
    return [r for r in rec.get("reasons") or [] if r.startswith(SWITCH_REASONS) and r not in unmeasured]


def headers_digest(files):
    """SHA-256 over the header files (each file's own SHA-256 under its name)."""
    return digest({k: hashlib.sha256(v).hexdigest() for k, v in files.items()})


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _whole(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_recipe(s):
    """The ink recipe settings (render.snap, ink.layers, ink.ensemble), when a plan has them."""
    sn = s["render"].get("snap")
    if sn is not None:
        if sn["source"] not in ("pred", "ct"):
            raise AutoError("render.snap.source is pred (the plan's surface prediction) or ct (the CT band midline)")
        if sn["check"] not in SNAP_CHECKS:
            raise AutoError(f"render.snap.check is one of {SNAP_CHECKS}")
        if sn["check_reference"] not in ("snapped", "original"):
            raise AutoError("render.snap.check_reference is snapped or original")
        if not isinstance(sn["sham"], bool):
            raise AutoError("render.snap.sham is true or false")
        if not (_whole(sn["max_off"]) and 1 <= sn["max_off"] <= 64):
            raise AutoError("render.snap.max_off is a whole number of voxels from 1 to 64")
        if not (_whole(sn["level"]) and 0 <= sn["level"] <= 8):
            raise AutoError("render.snap.level is a whole number from 0 to 8")
        for k in ("threshold", "jump", "sigma"):
            if not (_number(sn[k]) and sn[k] > 0):
                raise AutoError(f"render.snap.{k} is a number above 0")
        if "mode" in sn:
            if sn["mode"] not in SNAP_MODES:
                raise AutoError(f"render.snap.mode is one of {SNAP_MODES}")
            if sn["source"] != "ct":
                raise AutoError("render.snap.mode is for source ct; source pred snaps to the nearest predicted sheet")
        for k in ("target", "per_vertex"):
            if k in sn and sn.get("mode") != "face":
                raise AutoError(f"render.snap.{k} needs render.snap.mode face")
        if "per_vertex" in sn and not isinstance(sn["per_vertex"], bool):
            raise AutoError("render.snap.per_vertex is true or false")
        if "target" in sn:
            if sn["target"] not in SNAP_TARGETS:
                raise AutoError(f"render.snap.target is one of {SNAP_TARGETS}")
    lay = s["ink"].get("layers")
    if lay is not None:
        w = lay["windows"]
        if not (isinstance(w, list) and w and all(isinstance(p, list) and len(p) == 2 and all(map(_whole, p))
                                                  and 0 <= p[0] < p[1] for p in w)):
            raise AutoError("ink.layers.windows is a list of [start, stop) layer windows, 0 <= start < stop")
        if len({tuple(p) for p in w}) != len(w):
            raise AutoError("ink.layers.windows names a window twice")
        if lay["combine"] not in ENSEMBLE_METHODS:
            raise AutoError(f"ink.layers.combine is one of {ENSEMBLE_METHODS}")
    ens = s["ink"].get("ensemble")
    if ens is not None:
        if ens["method"] not in MODEL_ENSEMBLE_METHODS:
            raise AutoError(f"ink.ensemble.method is one of {MODEL_ENSEMBLE_METHODS}")
        if len(set(s["ink"]["models"])) < 2:
            raise AutoError("ink.ensemble combines the planned models' maps: plan at least two models")
        if "ensemble" in s["ink"]["models"]:
            raise AutoError("a planned model may not be named ensemble: the ensemble's maps go under that name")
        given = [k for k in OPTIONAL_EXTRA["ink.ensemble"] if k in ens]
        if given and ens["method"] != "zscore":
            raise AutoError(f"ink.ensemble.{given[0]} goes with method zscore")
        if ens["method"] == "zscore":
            from . import inkensemble
            why = inkensemble.check_plan(ens, list(s["ink"]["models"]))
            if why:
                raise AutoError(why)


def model_aliases():
    """vc3d_catalog.model_aliases(), with a malformed aliases file refused as an AutoError."""
    try:
        return vc3d_catalog.model_aliases()
    except vc3d_catalog.CatalogError as exc:
        raise AutoError(str(exc)) from None


def model_pins(names):
    """{name: sha256} for each planned ink model the aliases file pins (vc3d_catalog.ALIASES_FILE) under any of its
    names, so a plan and its outputs say which weights each name meant, and runs of one model under two of its names
    group by the same sha256. Only the pin is recorded, never the model's other names, so a plan that names a model by
    its old id does not carry a private family name. Empty when no planned name is pinned (then the plan holds no
    such record and its digest is as before)."""
    if not isinstance(names, list):
        return {}
    aliases = model_aliases()
    pins = {m: vc3d_catalog.model_pin(m, aliases) for m in names if isinstance(m, str)}
    return {m: pin for m, pin in pins.items() if pin}


def check_model_pins(plan):
    """Refuses ink when a planned model name is now pinned to other weights than when the plan was made
    (resolved.model_pins). A plan made before its names were pinned holds no record and is not checked here; the ink
    tool still checks any pin at every load."""
    then = (plan.get("resolved") or {}).get("model_pins") or {}
    now_ = model_pins(list(then))
    changed = [f"{m} was pinned to sha256 {then[m]} when the plan was made and is "
               f"{'pinned to ' + now_[m] if now_.get(m) else 'not pinned'} now"
               for m in sorted(then) if now_.get(m) != then[m]]
    if changed:
        raise AutoError(f"ink.models: {'; '.join(changed)} (the model aliases file changed): make a new plan")


def check_models(s, registered):
    """ink.models against the models kit can fetch (vc3d_catalog.KNOWN_MODELS) and those registered on this machine
    (registered, from the models tool), so a misspelled name is refused when the plan is made, not frozen into its
    digest and found at ink. A name passes when it or another name of the same model (vc3d_catalog.model_names) is
    known or registered. One model named twice, by the same name or by two of its names (vc3d_catalog.main_name), is
    refused always: it would ink the same weights twice and count as two models in an ensemble or a comparison. The
    rest is not checked when registered is None (a caller with no machine to ask) or ink.where is skip (no model
    runs)."""
    names = s["ink"]["models"]
    if isinstance(names, list) and all(isinstance(m, str) for m in names):
        aliases = model_aliases()   # another name of the same model counts (vc3d_catalog.ALIASES_FILE)
        seen = {}
        for m in names:
            key = vc3d_catalog.main_name(m, aliases)
            if key in seen:
                raise AutoError(f"ink.models names {m} twice" if seen[key] == m else
                                f"ink.models names {seen[key]} and {m}, two names of one model")
            seen[key] = m
    if registered is None or s["ink"]["where"] == "skip":
        return
    if not isinstance(names, list) or not names or not all(isinstance(m, str) and m for m in names):
        raise AutoError("ink.models is a list of model names")
    known = set(vc3d_catalog.KNOWN_MODELS) | set(vc3d_catalog.BUILTIN_MODELS)
    unknown = [m for m in names if vc3d_catalog.find_model(m, known, aliases) is None
               and vc3d_catalog.find_model(m, registered, aliases) is None]
    if unknown:
        raise AutoError(f"ink.models: {', '.join(unknown)} is neither a model kit can fetch "
                        f"({', '.join(sorted(known))}) nor one registered on this machine (the models tool, "
                        "action add); check the spelling")


def check_triage(s):
    """triage, when a plan has it: a known method, and the maps it scores (forward beside both controls)."""
    tri = s.get("triage")
    if tri is None:
        return
    if tri["method"] not in TRIAGE_METHODS:
        raise AutoError(f"triage.method is one of {TRIAGE_METHODS}")
    if not set(TRIAGE_VARIANTS) <= set(s["ink"]["variants"]):
        raise AutoError("triage scores the forward map beside the reverse and shuffled maps: it needs ink.variants "
                        "f, r and s")
    if s["ink"]["where"] == "skip":
        raise AutoError("triage scores ink maps, and ink.where skip makes none")


def check_crackle(s):
    """crackle, when a plan has it: a known rule, a tile size the rule can judge, and the maps it reads (forward
    beside the reverse-depth control)."""
    c = s.get("crackle")
    if c is None:
        return
    if c["rule"] not in CRACKLE_RULES:
        raise AutoError(f"crackle.rule is one of {CRACKLE_RULES}")
    t = c["tile_px"]
    if isinstance(t, bool) or not isinstance(t, int) or not 320 <= t <= 8192:
        # under about 317 px a tile cannot hold the rule's 100,000 papyrus pixels
        raise AutoError("crackle.tile_px is a whole number of pixels from 320 to 8192")
    if not {"f", "r"} <= set(s["ink"]["variants"]):
        raise AutoError("crackle judges the forward map against the reverse-depth map: it needs ink.variants f and r")
    if s["ink"]["where"] == "skip":
        raise AutoError("crackle judges ink maps, and ink.where skip makes none")


def check_orient(s):
    """ink.orient, when a plan has it: a known method, thresholds in range, a sampler kit canvasorient has, and maps
    to make."""
    o = s["ink"].get("orient")
    if o is None:
        return
    if o["method"] not in ORIENT_METHODS:
        raise AutoError(f"ink.orient.method is one of {ORIENT_METHODS}")
    if not (_number(o["min_consistency"]) and 0 < o["min_consistency"] <= 1):
        raise AutoError("ink.orient.min_consistency is a number above 0 and at most 1")
    if not (_number(o["min_vertical"]) and 0 <= o["min_vertical"] <= 10):
        raise AutoError("ink.orient.min_vertical is a number from 0 to 10 (voxels of z per canvas pixel)")
    if o["order"] not in (0, 1) or isinstance(o["order"], bool):
        raise AutoError("ink.orient.order is 0 (nearest) or 1 (bilinear)")
    if "fallback" in o and o["fallback"] not in ORIENT_FALLBACKS:
        raise AutoError(f"ink.orient.fallback is one of {ORIENT_FALLBACKS}")
    if s["ink"]["where"] == "skip":
        raise AutoError("ink.orient turns renders for the ink models, and ink.where skip runs none")
    if s["segment"]:
        raise AutoError("ink.orient turns the run's own traces; a published segment is in the published layout "
                        "already and its labels sit on its canvas")


def check_settings(s, sample, models=None):
    """make_plan's refusals that read the merged settings alone (and the sample, for score.transfer): the same
    checks a derived plan passes (a swap arm, kit/apgraph.py) before it is frozen."""
    if s["purpose"] not in ("benchmark", "target", "smoke"):
        raise AutoError("purpose is benchmark, target or smoke")
    if s["purpose"] == "target" and not s["experiment"]:
        raise AutoError("a target run needs experiment=<ledger slug>, fixed with kit run init before any map exists "
                        "(AGENTS.md rule 3)")
    if s["purpose"] != "target" and s["experiment"]:
        raise AutoError("experiment goes with purpose target only")
    if s["qa"]["require_seated"] not in QA_SEATED:
        raise AutoError(f"qa.require_seated is one of {QA_SEATED}")
    if s["qa"]["windaudit"] not in QA_WIND:
        raise AutoError(f"qa.windaudit is one of {QA_WIND}")
    if s["qa"]["published"] not in QA_PUBLISHED:
        raise AutoError(f"qa.published is one of {QA_PUBLISHED}")
    if s["trace"]["normal_grids"] not in TRACE_GRIDS:
        raise AutoError(f"trace.normal_grids is one of {TRACE_GRIDS}")
    reps = s["trace"].get("repeats", 1)
    if isinstance(reps, bool) or not isinstance(reps, int) or not 1 <= reps <= MAX_REPEATS:
        raise AutoError(f"trace.repeats is a whole number from 1 to {MAX_REPEATS}")
    if "trace.budget" in s:
        raise AutoError('trace.budget goes under trace ({"trace": {"budget": true}}); at the top level no stage reads it')
    # Any other optional setting of a section given at the top level by its dotted name ("trace.repeats",
    # "qa.repair"): _merge keeps it there and no stage reads it. A tracing run asked for 2 repeats and qa.repair this
    # way, and each seed was traced once with no repair (22 Oct 2026)
    dotted = sorted(k for k in s if "." in k and isinstance(DEFAULTS.get(k.split(".", 1)[0]), dict))
    if dotted:
        first = dotted[0].split(".", 1)
        raise AutoError(f"{', '.join(dotted)} go under their section ({{\"{first[0]}\": {{\"{first[1]}\": ...}}}}); "
                        "at the top level no stage reads them")
    if s["trace"].get("budget") is not None:
        try:
            tracebudget.check_settings(s["trace"]["budget"])
        except tracebudget.BudgetError as exc:
            raise AutoError(str(exc)) from exc
        b = s["trace"]["budget"]
        if s["purpose"] == "target" and b["keep_partial"] and not b["partial_rule"]:
            # a partial surface is not the trace the recipe describes: a target's readout must say how one counts
            # before any map exists (AGENTS.md rule 3)
            raise AutoError("a target plan with trace.budget keeps partial surfaces only when trace.budget."
                            "partial_rule names where its preregistration says how they count; or set "
                            "trace.budget.keep_partial false")
    pts = s["seeds"]["points"]
    if pts is not None and (not isinstance(pts, list) or not pts or not all(
            isinstance(q, list) and len(q) == 3 and all(isinstance(v, (int, float)) for v in q) for q in pts)):
        raise AutoError("seeds.points is a list of [x, y, z] seeds in level-0 voxels")
    if s["ink"]["where"] not in ("auto", "local", "modal", "skip"):
        raise AutoError("ink.where is auto, local, modal or skip")
    if s["purpose"] in ("target", "benchmark") and not {"f", "r"} <= set(s["ink"]["variants"]):
        raise AutoError("ink variants must include f and r: the reverse-depth control is required (rule 4)")
    trim = s["render"].get("trim")
    if trim is not None:
        if not s["render"]["audit"] or s["render"]["max_missing"] is None:
            raise AutoError("render.trim acts when the chunk audit refuses a surface: it needs render.audit and "
                            "render.max_missing")
        share = trim["min_area_share"]
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < share <= 1:
            raise AutoError("render.trim.min_area_share is a share of the area above 0 and at most 1")
        for k, hi in (("dilate", 64), ("level", 8)):
            if isinstance(trim[k], bool) or not isinstance(trim[k], int) or not 0 <= trim[k] <= hi:
                raise AutoError(f"render.trim.{k} is a whole number from 0 to {hi}")
    for k, v in (s.get("strict") or {}).items():
        if not isinstance(v, bool):
            raise AutoError(f"strict.{k} is true or false")
    transfer = s["score"].get("transfer")
    if transfer is not None:
        check_transfer(transfer, s, sample)
    check_recipe(s)
    check_models(s, models)
    check_triage(s)
    check_crackle(s)
    if s.get("stackcheck") is not None:
        try:
            apstackcheck.check(s["stackcheck"])
        except apstackcheck.StackError as exc:
            raise AutoError(str(exc)) from exc
    check_orient(s)
    check_trace_methods(s)
    rp = s["qa"].get("repair")
    if rp is not None:
        if rp["method"] not in REPAIR_METHODS:
            raise AutoError(f"qa.repair.method is one of {REPAIR_METHODS}")
        if not (_number(rp["min_area_share"]) and 0 < rp["min_area_share"] <= 1):
            raise AutoError("qa.repair.min_area_share is a share of the area above 0 and at most 1")
        if s["segment"]:
            raise AutoError("qa.repair repairs the run's own traces; a published segment is never cut")
    cp = s["qa"].get("crop")
    if cp is not None:
        check_crop(cp, s)
    ex = s["qa"].get("extend")
    if ex is not None:
        check_extend(ex, s)


QA_CROP_SEATING = ("off", "check", "grid")
EXTEND_NORMALS = ("prediction", "ct")
EXTEND_SIDES = ("up", "down", "left", "right")


def check_extend(ex, s):
    """qa.extend's settings (OPTIONAL["qa.extend"])."""
    sides = ex["sides"]
    if not isinstance(sides, list) or not sides or any(x not in EXTEND_SIDES for x in sides) or \
            len(set(sides)) != len(sides):
        raise AutoError(f"qa.extend.sides is a list of distinct sides from {EXTEND_SIDES}")
    for k, hi in (("cells", 256), ("rounds", 64), ("timeout", 48 * 3600)):
        if isinstance(ex[k], bool) or not isinstance(ex[k], int) or not 1 <= ex[k] <= hi:
            raise AutoError(f"qa.extend.{k} is a whole number from 1 to {hi}")
    if ex["normals"] not in EXTEND_NORMALS:
        raise AutoError(f"qa.extend.normals is one of {EXTEND_NORMALS}")
    if s["segment"]:
        raise AutoError("qa.extend grows the run's own traces; a published segment is never changed")



def check_crop(cp, s):
    """qa.crop's settings (OPTIONAL["qa.crop"])."""
    if cp["selfcross_per_cm2"] is not None and not _number(cp["selfcross_per_cm2"], 0):
        raise AutoError("qa.crop.selfcross_per_cm2 is a rate of crossings per cm2, 0 or more, or null")
    if cp["max_off_share"] is not None and not (_number(cp["max_off_share"], 0) and cp["max_off_share"] <= 1):
        raise AutoError("qa.crop.max_off_share is a share from 0 to 1, or null")
    for k in ("dilate", "off_min_cells", "window_cells"):
        if k == "off_min_cells" and cp[k] is None:
            continue
        if isinstance(cp[k], bool) or not isinstance(cp[k], int) or cp[k] < (0 if k == "dilate" else 2 if
                                                                            k == "window_cells" else 1):
            raise AutoError(f"qa.crop.{k} is a whole number" + (", 0 or more" if k == "dilate" else
                                                                ", 2 or more" if k == "window_cells" else
                                                                ", 1 or more"))
    if not _number(cp["min_area_cm2"], 0):
        raise AutoError("qa.crop.min_area_cm2 is an area in cm2, 0 or more")
    if cp["seating"] not in QA_CROP_SEATING:
        raise AutoError(f"qa.crop.seating is one of {QA_CROP_SEATING}")
    if s["segment"]:
        raise AutoError("qa.crop cuts the run's own traces; a published segment is never cut")


def make_plan(sample, settings=None, cat=None, cache_dir=None, created=None, root=None, store_kw=None, models=None):
    """A frozen plan for one run: the defaults with the given settings over them, and the scan, prediction, normal
    grids and umbilicus resolved from the catalog, or the prediction and grids the plan names from outside it
    (external_prediction, read and checked here). Its digest covers everything a stage decides by. models, when
    given, names the ink models registered on this machine (the models tool): each planned model must be one of
    them or one kit can fetch (check_models). The shorthand `backends` (kit/apbackends.py) is turned into the
    settings it stands for first, so the frozen plan holds those settings only."""
    from . import apbackends
    try:
        settings = apbackends.apply(settings)
    except apbackends.BackendError as exc:
        raise AutoError(str(exc)) from exc
    s = _merge(DEFAULTS, settings or {})
    try:
        apbackends.check_settings(s)
    except apbackends.BackendError as exc:
        raise AutoError(str(exc)) from exc
    check_settings(s, sample, models)
    transfer = s["score"].get("transfer")
    ext = s.get("external_prediction")
    files = run = None
    if ext is not None:
        if not ext.get("zarr"):
            raise AutoError("external_prediction needs zarr: the prediction's folder or URL")
        if s["segment"]:
            raise AutoError("a published segment replaces seeds and trace, so it has no use for external_prediction")
        if s["prediction"]:
            raise AutoError("prediction names a catalog prediction and external_prediction replaces it: give one")
        files = prediction_headers(_location(ext["zarr"], root), store_kw)
        run = external_run_record(files)
        if not s["volume"] and not (run or {}).get("scan"):
            raise AutoError("external_prediction: name the scan it was made from (volume=<catalog id>); its folder "
                            "has no run.json that says")
    bench = None
    if s["segment"]:
        why = reserved(sample, s["segment"])
        if why:
            raise AutoError(f"segment {s['segment']} stays unscored here: it is reserved ({why})")
        bench = BENCHMARKS.get(s["segment"])
        if bench and bench["sample"] != sample:
            raise AutoError(f"benchmark segment {s['segment']} is on {bench['sample']}, not {sample}")
        if s["purpose"] == "target":
            raise AutoError("a published labeled segment is a benchmark, not a target")
    cat = cat if cat is not None else vc3d_catalog.load(Path(cache_dir or kithome.path("work", "vc3d", "cache")))
    row = pick_volume(cat, sample, s["volume"] or (bench or {}).get("volume") or _scan_id((run or {}).get("scan")))
    external = None
    if ext is not None:
        # The catalog's grids serve the axis estimate only when they are in level-0 voxels: grids made on level 2
        # (the catalog's for most 2.2 to 2.4 um scans) are in voxels 4x larger, so such a scan takes the plan's
        external = resolve_external(ext["zarr"], ext.get("normal_grids"), row, files=files, root=root,
                                    store_kw=store_kw, catalog_grids=any(
                                        g.get("level") in (None, 0) for g in row.get("normal_grids") or []))
        external["box"], external["box_source"] = plan_box(ext, external, row["shape_zyx"])
        if external["box"] and s["seeds"]["points"]:
            out = [q for q in s["seeds"]["points"] if not in_box(q, external["box"])]
            if out:
                raise AutoError(f"seeds.points {out[:3]} lie outside the prediction's box {external['box']} "
                                f"({external['box_source']}); the prediction holds no sheet there")
        pred = {"url": external["zarr"], "model": "external", "level": 0}
        level = 0
        grids = [{"url": external["normal_grids"], "model": "external"}] if external["normal_grids"] else []
        if s["trace"]["normal_grids"] == "required" and not grids:
            raise AutoError("trace.normal_grids is required and external_prediction names no normal_grids")
    else:
        pred = pick_prediction(row, s["prediction"])
        if pred is None and not s["segment"]:
            raise AutoError(f"{sample} {row['volume']}: no surface prediction to trace on; a scan without one needs "
                            "the surface-prediction job first (kit surfacepred), then external_prediction")
        level = pred.get("level") if pred else None
        if pred is not None and level not in (None, 0) and not s["segment"]:
            raise AutoError(f"{sample} {row['volume']}: prediction {pred['url']} was made on level {level} of the "
                            f"scan ({2 ** level}x coarser per axis); the trace works in level-0 voxels and kit does not "
                            "scale frames yet. Use a scan with a level-0 prediction, or predict one "
                            "(kit surfacepred)")
        # The normal grids that go with the prediction: same model and level (grids made on another level are in
        # other voxels); grids of another model only when none match, and never of another level
        grids = [g for g in (row.get("normal_grids") or []) if g.get("level") in (None, level)]
        grids = [g for g in grids if not pred or g.get("model") == pred.get("model")] or grids
        if s["trace"]["normal_grids"] == "required" and not grids and not s["segment"]:
            raise AutoError(f"{sample} {row['volume']}: trace.normal_grids is required and the catalog publishes no "
                            "normal grids for this prediction")
    if (s["render"].get("snap") or {}).get("source") == "pred" and not pred:
        raise AutoError("render.snap with source pred needs a surface prediction, and this plan resolves none")
    umb = vc3d_catalog.umbilicus_for(cat, row["volume"])
    # Traces in the frame of the published PHerc0139 windings are measured against them (kit surfbench) under
    # the rule frozen here; the key is left out elsewhere, so plans of other scans keep their digest
    wb = None
    if not s["segment"]:
        from . import surfbench
        if (sample, row["volume"]) == (surfbench.SAMPLE, surfbench.VOLUME):
            wb = {"references": f"{surfbench.SAMPLE} windings in the frame of {surfbench.VOLUME}",
                  "rule_digest": surfbench.RULE_DIGEST}
    xfer = None
    if transfer is not None:
        # the labeled segments whose labels are carried: their meshes are fetched in this scan's frame, so each
        # must be labeled on it
        xfer = {}
        for key in transfer["segments"]:
            b = BENCHMARKS[key]
            if b["volume"] != row["volume"]:
                raise AutoError(f"score.transfer: {key}'s labels sit on scan {b['volume']}, not {row['volume']}")
            xfer[key] = {k: b[k] for k in ("segment", "volume", "labels", "surface_shape", "surface_volume", "crop")}
    report = None
    if transfer is not None:
        # report surfaces on this scan (0841-ag405): our traces may run over them, so render records where, from
        # their meshes alone; their labels are never fetched (a note of the source repository, 10 Oct)
        report = {key: {k: BENCHMARKS[key][k] for k in ("segment", "volume")} for key in sorted(REPORT_ONLY)
                  if key in BENCHMARKS and BENCHMARKS[key]["sample"] == sample
                  and BENCHMARKS[key]["volume"] == row["volume"]}
    resolved = {"sample": sample, "volume": row["volume"], "volume_url": row["url"], "voxel_um": row["voxel_um"],
                "shape_zyx": row["shape_zyx"], "license": row.get("license"),
                "prediction_url": pred["url"] if pred else None, "prediction_model": pred.get("model") if pred else None,
                "prediction_level": level,
                "normal_grids_url": grids[0]["url"] if grids else None,
                "normal_grids_model": grids[0].get("model") if grids else None, "catalog_umbilicus": umb,
                "benchmark": bench, **({"winding_bench": wb} if wb else {}),
                **({"external_prediction": external} if external else {}),
                **({"transfer": xfer} if xfer is not None else {}),
                **({"report_overlap": report} if report else {}),
                **trace_method_resolved(s)}
    pins = model_pins(s["ink"]["models"])     # only for a name the aliases file pins
    if pins:
        resolved["model_pins"] = pins
    try:
        apbackends.check_settings(s, resolved)
    except apbackends.BackendError as exc:
        raise AutoError(str(exc)) from exc
    plan = {"version": PLAN_VERSION, "created": created or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "settings": s, "resolved": resolved}
    plan["digest"] = digest({k: plan[k] for k in ("version", "settings", "resolved")})
    return plan


def _number(v, lo=None, hi=None, lo_open=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return False
    if lo is not None and (v <= lo if lo_open else v < lo):
        return False
    return hi is None or v <= hi


def check_transfer(t, s, sample):
    """score.transfer's refusals (make_plan): what it carries, from where, by which thresholds."""
    segs = t.get("segments")
    if not isinstance(segs, list) or not segs or not all(isinstance(k, str) for k in segs):
        raise AutoError("score.transfer.segments is a list of labeled segment keys, e.g. [\"0841-w00\"]")
    if len(set(segs)) != len(segs):
        raise AutoError("score.transfer.segments names a segment twice")
    for key in segs:
        if key in REPORT_ONLY:
            raise AutoError(f"score.transfer: {key} stays unscored here; it is a report surface "
                            f"({REPORT_ONLY[key]})")
        if key not in BENCHMARKS:
            known = ", ".join(sorted(k for k in BENCHMARKS if k not in REPORT_ONLY))
            raise AutoError(f"score.transfer: {key} is not a labeled segment kit knows ({known})")
        if BENCHMARKS[key]["sample"] != sample:
            raise AutoError(f"score.transfer: {key} is on {BENCHMARKS[key]['sample']}, not {sample}")
    if s["segment"]:
        raise AutoError("score.transfer scores the run's own traces; a published segment (segment) replaces the "
                        "trace, and is scored on its own labels without it")
    if s["purpose"] == "target":
        raise AutoError("score.transfer carries published labels: target runs are never scored here")
    if not _number(t["max_gap_vox"], 0, lo_open=True):
        raise AutoError("score.transfer.max_gap_vox is a distance in voxels above 0")
    if not _number(t["max_normal_deg"], 0, 90, lo_open=True) or t["max_normal_deg"] >= 90:
        raise AutoError("score.transfer.max_normal_deg is an angle above 0 and under 90 degrees")
    if not _number(t["min_area_cm2"], 0):
        raise AutoError("score.transfer.min_area_cm2 is an area in cm2, 0 or more")
    if not _number(t["displace_mm"], 0, lo_open=True):
        raise AutoError("score.transfer.displace_mm is a distance in mm above 0")
    if isinstance(t["lattice_px"], bool) or not isinstance(t["lattice_px"], int) or not 1 <= t["lattice_px"] <= 16:
        raise AutoError("score.transfer.lattice_px is a whole number from 1 to 16")
    b = t["bootstrap"]
    for k, lo in (("draws", 20), ("block_px", 1), ("seed", 0)):
        if isinstance(b[k], bool) or not isinstance(b[k], int) or b[k] < lo:
            raise AutoError(f"score.transfer.bootstrap.{k} is a whole number, at least {lo}")
    refs = t.get("references")
    if refs is not None:
        if not isinstance(refs, dict):
            raise AutoError("score.transfer.references is an object: {segment: \"run\" or {model: map path}}")
        for key, how in refs.items():
            if key not in segs:
                raise AutoError(f"score.transfer.references names {key}, which is not in score.transfer.segments")
            if how == "run":
                continue
            if not isinstance(how, dict) or not how or not all(
                    m in s["ink"]["models"] and isinstance(p, str) and p for m, p in how.items()):
                raise AutoError(f"score.transfer.references.{key} is \"run\" or {{model: path}} for models in "
                                "ink.models")
    if not {"f", "r"} <= set(s["ink"]["variants"]):
        raise AutoError("score.transfer needs the forward and reverse maps (ink.variants f and r)")


def check_plan(plan):
    """The plan as stored, with its digest checked: a plan edited after it was frozen is refused."""
    want = digest({k: plan.get(k) for k in ("version", "settings", "resolved")})
    if plan.get("digest") != want:
        raise AutoError("the plan's digest does not match its content: it was edited after it was made. Make a new "
                        "plan (a changed rule is a new run, never an edit of a frozen one)")
    if plan.get("version") not in READ_VERSIONS:
        raise AutoError(f"plan version {plan.get('version')} is not one of {READ_VERSIONS}")
    seg = (plan.get("settings") or {}).get("segment")
    why = seg and reserved((plan.get("resolved") or {}).get("sample"), seg)
    if why:
        raise AutoError(f"the plan's segment {seg} stays unscored here: it is reserved ({why}); a plan made before "
                        "kit refused it does not run")
    return plan


# ---------------------------------------------------------------- the run

class Run:
    """One run folder: plan.json (frozen), state.json (each stage's and each surface's record), and the
    outputs of every stage below it. A stage that finished is not run again; a stage that failed or a surface
    that was not reached is, so `run` resumes after an interruption."""

    def __init__(self, agent, ctx, out, plan, log=None):
        self.agent, self.ctx, self.out, self.plan = agent, ctx, Path(out), check_plan(plan)
        self.s, self.r = plan["settings"], plan["resolved"]
        self.log = log or (lambda m: None)
        self.state_path = self.out / "state.json"
        if self.state_path.is_file():
            self.state = json.loads(self.state_path.read_text())
            if self.state.get("plan_digest") != plan["digest"]:
                raise AutoError(f"{self.out} holds a run of another plan ({self.state.get('plan_digest', '')[:12]}); "
                                "use a new folder")
        else:
            self.state = {"plan_digest": plan["digest"], "stages": {}, "surfaces": {}}
        (self.out / "plan.json").write_text(json.dumps(plan, indent=1))
        self.ran_here = set()       # the stages this process ran: the learner names them this machine's (learn_record)

    # -- bookkeeping
    def save(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, default=str))
        tmp.replace(self.state_path)

    def done(self, stage):
        status = self.state["stages"].get(stage, {}).get("status")
        if status == "handoff":     # handed to the Modal runner: done here, run again there
            return not (self.on_runner or self.can_take_back(stage))
        return status in ("done", "skipped")

    def can_take_back(self, stage):
        """True when a run of the same folder can now do a handed-off stage itself: ink under the plan's "auto",
        once this machine has the planned models and an ink Python with torch (KIT_INK_PYTHON)."""
        if stage != "ink" or self.s["ink"]["where"] != "auto":
            return False
        try:
            return self.ink_where() == "local"
        except AutoError:
            return False

    @property
    def on_runner(self):
        """True inside a script of the source repository, which sets KIT_AUTOPIPE_RUNNER=modal: the place a handed-off
        stage runs."""
        return self.ctx.env.get("KIT_AUTOPIPE_RUNNER") == "modal"

    def mark(self, stage, status, record=None, **extra):
        if (self.state.get("running") or {}).get("stage") == stage:
            del self.state["running"]       # the stage ended: its record below says how
        rec = self.state["stages"].setdefault(stage, {})
        rec.update({"status": status, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **extra})
        if record is not None:
            rec["record"] = record
        self.save()
        events = getattr(self, "events", None)     # getattr: a Run made without __init__ (tests) has none
        if events is not None:
            events.stage(stage, status, extra)

    def surfaces(self, accepted=False):
        out = []
        for sid, s in sorted(self.state["surfaces"].items()):
            if accepted and not s.get("accepted"):
                continue
            out.append((sid, s))
        return out

    def call(self, name, args):
        """One agent tool, in this run's context; a ToolError becomes a recorded failure, not a crash."""
        self.log(f"{name} {json.dumps({k: v for k, v in args.items() if k != 'params'}, default=str)[:200]}")
        return self.agent.call(name, args, self.ctx)

    @property
    def target(self):
        return self.s["purpose"] == "target"

    @staticmethod
    def published(sid):
        """A published segment, not a trace of this run: the benchmark segment (seg) or a reference segment of
        score.transfer (ref-<key>). Its labels sit on its grid, so it is checked but not gated by default, never
        flattened, trimmed or refused for distortion."""
        return sid == "seg" or sid.startswith("ref-")

    @property
    def box(self):
        """The box a box prediction holds sheets in (external_prediction.box, resolved by plan_box), or None."""
        return (self.r.get("external_prediction") or {}).get("box")

    @property
    def transfer(self):
        """score.transfer when the plan asks for it, else None."""
        return (self.s.get("score") or {}).get("transfer")

    def labels_dir(self, key):
        return self.out / "labels" / key

    def published_mesh(self, key):
        return self.out / "published" / f"{key}.tifxyz"

    def fetch_labels(self, key, dest=None):
        """A labeled segment's inklabels.zarr and supervision.zarr under dest (default labels/<key>), unless
        already there."""
        from . import fetch
        lab = Path(dest) if dest else self.labels_dir(key)
        for z in ("inklabels", "supervision"):
            if not (lab / f"{z}.zarr").exists():
                fetch.fetch_prefix(f"{BENCHMARKS[key]['labels']}/{z}.zarr", lab / f"{z}.zarr", workers=8)
        return lab

    # -- stages
    def s_acquire(self):
        from . import vc3d_audit
        rec = {"volume": self.r["volume_url"], "prediction": self.r["prediction_url"],
               "normal_grids": self.r["normal_grids_url"], "voxel_um": self.r["voxel_um"]}
        for key in ("volume_url", "prediction_url"):
            url = self.r[key]
            if not url:
                continue
            try:
                store = vc3d_audit.open_store(url)
                levels, _ = vc3d_audit.levels(store)
            except Exception as exc:  # noqa: BLE001 - any read failure stops the run here, with its reason
                raise AutoError(f"{url}: headers do not read ({exc})") from exc
            rec[key.replace("_url", "_levels")] = [lv["meta"]["shape"] if lv.get("meta") else None for lv in levels]
            if any(lv.get("meta") is None for lv in levels):
                raise AutoError(f"{url}: a pyramid level has no header")
        ext = self.r.get("external_prediction")
        if ext:
            rec["external_prediction"] = self.check_external(ext)
        if self.r["benchmark"] or self.s["segment"]:
            seg = (self.r["benchmark"] or {}).get("segment") or self.s["segment"]
            got = self.call("fetch_segment", {"sample": self.r["sample"], "segment": seg, "frame": self.r["volume"],
                                              "dest": str(self.out / "segment" / f"{seg}.tifxyz")})
            rec["segment"] = {"surface": got["surface"], "source": got.get("source"), "stats": got.get("stats")}
            self.state["surfaces"]["seg"] = {"surface": got["surface"], "origin": f"published segment {seg}"}
        if self.transfer:
            rec["transfer"] = self.acquire_transfer()
        return rec

    def acquire_transfer(self):
        """score.transfer's inputs: each labeled segment's mesh in this scan's frame and its labels (kept when
        already in the run folder), and a reference surface ref-<key> for each segment the plan renders and inks
        in this run."""
        out = {}
        refs = self.transfer.get("references") or {}
        for key, b in self.r["transfer"].items():
            dest = self.published_mesh(key)
            if not (dest / "x.tif").is_file():
                got = self.call("fetch_segment", {"sample": self.r["sample"], "segment": b["segment"],
                                                  "frame": self.r["volume"], "dest": str(dest)})
                if Path(got["surface"]).resolve() != dest.resolve():
                    raise AutoError(f"fetch_segment put {key}'s mesh at {got['surface']}, not {dest}")
            self.fetch_labels(key)
            out[key] = {"mesh": str(dest), "labels": str(self.labels_dir(key)), "check": self.check_carry(key)}
            if refs.get(key) == "run":
                self.state["surfaces"][f"ref-{key}"] = {
                    "surface": str(dest), "reference": key,
                    "origin": f"published segment {b['segment']}: the paired reference of score.transfer"}
                out[key]["reference_surface"] = f"ref-{key}"
        for key, b in (self.r.get("report_overlap") or {}).items():
            # a report surface's mesh only (fetch_segment fetches the tifxyz, never labels): render records which
            # pixels of each trace lie on it. A failed fetch is recorded, and the run goes on without that record
            dest = self.report_mesh(key)
            try:
                if not (dest / "x.tif").is_file():
                    self.call("fetch_segment", {"sample": self.r["sample"], "segment": b["segment"],
                                                "frame": self.r["volume"], "dest": str(dest)})
                out[key] = {"mesh": str(dest), "labels": "never fetched: a report surface (REPORT_ONLY)"}
            except (self.agent.ToolError, OSError) as exc:
                out[key] = {"error": f"{type(exc).__name__}: {exc}"[:500],
                            "labels": "never fetched: a report surface (REPORT_ONLY)"}
        return out

    def report_mesh(self, key):
        return self.out / "report-surfaces" / f"{key}.tifxyz"

    def check_carry(self, key):
        """kit labelxfer's identity and displaced checks on one labeled segment's own mesh and labels, made here
        on the run's own copies before any trace exists (a note of the source repository: a failed check
        makes the readout VOID). Recorded, never raised."""
        from . import labelxfer
        from .verify import VerifyError
        tr = self.transfer
        try:
            res = labelxfer.check(self.published_mesh(key), self.labels_dir(key), self.out / "transfer-check" / key,
                                  voxel_um=self.r["voxel_um"], displace_mm=tr["displace_mm"],
                                  surface_shape=self.r["transfer"][key]["surface_shape"],
                                  lattice_px=tr["lattice_px"], log=self.log)
        except (VerifyError, OSError, ValueError, MemoryError) as exc:
            return {"passes": None, "error": f"{type(exc).__name__}: {exc}"}
        ident = res["identity"]
        return {"passes": res["passes"],
                "identity": {k: ident[k] for k in ("coverage", "within_one_px_share", "ink_agreement", "passes")},
                "displaced": {k: res["displaced"][k] for k in ("displace_mm", "max_dice", "passes")},
                "rule": res["rule"]}

    def check_external(self, ext):
        """A prediction from outside the catalog is the one the plan froze: its headers and its grids' metadata
        hash to what the plan recorded (a package replaced after the plan is refused, not traced)."""
        files = prediction_headers(ext["zarr"])
        if headers_digest(files) != ext["headers_sha256"]:
            raise AutoError(f"{ext['zarr']}: its headers changed after the plan was made (SHA-256 "
                            f"{headers_digest(files)[:12]}, the plan froze {ext['headers_sha256'][:12]}); make a new "
                            "plan for the new prediction")
        out = {"headers_sha256": ext["headers_sha256"], "headers": sorted(files)}
        if ext.get("normal_grids"):
            raw = _read(_store(ext["normal_grids"]), ext["normal_grids"], "metadata.json")
            got = hashlib.sha256(raw).hexdigest() if raw is not None else None
            if got != ext["grids_metadata_sha256"]:
                raise AutoError(f"{ext['normal_grids']}: metadata.json changed after the plan was made, or is gone; "
                                "make a new plan")
            out["grids_metadata_sha256"] = got
        return out

    def s_umbilicus(self):
        rec = self.umbilicus_axis()
        rec["sha256"] = vc3d_catalog.sha256_file(self.out / "umbilicus.json")
        shadow = self.s["umbilicus"].get("shadow")
        if shadow:
            rec["shadow"] = self.umbilicus_shadow(shadow, rec)
        return rec

    def umbilicus_shadow(self, names, used):
        """umbilicus.shadow: each named backend run on the same scan and measured against the axis the run uses
        (axis_distance, in voxels and um). Recorded only; a shadow that fails is recorded with its error and the
        stage goes on."""
        mine = vc3d_orient.load_umbilicus(str(self.out / "umbilicus.json"))
        out = {}
        for name in names:
            if name == used.get("estimator") or (name in ("catalog", "centerlines") and used.get("source") == name):
                out[name] = {"skipped": "the backend the run uses"}
                continue
            folder = self.out / "umbilicus-shadow" / name
            try:
                if name == "catalog":
                    if not self.r["catalog_umbilicus"]:
                        raise AutoError(f"the catalog has no umbilicus for {self.r['volume']}")
                    download(self.r["catalog_umbilicus"], folder / "umbilicus.json", tries=8)
                    path, extra = folder / "umbilicus.json", {"url": self.r["catalog_umbilicus"]}
                elif name == "centerlines":
                    setting = self.s["umbilicus"].get("centerlines") or centerlines.DEFAULTS
                    line = centerlines.pick(self.r["volume"], setting)
                    if line is None:
                        raise AutoError(f"the center lines dataset has no line for {self.r['volume']}")
                    path = folder / "umbilicus.json"
                    rec = centerlines.fetch(line, path, lambda url, d: download(url, d, tries=8), setting["rev"])
                    extra = {k: rec[k] for k in ("url", "line_source", "line_kind", "sha256", "usable_ends")}
                else:
                    res = self.call("umbilicus", {**self.umbilicus_args(folder), "estimator": [name]})
                    path, extra = Path(res["umbilicus"]), {k: res.get(k) for k in ("estimates", "kept", "seconds")}
                theirs = vc3d_orient.load_umbilicus(str(path))
                d = axis_distance(theirs, mine)
                out[name] = {"path": str(path), **extra, "voxels": d,
                             "um": {k: round(v * self.r["voxel_um"], 1) if k != "n" else v for k, v in d.items()}}
            except (AutoError, self.agent.ToolError, OSError, vc3d_orient.OrientError,
                    centerlines.CenterlineError) as exc:
                out[name] = {"error": str(exc)}
        return out

    def umbilicus_args(self, out):
        """The umbilicus tool's arguments for an estimate of this run's scan into out."""
        u = self.s["umbilicus"]
        args = {"volume": self.r["volume"], "sample": self.r["sample"], "source": "estimate", "out": str(out)}
        axis_grids = (self.r.get("external_prediction") or {}).get("axis_grids")
        if axis_grids:
            # the catalog has no grids for this scan: the estimate reads the plan's own (external_prediction)
            args.update(grids=axis_grids, voxel_um=self.r["voxel_um"], shape_zyx=self.r["shape_zyx"])
        args.update({k: u[k] for k in ("every", "repeats", "seed", "window", "max_jump_um") if u[k] is not None})
        return args

    def umbilicus_axis(self):
        u = self.s["umbilicus"]
        dest = self.out / "umbilicus.json"
        cat_url = self.r["catalog_umbilicus"]
        if u["source"] in ("auto", "catalog") and cat_url:
            download(cat_url, dest, tries=8)
            pts = vc3d_orient.load_umbilicus(str(dest))
            return {"source": "catalog", "url": cat_url, "points": len(pts), "path": str(dest)}
        if u["source"] == "catalog":
            raise AutoError(f"the catalog has no umbilicus for {self.r['volume']}")
        if u["source"] == "centerlines":
            try:
                line = centerlines.pick(self.r["volume"], u["centerlines"])
                if line is not None:
                    rec = centerlines.fetch(line, dest, lambda url, d: download(url, d, tries=8),
                                            u["centerlines"]["rev"])
                    return {**rec, "points": len(vc3d_orient.load_umbilicus(str(dest))), "path": str(dest)}
            except centerlines.CenterlineError as exc:
                raise AutoError(str(exc)) from exc
            if u.get("estimator") is None:
                raise AutoError(f"the center lines dataset has no line for {self.r['volume']}")
        elif u["source"] not in ("auto", "estimate"):
            path = self.agent.existing(self.ctx, u["source"], "umbilicus")
            shutil.copyfile(path, dest)
            return {"source": "file", "path": str(dest), "points": len(vc3d_orient.load_umbilicus(str(dest)))}
        args = {"volume": self.r["volume"], "sample": self.r["sample"], "source": "estimate",
                "out": str(self.out / "umbilicus")}
        if u.get("estimator") is not None:
            from . import apbackends
            args["estimator"] = apbackends.estimator_chain(u)
        axis_grids = (self.r.get("external_prediction") or {}).get("axis_grids")
        if axis_grids:
            # the catalog has no grids for this scan: the estimate reads the plan's own (external_prediction)
            args.update(grids=axis_grids, voxel_um=self.r["voxel_um"], shape_zyx=self.r["shape_zyx"])
        args.update({k: u[k] for k in ("every", "repeats", "seed", "window", "max_jump_um") if u[k] is not None})
        box_axis = None
        if axis_grids and self.box:
            # Grids of one box meet every 500th slice once or twice: too few for an axis. Read axis_slices slices
            # inside the box instead. vc_gen_umbilicus scores each candidate by how radially the slice's normals
            # point away from it (villa core/src/normalgridtools.cpp align_and_extract_umbilicus); the normals of
            # one box nearly agree, so they fix the direction to the axis better than its distance (Interpretation,
            # not yet measured). The seeds stage leaves out the radial band for such an axis
            z0, z1 = self.box[0]
            n = self.s["external_prediction"]["axis_slices"]
            args.update(z_range=[z0, z1], every=max(1, (z1 - z0) // n))
            box_axis = {"z_range": [z0, z1], "every": args["every"], "quality": "direction only"}
        if u.get("polish") and not box_axis:
            # one box's grids hold too few traced wraps for winding coverage: a box axis is never polished
            args["polish"] = u["polish"]
        res = self.call("umbilicus", args)
        shutil.copyfile(res["umbilicus"], dest)
        return {**res, "path": str(dest), **({"box_axis": box_axis} if box_axis else {})}

    def s_seeds(self):
        if self.state["surfaces"].get("seg"):
            return {"skipped": "a published segment replaces seeds and trace"}
        sd = self.s["seeds"]
        if sd.get("points"):
            # Seeds given in the plan (a benchmark seeded on a published winding): the trace checks each one on
            # the prediction and the CT before it grows
            return {"seeds": [list(map(float, q)) for q in sd["points"]], "stats": {"given": len(sd["points"])}}
        args = {"prediction": self.r["prediction_url"], "ct": self.r["volume_url"] if sd["ct_check"] else None,
                "umbilicus": str(self.out / "umbilicus.json"), "count": sd["count"], "voxel_um": self.r["voxel_um"],
                "z_range": sd["z_range"], "radius_um": sd["radius_um"], "level": sd["level"],
                "min_spacing_um": sd["min_spacing_um"], "seed": sd["seed"], "max_planes": sd["max_planes"]}
        bounded = self.seed_box(args)
        res = self.call("seeds", args)
        if not res["seeds"]:
            raise AutoError(f"no seed passed: {res['stats']}", kind="ours")
        (self.out / "seeds.json").write_text(json.dumps(res, indent=1))
        return {"seeds": [s["xyz"] for s in res["seeds"]], "stats": res["stats"], **({"box": bounded} if bounded
                                                                                      else {})}

    def seed_box(self, args):
        """Keep the seeds tool inside a box prediction's box, seed_margin voxels in (args changed in place); the
        record of what was bounded, or None with no box. A z_range the plan gives is cut to the box. With an
        axis estimated from the box (s_umbilicus box_axis) the radial band is left out: its distance from the
        box is the least trusted part of that axis."""
        if not self.box:
            return None
        m = self.s["external_prediction"]["seed_margin"]
        (z0, z1), (y0, y1), (x0, x1) = self.box
        lo, hi = z0 + m, z1 - m
        if args.get("z_range"):
            lo, hi = max(lo, int(args["z_range"][0])), min(hi, int(args["z_range"][1]))
            if hi <= lo:
                raise AutoError(f"seeds.z_range {args['z_range']} lies outside the prediction's box {self.box}",
                                kind="ours")
        if hi <= lo:
            raise AutoError(f"the prediction's box {self.box} leaves no height for seeds {m} voxels inside it",
                            kind="ours")
        args["z_range"] = [lo, hi]
        args["box"] = [[y0 + m, y1 - m], [x0 + m, x1 - m]]
        rec = {"box": self.box, "margin": m, "z_range": args["z_range"], "yx": args["box"]}
        umb = ((self.state["stages"].get("umbilicus") or {}).get("record") or {})
        if umb.get("box_axis"):
            args["radius_um"] = [0.0, None]
            rec["radius_band"] = "left out: the axis was estimated from this box alone (direction only)"
        return rec

    def s_trace(self):
        if self.state["surfaces"].get("seg"):
            return {"skipped": "a published segment replaces seeds and trace"}
        t = self.s["trace"]
        seeds = self.state["stages"]["seeds"]["record"]["seeds"]
        # Without normal grids the tracer has no loss that reads the scan: the surface is grown from the seed
        # by smoothness terms alone (villa GrowPatch.cpp gen_normal_loss returns no residual without them).
        # A version 1 plan has no setting and traced without them
        use = t.get("normal_grids", "off")
        grids = self.r.get("normal_grids_url") if use in ("auto", "required") else None
        if use == "required" and not grids:
            raise AutoError("trace.normal_grids is required and the plan resolved none")
        # Seeds given in the plan come from a published mesh, which sits on the sheet but not always on a voxel
        # the prediction marks: they move to the nearest such voxel within 8 voxels (snap_seed), and the CT air
        # check runs on them only with seeds.ct_check (a recto surface can sit at the papyrus edge)
        given = bool(self.s["seeds"].get("points"))
        ct_check = not given or self.s["seeds"].get("ct_check", True)
        # Every planned trace is on record in launch order (seed by seed, its repeats in turn), and every one that
        # gives no surface is recorded under its id with who decided it (trace_failure): the readout reads both.
        # A failure our chain decided is final; one of the infrastructure is tried again when the stage runs again
        repeats = t.get("repeats", 1)
        planned = [(trace_sid(i, k, repeats), i, k, xyz) for i, xyz in enumerate(seeds) for k in range(repeats)]
        self.state["planned_traces"] = [{"sid": sid, "seed_index": i, "repeat": k, "seed": list(xyz)}
                                        for sid, i, k, xyz in planned]
        failures = self.state.setdefault("trace_failures", {})
        # trace.budget (OPTIONAL, kit/tracebudget.py): budgets, snapshots and partial surfaces. A plan made without
        # it traces exactly as before. With it the traces go round by round, the first repeat of every seed before
        # any second repeat, so a work deadline goes to new seeds first (trace_budget); planned_traces keeps the
        # seed-by-seed order every reader knows
        cfg = t.get("budget")
        runtime = self.trace_runtime(cfg) if cfg else None
        if runtime is not None:
            self.state["trace_runtime"] = runtime
            # one entry per attempt of the stage: a resume on another machine keeps what the earlier one had
            self.state.setdefault("trace_runtimes", []).append(runtime)
        self.save()
        order = sorted(planned, key=lambda p: (p[2], p[1])) if cfg else planned
        made, failed, ran, deferred = [], [], [], []     # ran: the traces the tracer itself ran (the learner's Q2)
        for n, (sid, i, k, xyz) in enumerate(order):
            if sid in self.state["surfaces"]:
                made.append(sid)
                continue
            if (failures.get(sid) or {}).get("kind") == "ours":
                failed.append({"sid": sid, **failures[sid]})
                continue
            if cfg and cfg["preempted"] == "keep" and self.keep_preempted(sid, i, k, xyz, repeats, cfg):
                made.append(sid)
                continue
            given_params = t.get("params") or {}
            if self.box:
                given_params = box_trace_params(self.box, given_params)
            args = {"volume": self.r["prediction_url"], "seed": xyz, "seed_check": True,
                    "generations": t["generations"], "voxel_um": self.r["voxel_um"],
                    "params": {**given_params, "min_area_cm": t["min_area_cm"]},
                    "out": str(self.out / "traces"), "name": sid, "timeout": t["timeout"]}
            if ct_check:
                args["ct"] = self.r["volume_url"]
            if given:
                args["snap_seed"] = True
            if t.get("threads"):
                args["threads"] = t["threads"]
            if grids:
                args["normal_grids"] = grids
            budget = None
            if cfg:
                # this round's traces still to trace, this one included: they share what the deadline leaves
                left = sum(1 for p in order[n:] if p[2] == k and p[0] not in self.state["surfaces"]
                           and (failures.get(p[0]) or {}).get("kind") != "ours")
                parts = self.state.get("partial_traces") or {}
                after_short = any(parts[p2].get("kind") in ("partial_time_limit", "partial_timeout")
                                  for p2 in self.partials_of_seed(i, sid))
                budget = self.trace_budget(cfg, runtime, left, after_short, len(planned))
                if budget["defer"]:
                    # not run: not enough time for it under the work deadline, or a later repeat that would stop
                    # short. An infrastructure entry, so a rerun with more time traces it and the learner voids it
                    failures[sid] = {"seed": list(xyz), "kind": "infrastructure", "deferred": True,
                                     "reason": f"deferred: {budget['defer']}"[:600], "budget": budget}
                    failed.append({"sid": sid, **failures[sid]})
                    deferred.append(sid)
                    self.save()
                    continue
                args["timeout"] = budget["hard_timeout_s"]
                if cfg["snapshot_interval"]:
                    args["snapshot_interval"] = cfg["snapshot_interval"]
                if budget["time_limit_s"]:
                    args["time_limit_s"] = budget["time_limit_s"]
                if runtime.get("grid_cache_bytes"):
                    args["grid_cache_bytes"] = runtime["grid_cache_bytes"]
                if runtime.get("grid_cache_entries"):
                    args["grid_cache_entries"] = runtime["grid_cache_entries"]
                # an earlier attempt's folder of this id (a failure retried) goes first, so whatever is in it after
                # a lost container was written by this attempt (keep_preempted), whatever the volume's clock
                old = self.out / "traces" / sid
                if old.is_dir() and not old.is_symlink():
                    shutil.rmtree(old, ignore_errors=True)
                # the trace in flight, so a restart after a lost container finds its snapshot (keep_preempted).
                # started_fs: the start on the clock of the filesystem the trace writes to (a mark's mtime)
                now = time.time()
                (self.out / "traces").mkdir(parents=True, exist_ok=True)
                self.state["trace_inflight"] = {
                    "sid": sid, "seed": list(xyz), "budget": budget,
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "started_epoch": round(now, 1),
                    "started_fs": self.start_mark(self.out / "traces"),
                    "runtime": {kk: runtime.get(kk) for kk in ("memory_bytes", "grid_cache_bytes", "grid_cache_entries",
                                                               "class", "time_limit", "villa")}}
                self.save()
            try:
                res = self.trace_call(sid, args)
            except self.agent.ToolError as exc:
                self.state.pop("trace_inflight", None)
                failures[sid] = {"seed": list(xyz), **trace_failure(exc=exc)}
                failed.append({"sid": sid, **failures[sid]})
                self.save()
                continue
            self.state.pop("trace_inflight", None)
            ran.append(sid)
            stop = res.get("stop") or {}
            if cfg:
                speed = tracebudget.speed_record(stop.get("progress"), res.get("seconds"))
                if speed:
                    self.state.setdefault("trace_speed", {})[sid] = speed
            surf = (res.get("surfaces") or [{}])[0]
            path = surf.get("path") or surf.get("surface")
            partial = stop.get("partial") if cfg and cfg["keep_partial"] else None
            refused = bool(cfg) and bool(stop.get("partial")) and not partial    # keep_partial false
            # a timeout or cancel that came after the tracer's final save leaves the whole trace (tracebudget.
            # holds_whole_trace): a surface like any other
            whole_after_stop = bool(cfg) and bool(stop.get("whole"))
            small = bool(partial) and self.below_min_area(stop, t)
            if (res.get("exit") != 0 and not partial and not whole_after_stop) or not path or refused or small:
                failures[sid] = {"seed": list(xyz), **trace_failure(res=res, budget=cfg, min_area_cm=t["min_area_cm"]),
                                 "exit": res.get("exit"), "log_tail": res.get("log_tail")}
                if cfg:
                    failures[sid].update(stop=stop, budget=budget, grid_cache=res.get("grid_cache"))
                failed.append({"sid": sid, **failures[sid]})
                self.save()
                continue
            failures.pop(sid, None)
            ng = res.get("normal_grids") or {}
            sc = res.get("seed_check") or {}
            if sc.get("moved_from"):
                xyz = sc.get("nearest_on")
            self.state["surfaces"][sid] = {"surface": path, "origin": f"trace from seed {xyz}"
                                           + (f" (moved from {sc['moved_from']})" if sc.get("moved_from") else "")
                                           + (f", repeat {k} of {repeats}" if repeats > 1 else "")
                                           + (f", partial: stopped after generation {stop.get('generations_done')} "
                                              f"of {t['generations'] - 1} ({partial})" if partial else ""),
                                           "seed_index": i, "repeat": k,
                                           "trace": {**{k: surf.get(k) for k in ("grid_rows_cols", "valid_fraction",
                                                                                 "area_cm2")},
                                                     "normal_grids": bool(grids),
                                                     # grid_files is the folder's total after the trace (for
                                                     # streamed grids the shared cache, so every trace of that grid
                                                     # set so far); grid_files_fetched is what the cache gained
                                                     # during this trace (streamed grids only)
                                                     "grid_files": ng.get("files"),
                                                     "grid_files_fetched": ng.get("files_fetched"),
                                                     "grid_missing": ng.get("missing"),
                                                     "grid_false_missing": ng.get("false_missing"),
                                                     # 404 markers whose bucket state could not be read, or past
                                                     # the check limit: some may be false 404s (check_grid_missing)
                                                     "grid_unchecked": ng.get("unchecked"),
                                                     # streamed grids VC3D failed to fetch during this trace (the
                                                     # trace tool's check_grid_fetches): qa reports them
                                                     "grid_remote": ng.get("remote"),
                                                     "grid_fetch_failed": ng.get("fetch_failed"),
                                                     "grid_fetch_failed_sample": ng.get("fetch_failed_sample"),
                                                     "grid_refetch_failed": ng.get("refetch_failed")}}
            if cfg:
                rec = self.state["surfaces"][sid]["trace"]
                rec.update(stop=stop, budget=budget, seconds=res.get("seconds"), grid_cache=res.get("grid_cache"),
                           villa=runtime.get("villa"))
                if res.get("time_limit"):
                    rec["time_limit"] = res["time_limit"]
                earlier = self.partials_of_seed(i, sid)
                if earlier:
                    # an earlier repeat of this seed stopped short; this one ran under the same rule, calibrated
                    # by the speed measured on it (trace_budget)
                    rec["after_partial_of"] = earlier
                if partial:
                    self.note_partial(sid, i, k, partial, stop, budget, res.get("seconds"), earlier)
            for name in TRACE_METHODS:
                if res.get(name):
                    self.state["surfaces"][sid][name] = res[name]
            self.save()
            made.append(sid)
        if not made:
            kind = "infrastructure" if any(f["kind"] != "ours" for f in failed) else "ours"
            raise AutoError(f"no trace grew a surface: {json.dumps(failed, default=str)[:3000]}", kind=kind)
        out = {"surfaces": made, "failed": failed, "ran": ran}
        if cfg:
            partials = sorted(sid for sid in made if sid in (self.state.get("partial_traces") or {}))
            out.update(partial=partials, deferred=deferred, runtime=runtime,
                       order=[p[0] for p in order])
            if runtime.get("warning"):
                out["warning"] = runtime["warning"]
        return out

    # -- trace.budget (kit/tracebudget.py)
    def trace_runtime(self, cfg):
        """What this machine gives the plan's traces, recorded in state["trace_runtime"] (and, one per attempt of the
        stage, state["trace_runtimes"]) and the trace stage's record: the tracer's features (time limit, grid cache
        kind), the villa commit and patch bundles the image names (KIT_VILLA_REV, KIT_VILLA_PATCHES), the memory,
        the normal-grid cache variables from the plan's rule (tracebudget.grid_settings: VC_GRID_CACHE_BYTES on
        villa main, VC_NORMAL_GRID_CACHE on villa e0bbb8b with the grid-cache bundle), the cost model's cache class
        and whether time_limit_s is passed. The plan holds the rule (its digest covers it); the run records the
        values it resolved to here, since the memory is the runner's, not the planner's. A "thrash" class gives a
        warning: on that build the budgets only turn timeouts into partial surfaces."""
        from . import vc3d
        try:
            feats = vc3d.tracer_features(self.ctx.tools(), self.ctx.env)
        except Exception as exc:        # no VC3D here: the trace tool says so when it runs; cost as plain villa
            feats = {"time_limit": False, "snapshots": True, "grid_cache": "unknown",
                     "how": f"not read: {exc}"[:300], "files": []}
        memory = vc3d.memory_limit(self.ctx.env)
        generations = self.s["trace"]["generations"]
        grid = tracebudget.grid_settings(cfg, feats, memory, self.ctx.env, generations)
        rec = {"features": {k: feats.get(k) for k in ("time_limit", "snapshots", "grid_cache", "how")},
               "villa": {"rev": self.ctx.env.get("KIT_VILLA_REV") or None,
                         "patches": self.ctx.env.get("KIT_VILLA_PATCHES") or None},
               "memory_bytes": memory, "memory_from": "KIT_MEMORY_BYTES" if self.ctx.env.get("KIT_MEMORY_BYTES")
               else "cgroup or the machine",
               "grid_cache_bytes": grid["grid_cache_bytes"], "grid_cache_entries": grid["grid_cache_entries"],
               "grid_cache_from": {"VC_GRID_CACHE_BYTES": grid["bytes_from"],
                                   "VC_NORMAL_GRID_CACHE": grid["entries_from"]},
               "class": grid["class"],
               "time_limit": bool(feats.get("time_limit")) and cfg["time_limit"] == "auto",
               "deadline": self.work_deadline(),
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if grid["class"] == "thrash":
            rec["warning"] = (f"this tracer's normal-grid cache does not hold a {generations}-generation trace's grids "
                              f"(build kind {grid['kind']}): traces run several times slower, so budgets mostly turn "
                              "timeouts into partial surfaces. Run on villa main (VC_GRID_CACHE_BYTES) or the "
                              "grid-cache image")
        return rec

    def work_deadline(self):
        """The runner's work deadline in epoch seconds (KIT_AUTOPIPE_DEADLINE), or None."""
        try:
            v = float(self.ctx.env.get("KIT_AUTOPIPE_DEADLINE") or "")
        except ValueError:
            return None
        return v if math.isfinite(v) and v > 0 else None

    def trace_budget(self, cfg, runtime, traces_left, after_short=False, surfaces=None):
        """The next trace's budget (tracebudget.budget): cold for the run's first trace, calibrated by the seconds
        per vertex measured on the run's earlier traces, at the tracer threads the trace tool uses, with a safety
        margin from the slowest generation measured, and a share of the work deadline for the traces left in its
        round (traces_left; surfaces: every planned trace, for the reserve), and after_short when an earlier repeat
        of the seed stopped short at its budget (tracebudget.budget defers it then unless it fits). On Modal
        (MODAL_TASK_ID) with no
        deadline the budget is held to trace.timeout: the function's own timeout would otherwise end the run."""
        from . import vc3d
        t = self.s["trace"]
        speeds = self.state.get("trace_speed") or {}
        deadline = self.work_deadline()
        threads = t.get("threads") or min(4, vc3d.cpu_limit())
        ceiling = t["timeout"] if deadline is None and self.ctx.env.get("MODAL_TASK_ID") else None
        return tracebudget.budget(cfg, t["generations"], t["timeout"], runtime["class"], cold=not speeds,
                                  measured=tracebudget.measured_rate(speeds), deadline=deadline, now=time.time(),
                                  traces_left=traces_left, time_limit=runtime["time_limit"], threads=threads,
                                  after_short=after_short, surfaces=surfaces,
                                  slowest_generation_s=tracebudget.slowest_generation(speeds), ceiling_s=ceiling)

    def start_mark(self, folder):
        """When a trace starts, on the clock of the filesystem it writes to: the mtime of a mark file written into
        `folder` (vc3d_agent._start_mark), or this machine's clock when the agent has no such helper."""
        mark = getattr(self.agent, "_start_mark", None)
        try:
            return round(mark(folder), 3) if mark else round(time.time(), 3)
        except OSError:
            return round(time.time(), 3)

    @staticmethod
    def below_min_area(stop, t):
        """True when a partial surface is smaller than trace.min_area_cm: villa applies min_area_cm only at a
        normal end (vc_grow_seg_from_seed deletes a smaller final save), never to a snapshot, so AP applies it."""
        area, least = stop.get("area_cm2"), t.get("min_area_cm") or 0
        return isinstance(area, (int, float)) and not isinstance(area, bool) and least > 0 and area < least

    def partials_of_seed(self, seed_index, sid):
        """The earlier traces of the same seed that stopped short (partial surfaces), in launch order."""
        parts = self.state.get("partial_traces") or {}
        return [p for p, rec in parts.items() if rec.get("seed_index") == seed_index and p != sid]

    def note_partial(self, sid, i, k, kind, stop, budget, seconds, earlier=()):
        """state["partial_traces"][sid]: a partial surface on record, apart from failures and whole traces, so
        reports, readouts and the monitor show it."""
        self.state.setdefault("partial_traces", {})[sid] = {
            "kind": kind, "reason": stop.get("reason"), "seed_index": i, "repeat": k,
            "generations_done": stop.get("generations_done"), "generations_planned": self.s["trace"]["generations"],
            "area_cm2": stop.get("area_cm2"), "elapsed_time_s": stop.get("elapsed_time_s"), "seconds": seconds,
            **({k2: budget.get(k2) for k2 in ("budget_s", "time_limit_s", "hard_timeout_s", "estimate_s")}
               if budget else {}),
            **({"after_partial_of": list(earlier)} if earlier else {})}

    def keep_preempted(self, sid, i, k, xyz, repeats, cfg):
        """trace.budget.preempted "keep": the trace in flight when the last process or container was lost (its
        state["trace_inflight"]) left a complete surface in traces/<sid>, so it is recorded instead of tracing the
        same seed again from generation 1: as a whole surface when it holds the whole trace (the tracer saved before
        the loss), as partial_time_limit when the patched tracer stopped at its limit and saved, else as
        partial_preempted (its last snapshot). A complete copy villa's save fallback left in traces/.tmp_*/<sid> is
        put back first (tracebudget.recover_snapshot), and the save's leftovers are removed. A partial surface under
        trace.min_area_cm is traced again. Growth is not resumed from it: villa's resume skips the generation-8
        solve and starts in its hole-filling branch, so a resumed trace is not the trace the plan describes
        (a note of the source repository). Only this attempt can have written the folder: s_trace removes an earlier
        attempt's folder of the id before tracing, and `since` is the start on the volume's own clock. True when
        kept."""
        inflight = self.state.get("trace_inflight") or {}
        if inflight.get("sid") != sid:
            return False
        folder = self.out / "traces" / sid
        since = inflight.get("started_fs", inflight.get("started_epoch"))
        since = since if isinstance(since, (int, float)) and not isinstance(since, bool) else None
        recovered = tracebudget.recover_snapshot(folder, since=since)
        drop = getattr(self.agent, "_drop_save_leftovers", None)
        if drop:
            drop(self.out / "traces", sid)
        snap = tracebudget.read_snapshot(folder, since=since)
        self.state.pop("trace_inflight", None)
        t = self.s["trace"]
        G = t["generations"]
        kind = tracebudget.preempted_kind(snap, G) if snap["ok"] else None
        why = None
        if not snap["ok"]:
            why = snap.get("why")
        elif kind and self.below_min_area(snap, t):
            why = f"a partial surface of {snap.get('area_cm2')} cm2, under trace.min_area_cm {t['min_area_cm']}"
        if why:
            self.state.setdefault("trace_preempted", {})[sid] = {"kept": False, "why": why}
            self.save()
            return False
        try:
            stats = self.agent.tifxyz_stats(folder, self.r.get("voxel_um"))
        except Exception as exc:        # an unreadable snapshot is traced again
            self.state.setdefault("trace_preempted", {})[sid] = {"kept": False, "why": f"does not read: {exc}"[:300]}
            self.save()
            return False
        last = G - 1          # the last generation the plan places
        whole = kind is None
        done = tracebudget.whole_generations(snap, G) if whole else snap.get("generations_done")
        stop = {"exit": "lost", "reason": "the process or container was lost mid-trace"
                + (", after the tracer saved its whole surface" if whole else
                   ", after the tracer stopped at its time limit and saved" if kind == "partial_time_limit" else ""),
                "partial": kind, "whole": whole, "snapshot": kind == "partial_preempted", "generations_planned": G,
                **{k2: snap.get(k2) for k2 in ("max_gen", "area_cm2", "elapsed_time_s", "stop_reason")},
                "generations_done": done}
        if recovered:
            stop["recovered_from"] = recovered.get("recovered_from")
        seed = (json.loads((folder / "meta.json").read_text()) or {}).get("seed") or list(xyz)
        self.state["surfaces"][sid] = {
            "surface": str(folder), "seed_index": i, "repeat": k,
            "origin": f"trace from seed {seed}" + (f", repeat {k} of {repeats}" if repeats > 1 else "")
                      + ("" if whole else f", partial: stopped after generation {done} of {last} ({kind})"),
            "trace": {**{k2: stats.get(k2) for k2 in ("grid_rows_cols", "valid_fraction", "area_cm2")},
                      "normal_grids": bool(self.r.get("normal_grids_url")) and
                      t.get("normal_grids", "off") in ("auto", "required"),
                      "stop": stop, "budget": inflight.get("budget"), "started": inflight.get("started"),
                      "runtime": inflight.get("runtime"),
                      "villa": (inflight.get("runtime") or {}).get("villa")}}
        self.state.setdefault("trace_preempted", {})[sid] = {"kept": True, "whole": whole, "kind": kind,
                                                             "generations_done": done}
        if not whole:
            earlier = self.partials_of_seed(i, sid)
            self.note_partial(sid, i, k, kind, stop, inflight.get("budget"), None, earlier)
        self.save()
        return True

    def bench_refs(self):
        """The reference folder kit surfbench scores against: KIT_SURFBENCH_REFS, else its default in the kit home."""
        from . import surfbench
        given = self.ctx.env.get("KIT_SURFBENCH_REFS")
        return Path(given) if given else self.ctx.root / surfbench.REL_REFS

    def s_bench(self):
        """Each trace measured against the published windings it lies among (kit surfbench: dominant-winding
        precision, coverage, switch edges, with controls at its site). Recorded, never a gate: acceptance stays
        the qa rule, which has to work on scans with no references. A measurement that cannot be made fails the
        stage, so a benchmark run never goes on unmeasured."""
        wb = self.r.get("winding_bench")
        if not wb:
            return {"skipped": "no published windings in this scan's frame to measure traces against"}
        from . import surfbench
        if wb["rule_digest"] != surfbench.RULE_DIGEST:
            raise AutoError(f"the plan froze winding benchmark rule {wb['rule_digest'][:12]}; this kit has "
                            f"{surfbench.RULE_DIGEST[:12]}. Make a new plan (a changed rule is a new run)")
        todo = [(sid, s) for sid, s in self.surfaces() if not self.published(sid) and "bench" not in s]
        refs = self.bench_refs()
        workers = self.s["trace"].get("threads") or 2
        try:
            if todo and not (refs / "manifest.json").is_file():
                self.log(f"bench: building the references in {refs}")
                surfbench.build_refs(refs, log=self.log, workers=workers)
            if todo and not (refs / "audit.json").is_file():
                self.log("bench: seating audit of the references")
                surfbench.audit(refs, cache_dir=refs.parent.parent / "cache", log=self.log, workers=workers)
            for sid, s in todo:
                res = surfbench.score(s["surface"], refs, workers=workers, log=self.log)
                (self.out / "bench").mkdir(exist_ok=True)
                (self.out / "bench" / f"{sid}.json").write_text(json.dumps(res, indent=1, default=str))
                m = res.get("metrics") or {}
                s["bench"] = {"verdict": res.get("verdict"), "valid": res.get("valid"),
                              "invalid_reasons": res.get("invalid_reasons"),
                              "d4": m.get("d4"), "d2": m.get("d2"), "switches": m.get("switches"),
                              "recall_d4": m.get("recall_d4"),
                              "dominant_covered_cm2": m.get("dominant_covered_cm2"),
                              "dominant_split": m.get("dominant_split"),
                              "rule_digest": res.get("rule_digest"), "manifest_digest": res.get("manifest_digest"),
                              "audit_digest": res.get("audit_digest"), "path": str(self.out / "bench" / f"{sid}.json")}
                kind = (((s.get("trace") or {}).get("stop")) or {}).get("partial")
                if kind:
                    # a partial surface (trace.budget) is measured as it is; its verdict says it stopped short
                    s["bench"]["partial"] = kind
                self.save()
        except surfbench.BenchError as exc:
            raise AutoError(f"winding benchmark: {exc}") from exc
        return {sid: (s.get("bench") or {}).get("verdict") for sid, s in self.surfaces() if not self.published(sid)}

    def qa_one(self, sid, s):
        from . import meshqa
        q = self.s["qa"]
        surface = s["surface"]
        strict = self.s.get("strict") or {}
        rec, reasons, warnings = {}, [], []
        traced = s.get("trace") or {}
        if "normal_grids" in traced:
            rec["data_term"] = "normal grids" if traced["normal_grids"] else "none"
            if not traced["normal_grids"] and q.get("require_data_term", False):
                reasons.append("traced without normal grids: no loss read the scan, so the surface is the seed "
                               "extrapolated by smoothness alone")
        if traced.get("normal_grids"):
            warn = self.grid_losses(traced)
            rec["grid_fetches"] = {k: traced.get(k) for k in ("grid_remote", "grid_files_fetched",
                                                              "grid_fetch_failed", "grid_refetch_failed",
                                                              "grid_false_missing", "grid_unchecked")}
            if warn:
                warnings.append(warn)
        chk = self.call("check_surface", {"surface": surface, "volume": self.r["volume_url"], "windows": q["windows"],
                                          "umbilicus": str(self.out / "umbilicus.json"), "voxel_um": self.r["voxel_um"]})
        rec["check_surface"] = {k: chk.get(k) for k in ("verdict", "findings", "grid", "selfcross")}
        seat = chk.get("seating") or {}
        rec["seating"] = {k: seat.get(k) for k in ("verdict", "seated_windows", "better_frame")}
        orient = chk.get("orientation") or {}
        rec["orientation"] = {k: orient.get(k) for k in ("checked", "normal", "team_order", "layout", "advice", "why")
                              if k in orient}
        # reasons that rest only on a check that could not run (unmeasured): a rejection made of nothing else is not
        # the rule's verdict but the infrastructure's (FAILURE_KINDS; the preregistration's amendment of 10 Oct 2026)
        unmeasured = []
        grid = chk.get("grid") or {}
        if (grid.get("valid_fraction") or 0) < q["min_valid_fraction"]:
            reasons.append(f"valid fraction {grid.get('valid_fraction')} is under {q['min_valid_fraction']}")
        sc_rec = chk.get("selfcross")
        sc = (sc_rec or {}).get("transverse")
        if sc is None:
            reasons.append("self-intersections: not measured (" + (
                "vc_tifxyz_selfcross is not installed" if sc_rec is None else
                f"vc_tifxyz_selfcross exited {sc_rec.get('exit')} with no readable report: {sc_rec.get('error')}")
                + ")")
            unmeasured.append(reasons[-1])
        elif (q.get("crop") or {}).get("selfcross_per_cm2") is not None:
            tol = q["crop"]["selfcross_per_cm2"]
            area = self.surface_cm2(surface)
            rate = sc / area if area else math.inf
            rec["selfcross_rate"] = {"transverse": sc, "area_cm2": round(area, 4), "per_cm2": round(rate, 3),
                                     "tolerance_per_cm2": tol}
            if rate > tol:
                reasons.append(f"self-intersections: {sc} ({rate:.1f} per cm2, over {tol:g})")
        elif sc > q["max_selfcross"]:
            reasons.append(f"self-intersections: {sc}")
        if q.get("crop"):
            # what Run.crop_one cuts by: the located crossings and check_surface's own seating windows
            rec["crop_inputs"] = {"selfcross_report": (sc_rec or {}).get("report"),
                                  "seating": {k: seat.get(k) for k in ("level", "scale_segmentation", "windows",
                                                                       "candidates") if k in seat}}
        verdict = seat.get("verdict")
        need = q["require_seated"]
        if (need == "all" and verdict != "seated") or (need == "any" and verdict not in ("seated", "partly seated")):
            reasons.append(f"seating: {verdict}")
            lost, decided = self.seating_unmeasured(seat, need)
            if lost:
                reasons[-1] += f" ({lost})"
            if not decided:
                unmeasured.append(reasons[-1])
        for f in chk.get("findings") or []:
            if f.startswith("orientation"):
                reasons.append(f)
        if q["validity"]:
            patch = meshqa.load_patch(surface)
            findings = meshqa.validate_patch(patch)
            worst = meshqa.worst_severity(findings)
            rec["validity"] = {"worst": worst, "findings": findings[:20]}
            if worst == "error":
                reasons.append("VC3D's loader rules: " + "; ".join(f.get("message", str(f)) for f in findings
                                                                  if f.get("severity") == "error")[:300])
        if q["windaudit"] != "off":
            try:
                w = meshqa.wind_audit(surface, umbilicus=str(self.out / "umbilicus.json"),
                                      pitch=q["wind_pitch"] or "auto")
                rec["windaudit"] = {"gate": w["gate"], "mergers": {k: w["mergers"][k] for k in
                                                                   ("outer", "core", "full_turn", "outer_fraction")},
                                    "pitch": self.wind_pitch_record(w.get("pitch"))}
                if w["gate"]["local_failed"]:
                    reasons.append(f"winding audit: {w['gate']['full_turn_fusions']} full-turn fusions, "
                                   f"{w['gate'].get('multi_turn_skips', 0)} multi-turn skips, "
                                   f"{w['gate']['broad_fusions']} broad (a sheet switch or merger)")
            except meshqa.MeshQAError as exc:
                # Why an automatic pitch failed (meshqa.PitchFitError.reason): "span", too little of a turn to fit
                # one, which auto lets pass unaudited; "concentration", a turn or more that follows no one spiral
                # about the axis, which is a finding about the surface or the axis, not a small patch. Until 9 Oct
                # 2026 both passed here as "span" (both messages name --pitch auto), so a plan without
                # strict.windaudit_unfit keeps that verdict and carries a warning
                fit = getattr(exc, "reason", None)
                rec["windaudit"] = {"error": str(exc), "audited": False, **({"pitch_fit": fit} if fit else {})}
                if q["windaudit"] == "required" or fit not in ("span", "concentration"):
                    reasons.append(f"winding audit could not run: {exc}")
                    if fit is None:     # not a pitch-fit result: the audit did not run (axis, surface or file)
                        unmeasured.append(reasons[-1])
                elif fit == "span":
                    rec["windaudit"]["why"] = ("no winding pitch could be fitted to this patch (too little of a "
                                               "turn); not audited, and qa.windaudit required would reject it")
                elif strict.get("windaudit_unfit"):
                    reasons.append(f"winding audit fitted no pitch to a patch of a turn or more: {exc}")
                else:
                    rec["windaudit"]["why"] = ("the patch spans a turn or more but follows no one spiral about the "
                                               "axis (a crushed sheet, an axis off the core, or not one winding); "
                                               "not audited, and strict.windaudit_unfit would reject it")
                    warnings.append(f"winding audit not run on a patch of a turn or more: {exc}")
        rec["accepted"] = not reasons
        rec["reasons"] = reasons
        rec["warnings"] = warnings
        if unmeasured:
            rec["unmeasured"] = unmeasured
        if reasons and len(unmeasured) == len(reasons):
            # no check that ran rejected it: the rule did not decide (s_qa keeps this kind; trace_entries reads it)
            rec["failure"] = {"kind": "infrastructure", "reason": "rejected only by checks that could not run: "
                                                                  + "; ".join(unmeasured)}
        # every check with what it measured and the threshold it was held to (kit/qareasons.py; added 22 Oct 2026,
        # after a tracing run's reader could not say why its traces failed): the reasons above still decide
        rec["checks"] = qareasons.checks(rec, q)
        return rec

    def surface_cm2(self, surface):
        """VC3D's area of a tifxyz in cm2 at the plan's voxel size (kit/regioncrop.py coordinate_unit_um, which
        reads villa's original_volume_downscale from its meta.json)."""
        from . import regioncrop
        xyz, valid, meta, _ = regioncrop.read(surface)
        unit, _ = regioncrop.coordinate_unit_um(meta, self.r.get("voxel_um"))
        if unit is None:
            raise AutoError(f"{surface}: no voxel size for its area")
        return regioncrop.area_vx2(xyz, valid) * (unit * 1e-4) ** 2

    def crop_one(self, sid, s, rec):
        """qa.crop for a trace qa rejected for its self-intersections, seating or winding audit: kit meshqa crop
        cuts it into pieces under cropped/<sid>/, each piece is checked again by the same qa rule (Run.qa_one), and
        each that passes becomes surface <sid>-rNN with crop_of = sid. Returns (the trace's qa record with a "crop"
        record, {piece id: surface entry}); the trace stays rejected. A crop that cannot run leaves the rejection as
        it was, with the reason."""
        from . import regioncrop
        cfg = self.s["qa"]["crop"]
        inputs = rec.get("crop_inputs") or {}
        least = max(cfg["min_area_cm2"], self.s["trace"].get("min_area_cm") or 0.0)
        P = regioncrop.merged({"selfcross": {"dilate": cfg["dilate"], "per_cm2": cfg["selfcross_per_cm2"]},
                               "off_sheet": {"min_cells": cfg["off_min_cells"]},
                               "seating": {"window_cells": cfg["window_cells"],
                                           "fail": [] if cfg["seating"] == "off" else ["not seated"]},
                               "regions": {"min_area_cm2": least, "max_off_share": cfg["max_off_share"]}})
        out = self.out / "cropped" / sid
        crec = {"params_digest": regioncrop.params_digest(P), "out": str(out), "seating_source": cfg["seating"],
                "min_area_cm2": least}
        seat = inputs.get("seating") or {}
        try:
            windows = seat if cfg["seating"] == "check" and (seat.get("windows") or seat.get("candidates")) else None
            res = regioncrop.crop(s["surface"], out, selfcross=inputs.get("selfcross_report"), windows=windows,
                                  ct=self.r["volume_url"] if cfg["seating"] == "grid" else None,
                                  prediction=self.r.get("prediction_url"), voxel_um=self.r.get("voxel_um"),
                                  params=P, overwrite=True,
                                  cache_dir=self.ctx.root / "work" / "surfbench" / "cache" if self.ctx else None)
        except Exception as exc:  # noqa: BLE001 - any failure leaves the rejection as it was, with the reason
            crec.update(done=False, error=f"{type(exc).__name__}: {exc}"[:500])
            return {**rec, "crop": crec}, {}
        crec.update(done=True, **{k: res.get(k) for k in ("area_cm2", "kept_area_cm2", "kept_share", "cut_vertices",
                                                          "measured", "dropped_small", "whole_trace")})
        (self.out / "cropped").mkdir(parents=True, exist_ok=True)
        (self.out / "cropped" / f"{sid}.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
        pieces, rows = {}, []
        for r in res["regions"]:
            pid = f"{sid}-r{r['index']:02d}"
            again = self.qa_one(pid, {**s, "surface": r["path"]})
            again.pop("crop_inputs", None)
            ok = again["accepted"]
            again["crop_of"] = sid
            if not ok:
                again.setdefault("failure", {"kind": "ours"})
            pieces[pid] = {"surface": r["path"], "crop_of": sid, "qa": again, "accepted": ok,
                           **({"trace": {"normal_grids": (s.get("trace") or {}).get("normal_grids")}}
                              if "trace" in s else {})}
            rows.append({"sid": pid, "area_cm2": r.get("area_cm2"), "accepted": ok,
                         **({} if ok else {"reasons": again["reasons"]})})
        crec["pieces"] = rows
        crec["accepted_cm2"] = round(sum(x["area_cm2"] or 0 for x in rows if x["accepted"]), 5)
        return {**rec, "crop": crec}, pieces

    def repair_one(self, sid, s, rec):
        """qa.repair for a trace qa rejected for a sheet switch: kit switchfix cuts it back to its seed's winding
        (method barrier: `kit switchfix barrier`, the seed's part under kit.sheetgap's contact barrier; method
        switchfix: `kit switchfix repair`) into repaired/<sid>, the copy is checked by the same qa rule, and it replaces the trace (s["surface"]; the
        trace stays at s["surface_traced"]) only when it passes and keeps min_area_share of the trace's area.
        Returns the qa record that stands: the copy's, with the trace's under "before_repair", or the trace's with
        a "repair" record saying why the copy was not taken."""
        from . import switchfix
        cfg = self.s["qa"]["repair"]
        out = self.out / "repaired" / sid
        barrier = cfg["method"] == "barrier"
        rep = {"method": cfg["method"], "out": str(out), "min_area_share": cfg["min_area_share"],
               **({"barrier_digest": switchfix.barrier_digest()} if barrier
                  else {"params_digest": switchfix.params_digest()})}
        seed = next((p.get("seed") for p in self.state.get("planned_traces") or [] if p.get("sid") == sid), None)
        try:
            xyz, _, meta = switchfix.read_surface(s["surface"])
            before = switchfix.surface_area_vx2(xyz)
            cache = self.ctx.root / "work" / "surfbench" / "cache"
            seed_arg = None if switchfix.seed_of(meta) else seed
            if barrier:
                got = switchfix.barrier(s["surface"], out, switchfix.open_field(self.r["prediction_url"], cache),
                                        seed=seed_arg, record_path=self.out / "repaired" / f"{sid}.json",
                                        overwrite=True, prediction_label=self.r["prediction_url"])
            else:
                sampler = switchfix.open_prediction(self.r["prediction_url"], cache, workers=4)
                got, _ = switchfix.repair(s["surface"], out, sampler, seed=seed_arg,
                                          record_path=self.out / "repaired" / f"{sid}.json", overwrite=True,
                                          prediction_label=self.r["prediction_url"])
        except Exception as exc:  # noqa: BLE001 - any failure leaves the rejection as it was, with the reason
            rep.update(done=False, error=f"{type(exc).__name__}: {exc}"[:500])
            return {**rec, "repair": rep}
        after = switchfix.surface_area_vx2(switchfix.read_surface(out)[0])
        share = after / before if before > 0 else 0.0
        det = got.get("detect") or {}
        rep.update(done=True, area_share=round(share, 4), flagged=det.get("flagged"), kept=det.get("kept"))
        if share < cfg["min_area_share"]:
            rep.update(taken=False, why=f"the cut keeps {share:.3f} of the area, under {cfg['min_area_share']}")
            return {**rec, "repair": rep}
        again = self.qa_one(sid, {**s, "surface": str(out)})
        if not again["accepted"]:
            rep.update(taken=False, why="the cut copy fails qa: " + "; ".join(again["reasons"]),
                       qa=again)
            return {**rec, "repair": rep}
        rep["taken"] = True
        s["surface_traced"], s["surface"] = s["surface"], str(out)
        s["repair"] = rep
        return {**again, "repair": rep, "before_repair": {k: rec.get(k) for k in ("reasons", "warnings",
                                                                                  "check_surface", "windaudit",
                                                                                  "checks")}}

    def extend_one(self, sid, s, rec):
        """qa.extend for an accepted trace: vc_extend_edge (the agent tool `extend`) grows a copy past its edges
        into extended/<sid>, the copy is checked by the same qa rule, and it replaces the trace (kept at
        s["surface_before_extend"]) only when it passes. Returns the qa record that stands: the copy's, with an
        "extend" record and the trace's under "before_extend", or the trace's with an "extend" record saying why
        the copy was not taken."""
        cfg = self.s["qa"]["extend"]
        out = self.out / "extended" / sid
        normals = self.r.get("prediction_url") if cfg["normals"] == "prediction" else self.r["volume_url"]
        ext = {"out": str(out), "normals": cfg["normals"], "normals_volume": normals,
               **{k: cfg[k] for k in ("sides", "cells", "rounds")}}
        if not normals:
            ext.update(done=False, taken=False, why=f"the plan has no {cfg['normals']} volume for the normals")
            return {**rec, "extend": ext}
        try:
            res = self.call("extend", {"surface": s["surface"], "normals": normals, "out": str(out),
                                       "sides": list(cfg["sides"]), "cells": cfg["cells"], "rounds": cfg["rounds"],
                                       "timeout": cfg["timeout"]})
        except Exception as exc:  # noqa: BLE001 - the trace stands as it was, with the reason
            res = {"error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(res, dict) or res.get("exit") != 0 or not vc3d_io.is_tifxyz(out):
            why = (res.get("error") or f"exit {res.get('exit')}") if isinstance(res, dict) else str(res)
            ext.update(done=False, taken=False, why=f"vc_extend_edge did not finish: {why}"[:500])
            return {**rec, "extend": ext}
        ext.update(done=True, added=res.get("added"), grid_before=res.get("grid_before"),
                   grid_after=res.get("grid_after"), seconds=res.get("seconds"))
        if not res.get("added"):
            ext.update(taken=False, why="no vertex was added (no edge to grow)")
            return {**rec, "extend": ext}
        again = self.qa_one(sid, {**s, "surface": str(out)})
        if not again["accepted"]:
            ext.update(taken=False, why="the grown copy fails qa: " + "; ".join(again["reasons"]))
            return {**rec, "extend": ext}
        ext["taken"] = True
        s["surface_before_extend"], s["surface"] = s["surface"], str(out)
        s["extend"] = ext
        return {**again, "extend": ext, "before_extend": {k: rec.get(k) for k in ("warnings", "check_surface",
                                                                                  "checks")}}

    @staticmethod
    def seating_unmeasured(seat, need):
        """(what of the seating check did not run, or "", whether the windows that did run decide the rejection by
        themselves) for a surface qa.require_seated `need` rejects. A window did not run when its probe render
        exited non-zero (a relay or fetch error, a tool that could not start, a time limit) or exited 0 with no
        readable stack (no coverage measured; kit/vc3d_agent.py _seating). With "all" the windows that ran decide
        when one of them is not seated; with "any" when another window could not have seated it, that is, when
        every window ran. No seating record at all is no measurement."""
        from . import vc3d_seat
        wins = seat.get("windows") or (seat.get("candidates") or [])[:1]
        if not wins:
            return "no seating record: not measured", False
        def lost(w):
            return w.get("exit") != 0 or w.get("coverage") is None
        gone, ran = [w for w in wins if lost(w)], [w for w in wins if not lost(w)]
        if not gone:
            return "", True
        seated = sum((w.get("verdict") or vc3d_seat.verdict(w)) == "seated" for w in ran)
        how = sorted({f"exited {w.get('exit')}" if w.get("exit") != 0 else "wrote no readable stack" for w in gone})
        return (f"{len(gone)} of {len(wins)} windows not measured: the probe {', '.join(how)}",
                (seated < len(ran)) if need == "all" else False)

    @staticmethod
    def wind_pitch_record(pitch):
        """The pitch the winding audit used, as qa records it: its source and value, and for an automatic fit its
        concentration, handedness and span in turns. An audit that passed may have used a wrong pitch: on synthetic
        spirals of pitch 20 with the axis 5 to 150 voxels off, the fit gave 19.4 to 400.7 at concentrations 0.44 to
        0.55, above meshqa's 0.4, and the audit passed. So the fitted value is kept, to be read against the scroll's
        expected wrap spacing; the plan holds no such spacing, so qa does not judge it."""
        if not isinstance(pitch, dict):
            return None
        out = {"source": pitch.get("source"), "value": pitch.get("value")}
        auto = pitch.get("auto") or {}
        out.update({k: auto[k] for k in ("concentration", "other_handedness", "handedness", "span_turns")
                    if k in auto})
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in out.items()}

    @staticmethod
    def grid_losses(traced):
        """A warning for a trace that went without some of its normal grids, or None. qa.require_data_term sees
        only that grids were configured; VC3D skips a slice's normals for the rest of a run when its grid file
        fails to fetch (villa NormalGridVolume caches a null grid; kit/vc3d_agent.py check_grid_fetches counts
        them from the log) or answers a false 404 (check_grid_missing). A 404 marker whose bucket state could not
        be read, or past check_grid_missing's limit, is counted as unchecked: it may be a false 404 too, so it is
        said, not taken as a true one. Local grid folders are not fetched."""
        if traced.get("grid_remote") is False:
            return None
        failed, false404 = traced.get("grid_fetch_failed"), traced.get("grid_false_missing") or 0
        unchecked = traced.get("grid_unchecked") or 0
        if failed is None:
            return ("the trace record does not say whether normal-grid fetches failed during the trace (traced by "
                    "a kit that did not record them, or its log did not read)")
        parts = []
        if failed or false404:
            sample = traced.get("grid_fetch_failed_sample") or []
            parts.append(f"the trace went without the normals of {failed + false404} grid files: {failed} failed to "
                         "fetch" + (f" ({', '.join(sample[:3])})" if sample else "") + f" and {false404} answered "
                         "a false 404; it grew near those slices without their data term")
        if unchecked:
            parts.append(f"{unchecked} grid files answered 404 during the trace and could not be checked against the "
                         "bucket; any of them the bucket holds was a false 404, and the trace went without its "
                         "normals")
        return "; ".join(parts) or None

    def s_qa(self):
        out = {}
        for sid, s in self.surfaces():
            if "qa" in s and not s["qa"].get("exception"):
                out[sid] = s["accepted"]
                continue
            try:
                rec = self.qa_one(sid, s)
            except Exception as exc:  # noqa: BLE001 - recorded on the trace, never lost with the stage (22 Oct 2026)
                # the checks could not run: no verdict of the rule, so not ours (trace_entries). The exception's type
                # and message stay on the trace's record, and a rerun of the stage checks the trace again
                rec = {"accepted": False, "reasons": [f"check failed: {exc}"[:600]],
                       "failure": {"kind": "infrastructure"}, "exception": qareasons.exception_record(exc)}
                rec["checks"] = qareasons.checks(rec, self.s["qa"])
            if (not rec["accepted"] and not self.published(sid) and self.s["qa"].get("repair")
                    and switch_reasons(rec)):
                rec = self.repair_one(sid, s, rec)
            pieces = {}
            if not rec["accepted"] and not self.published(sid) and self.s["qa"].get("crop") and crop_reasons(rec):
                rec, pieces = self.crop_one(sid, s, rec)
            if rec["accepted"] and not self.published(sid) and self.s["qa"].get("extend") and not pieces:
                rec = self.extend_one(sid, s, rec)
            if self.published(sid) and self.s["qa"].get("published", "gate") == "record":
                # A published segment's makers accepted it and its labels sit on its grid: a benchmark measures
                # what comes after it, so the checks are recorded, including whether the trace rule would pass it
                rec["rule_verdict"] = "accepted" if rec["accepted"] else "rejected"
                rec["accepted"] = True
                rec["gated"] = False
            if not rec["accepted"]:
                rec.setdefault("failure", {"kind": "ours"})         # the acceptance rule decided
            else:
                rec.pop("failure", None)
            s["qa"], s["accepted"] = rec, rec["accepted"]
            for pid, p in pieces.items():
                self.state["surfaces"][pid] = p
                out[pid] = p["accepted"]
            self.save()
            out[sid] = rec["accepted"]
        # one log line per trace, and the failures counted by kind and by check (kit/qareasons.py)
        failures = {}
        for sid in out:
            q = self.state["surfaces"][sid]["qa"]
            failures[sid] = None if q.get("accepted") else qareasons.qa_failure(q, self.s["qa"])
            self.log(qareasons.log_line(sid, failures[sid]))
        summary = qareasons.counts(failures.values())
        if not any(out.values()):
            infra = any((self.state["surfaces"][sid]["qa"].get("failure") or {}).get("kind") == "infrastructure"
                        for sid in out)
            err = AutoError(f"no surface passed the acceptance rule: " + "; ".join(
                f"{sid}: {', '.join(self.state['surfaces'][sid]['qa']['reasons'])}" for sid in out),
                kind="infrastructure" if infra else "ours")
            err.detail = {"failure_counts": summary, "failures": failures}
            raise err
        warned = {sid: self.state["surfaces"][sid]["qa"]["warnings"] for sid in out
                  if self.state["surfaces"][sid]["qa"].get("warnings")}
        return {"accepted": [k for k, v in out.items() if v], "rejected": [k for k, v in out.items() if not v],
                **({"warnings": warned} if warned else {}),
                **({"failure_counts": summary, "failures": {k: v for k, v in failures.items() if v}}
                   if summary["rejected"] else {})}

    def s_flatten(self):
        f = self.s["flatten"]
        rec = {}
        for sid, s in self.surfaces(accepted=True):
            if "flatten" in s:
                rec[sid] = s["flatten"]["used"]
                continue
            if self.published(sid) or not f["enabled"]:
                entry = {"used": "original", "why": "labels sit on the published grid" if self.published(sid)
                         else "flatten disabled in the plan"}
                s["render_surface"] = s["surface"]
            else:
                try:    # a malformed scale or an oversized grid is recorded; render_distortion re-measures it below
                    entry = {"before": grid_distortion(s["surface"])}
                except Exception as exc:    # noqa: BLE001
                    entry = {"before_error": f"{type(exc).__name__}: {exc}"}
                try:
                    res = self.call("flatten", {"surface": s["surface"],
                                                "out": str(self.out / "flat" / f"{sid}.tifxyz"),
                                                "iterations": f["iterations"], "downsample": f["downsample"]})
                except Exception as exc:    # noqa: BLE001; a failed flattening keeps the original
                    res = {"exit": str(exc) if isinstance(exc, self.agent.ToolError)
                           else f"{type(exc).__name__}: {exc}"}
                entry["exit"] = res.get("exit")
                if res.get("exit") == 0 and res.get("surface"):
                    try:
                        d = grid_distortion(res["out"])
                        ok, why = distortion_passes(d, f)
                    except Exception as exc:    # noqa: BLE001; an unmeasurable flattening is refused
                        d, ok, why = None, False, [f"after: {type(exc).__name__}: {exc}"]
                        entry["after_error"] = why[0]
                    entry.update({"after": d, "passes": ok, "reasons": why})
                    entry["used"] = "flattened" if ok else "original"
                    s["render_surface"] = res["out"] if ok else s["surface"]
                else:
                    entry.update({"used": "original", "log_tail": res.get("log_tail")})
                    s["render_surface"] = s["surface"]
            if entry["used"] == "original":
                entry["render_distortion"] = self.render_distortion(s["surface"], entry.get("before"))
            s["flatten"] = entry
            self.save()
            rec[sid] = entry["used"]
        return rec

    def render_distortion(self, surface, measured=None):
        """The flatten limits applied to a surface that goes to render unflattened (flatten disabled, failed or
        refused, or a published segment); `measured` is its grid_distortion when the flatten stage has it. Only a
        kept flattening was checked before, so a stretched grid (a tifxyz whose declared scale is not its vertex
        spacing, a trace whose step drifts) reached the render unmeasured and rendered at the wrong scale
        (compressed where its vertices are farther apart than the declared step). Recorded, with
        a warning when it fails or cannot be measured; it refuses the render only under strict.render_distortion
        (Run.s_render)."""
        try:
            d = measured or grid_distortion(surface)
        except Exception as exc:  # noqa: BLE001 - recorded; under a plan without strict it is evidence, not a gate
            # AutoError (no numpy, no scale, too large), a bad grid, and also what a malformed meta.json raises
            # (IndexError for a one-element scale, KeyError for a dict) or MemoryError for a huge grid: none of them
            # may fail the flatten stage for a surface that before went to render unmeasured
            err = f"{type(exc).__name__}: {exc}"
            return {"passes": None, "error": err, "error_type": type(exc).__name__,
                    "warning": f"the unflattened surface that goes to render could not be measured: {err}"}
        ok, why = distortion_passes(d, self.s["flatten"])
        out = {"passes": ok, "reasons": why}
        if measured is None:
            out["distortion"] = d           # otherwise it is the flatten record's "before"
        if not ok:
            out["warning"] = "the unflattened surface that goes to render fails the flatten limits: " + "; ".join(why)
        return out

    def audit_chunks(self, surface, out):
        """The chunk audit of the scan under a surface (tool `audit`), as the render stage records it: the share of
        level-0 chunks under the surface that the scan does not hold."""
        a = self.call("audit", {"volume": self.r["volume_url"], "surface": str(surface), "out": str(out)})
        lv = ((a.get("footprint") or {}).get("levels") or [{}])[0]
        on, gone = lv.get("chunks_on_surface"), lv.get("missing_on_surface")
        frac = round(gone / on, 4) if on and gone is not None else None
        return {"verdict": a.get("verdict"), "chunks_on_surface": on, "missing_on_surface": gone,
                "missing_fraction": frac}

    def trim_for_render(self, sid, surface, t, limit):
        """render.trim: a copy of the surface with every vertex over CT value 0 (outside the scan or its mask) and
        t["dilate"] grid cells around each made invalid, read at CT level t["level"] (the coarsest the scan has when
        it has fewer), and cropped (tool `trim`). The copy is used only when it keeps at least t["min_area_share"]
        of the surface's area and its own chunk audit is at most render.max_missing; the record says what was
        trimmed and why it was used or not. The original is never changed."""
        levels = len((self.state["stages"].get("acquire", {}).get("record") or {}).get("volume_levels") or []) or None
        level = t["level"] if levels is None else min(t["level"], levels - 1)
        dest = self.out / "trims" / sid / Path(surface).name
        res = self.call("trim", {"surface": str(surface), "ct": self.r["volume_url"], "level": level,
                                 "dilate": t["dilate"], "crop": True, "out": str(dest)})
        before = self.agent.tifxyz_stats(surface)["area_voxels2"]
        after = self.agent.tifxyz_stats(res["out"])["area_voxels2"] if res.get("kept_vertices") else 0.0
        share = after / before if before else 0.0      # compared unrounded: a share just under the limit is under it
        rec = {"surface": res["out"], "level": t["level"], "level_read": level, "dilate": t["dilate"],
               "valid_vertices": res.get("valid_vertices"), "trimmed_vertices": res.get("trimmed_vertices"),
               "kept_vertices": res.get("kept_vertices"), "area_voxels2_before": before,
               "area_voxels2_after": after, "area_share": round(share, 4), "min_area_share": t["min_area_share"],
               "crop": res.get("crop"), "ct_missing_chunks_read": res.get("missing_chunks")}
        if share < t["min_area_share"]:
            rec.update(used=False, why=f"the trimmed copy keeps {share:.1%} of the area, under render.trim."
                                       f"min_area_share {t['min_area_share'] * 100:g}%")
            return rec
        a = rec["audit"] = self.audit_chunks(res["out"], self.out / "audits" / f"{sid}-trimmed")
        frac = a["missing_fraction"]
        missing = f"{a['missing_on_surface']} of {a['chunks_on_surface']} chunks under it missing (" + \
            ("share unknown" if frac is None else f"{frac:.1%}") + ")"
        if frac is None or frac > limit:
            rec.update(used=False, why=f"the trimmed copy still has {missing}, over render.max_missing {limit:.0%}")
            return rec
        ring = f", or within {t['dilate']} grid cells of one" if t["dilate"] else ""
        rec.update(used=True, why=f"{rec['trimmed_vertices']} of {rec['valid_vertices']} vertices dropped (over CT "
                                  f"value 0{ring}); the copy keeps {share:.1%} of the area and has {missing}")
        return rec

    def kit_json(self, *args):
        """`python -m kit ARGS` from this repository, in the run's environment: (exit, parsed stdout or None, the
        end of stderr)."""
        import subprocess
        root = kithome.SOURCE
        p = subprocess.run([sys.executable, "-m", "kit", *map(str, args)], capture_output=True, text=True,
                           cwd=str(root), env=dict(self.ctx.env, PYTHONPATH=str(root)))
        try:
            res = json.loads(p.stdout) if p.stdout.strip() else None
        except json.JSONDecodeError:
            res = None
        return p.returncode, res, p.stderr[-800:]

    def snap_one(self, sid, surface, cfg):
        """render.snap: kit snap --check under the plan's rule, then the snap (or its sham) into snaps/<sid>/, and
        the check that the snapped grid keeps the input's shape and valid vertices, so labels drawn on a published
        segment's grid still sit on the render. Returns the record, with "surface" when the copy is to be rendered
        and "refused" when it is not."""
        if cfg["source"] == "pred":
            volume = self.r["prediction_url"]
            base = [surface, "--volume", volume, "--level", cfg["level"], "--max-off", cfg["max_off"],
                    "--threshold", cfg["threshold"], "--jump", cfg["jump"], "--sigma", cfg["sigma"]]
        else:
            volume = self.r["volume_url"]
            mode = cfg.get("mode", "midline")
            base = [surface, "--volume", volume, "--level", cfg["level"], "--source", "ct", "--mode", mode,
                    "--umbilicus", self.out / "umbilicus.json"]
            if mode == "face":
                base += ["--face-target", cfg.get("target", "recto")]
                if cfg.get("per_vertex"):
                    base.append("--face-per-vertex")
        dest = self.out / "snaps" / sid
        rec = {"source": cfg["source"], "volume": volume, "sham": cfg["sham"], "check": None}
        if cfg["source"] == "ct":
            rec["mode"] = cfg.get("mode", "midline")
            if rec["mode"] == "face":
                rec["target"] = cfg.get("target", "recto")
                rec["per_vertex"] = bool(cfg.get("per_vertex"))
        if cfg["check"] != "off":
            code, res, err = self.kit_json("snap", *base, "--check", "--check-reference", cfg["check_reference"],
                                           "--out", dest / "check", "--json")
            c = ((res or {}).get("checks") or [None])[0]
            if code not in (0, 1) or c is None:
                rec["check"] = {"passed": None, "error": f"kit snap --check exit {code}: {err.strip()}"}
            else:
                rec["check"] = {"passed": bool(c["passed"]), "reference": c["reference"], "why": c["why"],
                                "recovery": {k: c["recovery"].get(k) for k in ("median", "p90", "frac_within_tol",
                                                                               "tol", "min_frac", "passed")},
                                "planted_median": c["planted"].get("median"),
                                "control_shifted": {k: c["control_shifted"].get(k)
                                                    for k in ("median", "frac_within_tol", "caught")},
                                "control_empty": dict(c["control_empty"])}
            if cfg["check"] == "required" and rec["check"]["passed"] is not True:
                why = "; ".join(rec["check"].get("why") or [rec["check"].get("error") or "no result"])
                rec["refused"] = f"kit snap --check did not pass ({why}), and render.snap.check is required"
                return rec
        code, res, err = self.kit_json("snap", *base, "--out", dest, "--json", *(["--sham"] if cfg["sham"] else []))
        mesh = dest / Path(surface).name
        if code != 0 or not (mesh / "x.tif").is_file():
            rec["refused"] = f"kit snap exit {code}: {err.strip()}"
            return rec
        rec["report"] = ((res or {}).get("meshes") or [{}])[0]
        rec["grid"] = g = grid_kept(surface, mesh)
        if not g["kept"]:
            rec["refused"] = f"the snapped grid is not the input's: {g['why']}"
            return rec
        rec["surface"] = str(mesh)
        return rec

    def snapped_render_shape(self, sid, zarr):
        """A benchmark segment's snapped render must have the published surface volume's layers, rows and columns,
        so its labels still sit on it; another surface's, the shape its own grid gives (rows and columns at the
        render's scale 1)."""
        from . import vc3d_region
        got = list(vc3d_region.Volume(str(zarr)).shape(0))
        bench = self.r["benchmark"] or {}
        layers = (getattr(self.agent, "PRESETS", {}).get(self.s["render"]["preset"]) or {}).get("layers")
        if sid == "seg" and bench.get("surface_shape"):
            want = [layers, *bench["surface_shape"]]
        else:
            want = [layers, *self.agent.tifxyz_stats(self.state["surfaces"][sid]["render_surface"])
                    ["render_px_at_scale_1"]]
        kept = all(w is None or w == g for w, g in zip(want, got)) and len(got) == 3
        return {"want": want, "got": got, "kept": kept}

    def s_render(self):
        rd = self.s["render"]
        rec = {}
        for sid, s in self.surfaces(accepted=True):
            done = s.get("render") or {}
            if done.get("zarr") or done.get("refused") or (done.get("failure") or {}).get("kind") == "ours":
                # a render our chain refused or that exited non-zero is final; one the infrastructure stopped
                # (the tool could not run) is tried again when the stage runs again
                rec[sid] = done.get("zarr") or (f"refused: {done['refused']}" if done.get("refused") else
                                                f"failed: {done['failure']['reason']}")
                continue
            entry = {}
            surface = s["render_surface"]
            dist = (s.get("flatten") or {}).get("render_distortion") or {}
            if dist and dist["passes"] is not True and (self.s.get("strict") or {}).get("render_distortion") \
                    and not self.published(sid):    # a published segment's labels sit on its grid: never refused
                why = ("fails the flatten limits (" + "; ".join(dist["reasons"]) + ")" if dist["passes"] is False
                       else f"could not be measured ({dist.get('error')})")
                entry["refused"] = f"the unflattened surface {why}, and strict.render_distortion refuses it"
                s["render"] = entry
                self.save()
                rec[sid] = f"refused: {entry['refused']}"
                continue
            try:
                surface = self.render_one(sid, s, entry, surface, rd)
            except self.agent.ToolError as exc:
                entry["failure"] = {"kind": "infrastructure", "reason": f"the render tools could not run: {exc}"[:600]}
                surface = None
            if surface is None:
                s["render"] = entry
                self.save()
                rec[sid] = f"refused: {entry['refused']}" if entry.get("refused") else \
                    f"failed: {entry['failure']['reason']}"
                continue
            s["render"] = entry
            self.save()
            rec[sid] = entry["zarr"]
        if not any(s.get("render", {}).get("zarr") for _, s in self.surfaces(accepted=True)):
            infra = any(((s.get("render") or {}).get("failure") or {}).get("kind") == "infrastructure"
                        for _, s in self.surfaces(accepted=True))
            raise AutoError(f"no render finished: {rec}", kind="infrastructure" if infra else "ours")
        if self.transfer:
            # labels are carried here, on the CPU machine and before any map exists, so the pixels each trace is
            # scored on are fixed by geometry alone
            rec["label_transfer"] = {sid: {k: v.get("labelled_cm2", v.get("error")) for k, v in
                                           self.carry_labels(sid, s).items()}
                                     for sid, s in self.surfaces(accepted=True)
                                     if not self.published(sid) and (s.get("render") or {}).get("zarr")}
        return rec

    def render_one(self, sid, s, entry, surface, rd):
        """The chunk audit, trim and render of one accepted surface, into `entry`. Returns the tifxyz rendered, or
        None when the surface was refused (entry["refused"]) or the renderer did not finish (entry["failure"]:
        a non-zero exit is ours, a renderer that could not start or was canceled is the infrastructure's). A
        ToolError (an input or tool the render tools could not reach) is left to the caller."""
        if rd.get("snap") is not None:          # opt in: absent from plans that do not ask for it
            entry["snap"] = sn = self.snap_one(sid, surface, rd["snap"])
            if sn.get("refused"):
                entry["refused"] = sn["refused"]
                return None
            surface = sn["surface"]
        if rd["audit"]:
            entry["audit"] = a = self.audit_chunks(surface, self.out / "audits" / sid)
            on, gone, frac = a["chunks_on_surface"], a["missing_on_surface"], a["missing_fraction"]
            if a["verdict"] not in ("clean",):
                entry["warning"] = f"chunk audit says {a['verdict']}: a hole renders as zeros with no error"
            limit = rd.get("max_missing")      # plans made before this rule existed have none
            if limit is not None and frac is not None and frac > limit:
                refused = (f"{gone} of {on} chunks under the surface are missing from the scan ({frac:.1%}, "
                           f"over render.max_missing {limit:.0%}): it runs where the masked scan has no "
                           "data, so its render would be partly zeros")
                trim = rd.get("trim")          # opt in: absent from plans that do not ask for it
                if trim is not None and self.published(sid):
                    entry["trim"] = {"used": False, "why": "a published segment is never trimmed: its labels "
                                                           "sit on its grid"}
                elif trim is not None:
                    entry["trim"] = t = self.trim_for_render(sid, surface, trim, limit)
                    if t["used"]:
                        surface = t["surface"]
                        refused = None
                if refused:
                    entry["refused"] = refused + (f"; not trimmed: {entry['trim']['why']}" if "trim" in entry
                                                  else "")
                    return None
        res = self.call("render", {"surface": surface, "volume": self.r["volume_url"],
                                   "preset": rd["preset"], "umbilicus": str(self.out / "umbilicus.json"),
                                   "voxel_um": self.r["voxel_um"], "format": rd["format"],
                                   "out": str(self.out / "renders" / sid)})
        entry.update({"exit": res.get("exit"), "order": res.get("order"), "orientation": res.get("orientation")})
        if surface != s["render_surface"]:
            entry["surface"] = surface          # the snapped or trimmed copy
        zarr = res.get("zarr") or res.get("out")
        rc = res.get("exit")
        if rc != 0 or not zarr:
            ours = rc == 0 or rc == "timeout" or (isinstance(rc, int) and not isinstance(rc, bool))
            entry["failure"] = {"kind": "ours" if ours else "infrastructure",
                                "reason": f"the renderer exited {rc}" + ("" if zarr else " and wrote no render")}
            return None
        if "snap" in entry:
            entry["snap"]["render_shape"] = shape = self.snapped_render_shape(sid, zarr)
            if not shape["kept"]:
                entry["refused"] = f"the render of the snapped surface is {shape['got']}, not {shape['want']}"
                return None
        entry["zarr"] = zarr
        bench = (self.r["benchmark"] or {}) if sid == "seg" else \
            ((self.r.get("transfer") or {}).get(s.get("reference")) or {})
        if self.published(sid) and bench.get("surface_volume") and "snap" in entry:
            entry["published_check"] = {"passes": None, "skipped": "the surface was snapped: the published "
                                                                   "render is of the unmoved mesh"}
        elif self.published(sid) and bench.get("surface_volume"):
            try:
                entry["published_check"] = render_check(
                    zarr, f"{vc3d_catalog.BUCKET_URL}/{bench['surface_volume']}", bench["crop"])
            except Exception as exc:  # noqa: BLE001 - recorded; the check is evidence, not a gate
                entry["published_check"] = {"passes": None, "error": f"{type(exc).__name__}: {exc}"}
        return surface

    def carry_labels(self, sid, s):
        """score.transfer: every listed segment's labels carried onto this trace's render canvas (kit labelxfer),
        from the tifxyz that was rendered (the flattened or trimmed copy when one was). Kept in s["transfer"];
        a segment already carried is not carried again, and a failure is recorded, not raised. First the canvas
        check (labelxfer.canvas_check, s["canvas_check"]): the render must fill only pixels the carrying takes as
        rendered, or the canvas formula is not the renderer's and every carry is recorded as an error (the readout
        then gives VOID). Then each report surface's overlap with the trace, from its mesh alone
        (s["report_overlap"], labelxfer.overlap)."""
        from . import labelxfer
        from .verify import VerifyError
        tr = self.transfer
        render = s.get("render") or {}
        surface = render.get("surface") or s.get("render_surface") or s["surface"]
        errors = (VerifyError, AutoError, OSError, ValueError, MemoryError)
        if "canvas_check" not in s:
            try:
                s["canvas_check"] = labelxfer.canvas_check(surface, render["zarr"])
            except errors as exc:
                s["canvas_check"] = {"passes": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
            self.save()
        cc = s["canvas_check"]
        done = s.setdefault("transfer", {})
        for key in tr["segments"]:
            if key in done and ("labelled_cm2" in done[key] or "error" in done[key]):
                continue
            dest = self.out / "transfer" / sid / key
            if not cc.get("passes"):
                done[key] = {"error": "canvas check failed: " + (cc.get("error") or
                                                                 f"agreement {cc.get('agreement')} under "
                                                                 f"{cc.get('min_agreement')}"),
                             "surface": str(surface)}
                self.save()
                continue
            try:
                res = labelxfer.carry(surface, self.published_mesh(key), self.labels_dir(key), dest,
                                      tr["max_gap_vox"], tr["max_normal_deg"], voxel_um=self.r["voxel_um"],
                                      lattice_px=tr["lattice_px"],
                                      surface_shape=self.r["transfer"][key]["surface_shape"], log=self.log)
                done[key] = {"out": str(dest), "surface": str(surface), **labelxfer.coverage(res["record"])}
            except errors as exc:
                done[key] = {"error": f"{type(exc).__name__}: {exc}", "surface": str(surface)}
            self.save()
        acquired = ((self.state["stages"].get("acquire") or {}).get("record") or {}).get("transfer") or {}
        over = s.setdefault("report_overlap", {})
        for key in self.r.get("report_overlap") or {}:
            if key in over:
                continue
            mesh = (acquired.get(key) or {}).get("mesh")
            if not mesh:
                over[key] = {"error": "its mesh was not fetched: " + str((acquired.get(key) or {}).get("error")),
                             "labels": "never fetched"}
            else:
                try:
                    over[key] = labelxfer.overlap(surface, mesh, self.out / "transfer" / sid / f"report-{key}",
                                                  tr["max_gap_vox"], tr["max_normal_deg"], voxel_um=self.r["voxel_um"],
                                                  lattice_px=tr["lattice_px"], log=self.log)
                except errors as exc:
                    over[key] = {"error": f"{type(exc).__name__}: {exc}"[:500], "labels": "never fetched"}
            self.save()
        return done

    def ink_where(self):
        """local when every planned model is registered and its engine's Python requirements are present.
        Command engines own their dependencies; learned engines need torch. Otherwise modal; skip as planned."""
        w = self.s["ink"]["where"]
        if w == "modal" and self.on_runner:
            return "local"
        if w in ("local", "modal", "skip"):
            return w
        models = self.agent.load_models(self.ctx)
        aliases = model_aliases()
        models = {**{m: vc3d_catalog.builtin_model(m) for m in self.s["ink"]["models"]
                     if vc3d_catalog.builtin_model(m) is not None}, **models}    # shipped in kit; a registration wins
        found = [vc3d_catalog.find_model(m, models, aliases) for m in self.s["ink"]["models"]]   # by any of its names
        registered = all(k is not None for k in found)
        commands_only = registered and all(isinstance(models[k], dict) and models[k].get("engine") == "command"
                                           for k in found)
        if registered and (commands_only or self.agent.ink_env(self.ctx).get("torch")):
            return "local"
        if self.on_runner:
            raise AutoError(f"the runner has no registered {self.s['ink']['models']} or no torch in its ink Python "
                            f"({self.agent.ink_env(self.ctx).get('python')})")
        return "modal"

    def s_ink(self):
        where = self.ink_where()
        if where == "skip":
            return {"skipped": "ink.where is skip in the plan"}
        if where == "modal":
            job = {"plan": str(self.out / "plan.json"), "run": str(self.out), "stage": "ink",
                   "models": self.s["ink"]["models"],
                   "renders": {sid: s["render"]["zarr"] for sid, s in self.surfaces(accepted=True)
                               if s.get("render", {}).get("zarr")}}
            (self.out / "modal-job.json").write_text(json.dumps(job, indent=1))
            return {"handoff": "modal", "job": str(self.out / "modal-job.json"),
                    "why": "no registered model with torch here; run the same folder again once KIT_INK_PYTHON "
                           "names a Python with torch and the models are registered, or the Modal runner "
                           "(a script of the source repository) runs ink on a GPU, launched by a person or an agent "
                           "that can reach Modal (AGENTS.md rule 10)"}
        check_model_pins(self.plan)      # each name still means the weights it meant when the plan was made
        rec = {}
        layers, ens = self.s["ink"].get("layers"), self.s["ink"].get("ensemble")
        orient = self.s["ink"].get("orient")
        for sid, s in self.surfaces(accepted=True):
            zarr = s.get("render", {}).get("zarr")
            if not zarr:
                continue
            maps = s.setdefault("ink", {})
            turn = None
            if orient is not None:      # opt in: absent from plans that do not ask for it
                turn = self.orient_one(sid, s, zarr, orient)
                # a failed turn leaves the surface uninked, unless the plan asks for fallback "unturned": then it is
                # inked as rendered (a failed record is not used), the failure kept in s["orient"] and on each map
                if turn.get("failed") and orient.get("fallback") != "unturned":
                    for model in self.s["ink"]["models"]:
                        if maps.get(model, {}).get("exit") != 0:
                            maps[model] = {"exit": f"not inked: the canvas turn failed ({turn['failed']})"}
                    self.save()
                    rec[sid] = {m: v.get("exit") for m, v in maps.items()}
                    continue
                if not turn.get("used"):
                    turn = None
            for model in self.s["ink"]["models"]:
                if maps.get(model, {}).get("exit") == 0:
                    continue
                if turn is not None:
                    maps[model] = self.ink_turned(sid, turn, model, layers)
                elif layers is None:
                    maps[model] = self.ink_one(zarr, model, self.out / "ink" / sid / model)
                else:
                    maps[model] = self.ink_windows(sid, zarr, model, layers)
                if (s.get("orient") or {}).get("failed") and turn is None:
                    maps[model]["warnings"] = [*(maps[model].get("warnings") or []),
                                               f"inked as rendered: the canvas turn failed ({s['orient']['failed']})"]
                self.save()
            if ens is not None and maps.get("ensemble", {}).get("exit") != 0:
                maps["ensemble"] = self.combine_maps(
                    [maps.get(m) for m in self.s["ink"]["models"]], ens["method"],
                    self.ink_dest(maps.get(self.s["ink"]["models"][0]), sid, "ensemble"),
                    {"models": list(self.s["ink"]["models"])}, ens)
                # the fallback's warning goes with the combination of maps that carry it
                fell = sorted({w for m in self.s["ink"]["models"] for w in (maps.get(m) or {}).get("warnings") or ()
                               if w.startswith("inked as rendered: the canvas turn failed")})
                if fell:
                    maps["ensemble"]["warnings"] = [*(maps["ensemble"].get("warnings") or []), *fell]
                self.save()
            rec[sid] = {m: v.get("exit") for m, v in maps.items()}
        return rec

    @staticmethod
    def map_paths(s, model, out=None):
        """{variant: path} from one model, including ink/ files copied back from a runner.

        Existing paths win. Only an unambiguous ink/ tail may move under out; a missing
        arbitrary input is never replaced by another file with the same basename.
        """
        m = (s.get("ink") or {}).get(model) or {}
        paths = {k: v.get("path") for k, v in (m.get("maps") or {}).items() if isinstance(v, dict)}
        for key, path in paths.items():
            if not out or not path or Path(path).exists():
                continue
            parts = Path(path).parts
            if parts.count("ink") != 1 or ".." in parts:
                continue
            moved = Path(out).joinpath(*parts[parts.index("ink"):])
            if moved.is_file():
                paths[key] = str(moved)
        return paths

    def score_transfer(self):
        """score.transfer: each accepted trace's maps on the labels carried onto it, per segment, with the
        reverse, shuffled and displaced controls; each reference segment's own maps on its own labels (as a
        benchmark run scores them) and, sampled at the carried pixels' sources, compared with the trace's forward
        map. Every planned trace is recorded, in launch order (traces.planned): one with no trace, rejected, not
        rendered, without carried labels or under min_area_cm2 as not scorable, with the reason and, in failure,
        the step and who decided it (FAILURE_KINDS); with each trace its canvas check and its overlap with any
        report surface (geometry only)."""
        from . import labelxfer
        from .verify import VerifyError
        tr = self.transfer
        models = self.s["ink"]["models"]
        boot = tr["bootstrap"]
        acquired = ((self.state["stages"].get("acquire") or {}).get("record") or {}).get("transfer") or {}
        rec = {"rule": {k: tr[k] for k in ("segments", "max_gap_vox", "max_normal_deg", "min_area_cm2",
                                           "displace_mm", "lattice_px")},
               "bootstrap": boot, "plan": self.plan["digest"],
               "checks": {key: (acquired.get(key) or {}).get("check") for key in tr["segments"]},
               "references": {}, "surfaces": {},
               "note": "scores on carried labels: published labels moved by geometry onto this run's own surfaces; "
                       "model output, not a reading"}
        refmaps = {}
        for key, how in (tr.get("references") or {}).items():
            if how == "run":
                sid = f"ref-{key}"
                s = self.state["surfaces"].get(sid) or {}
                r = {"surface": sid, "render": (s.get("render") or {}).get("zarr"), "models": {}}
                for model in models:
                    paths = self.map_paths(s, model, self.out)
                    if not (paths.get("f") and paths.get("r")):
                        r["models"][model] = {"error": "forward or reverse map missing"}
                        continue
                    r["models"][model] = score_maps(self.ctx, paths["f"], paths["r"], self.labels_dir(key),
                                                    self.r["transfer"][key], self.s["score"]["inner"],
                                                    self.out / "scores" / sid)
                    if paths.get("s"):
                        r["models"][model]["shuffled_whole"] = _auc(self.ctx, paths["s"], paths["r"],
                                                                    self.labels_dir(key), [])
                    refmaps.setdefault(key, {})[model] = paths["f"]
            else:
                r = {"given": how}
                refmaps[key] = dict(how)
            rec["references"][key] = r
        # every planned trace, in launch order, with where it stands (trace_entries); one that stopped before a
        # render is not scorable, with the step that stopped it and who decided it (FAILURE_KINDS)
        entries = trace_entries(self.state)
        rec["traces"] = {"planned": [e["sid"] for e in entries], "repeats": self.s["trace"].get("repeats", 1),
                         "seeds": {e["sid"]: e["seed_index"] for e in entries}}
        for e in entries:
            sid = e["sid"]
            s = self.state["surfaces"].get(sid) or {}
            entry = rec["surfaces"][sid] = {"origin": s.get("origin"), "seed_index": e["seed_index"],
                                            "repeat": e["repeat"], "accepted": e["accepted"]}
            if s.get("report_overlap"):
                entry["report_overlap"] = s["report_overlap"]
            if s.get("canvas_check"):
                entry["canvas_check"] = s["canvas_check"]
            if e["failure"]:
                f = e["failure"]
                entry.update(scorable=False, why=f["reason"] if f["stage"] != "trace" else f"no trace: {f['reason']}",
                             failure=f)
                continue
            carried = self.carry_labels(sid, s)
            if s.get("report_overlap"):
                entry["report_overlap"] = s["report_overlap"]
            entry["canvas_check"] = s.get("canvas_check")
            entry["segments"] = {}
            for key in tr["segments"]:
                c = carried.get(key) or {}
                g = entry["segments"][key] = {"coverage": c}
                if c.get("error"):
                    g.update(scorable=False, why=f"labels not carried: {c['error']}",
                             failure={"stage": "transfer", "kind": "infrastructure",
                                      "reason": f"labels not carried: {c['error']}"})
                    continue
                if (c.get("labelled_cm2") or 0.0) < tr["min_area_cm2"] or not c.get("ink_px") \
                        or not c.get("background_px"):
                    why = (f"{c.get('labelled_cm2')} cm2 of carried labels ({c.get('ink_px')} ink and "
                           f"{c.get('background_px')} background px), under score.transfer.min_area_cm2 "
                           f"{tr['min_area_cm2']} or one class missing")
                    g.update(scorable=False, why=why, failure={"stage": "transfer", "kind": "ours", "reason": why})
                    continue
                g["scorable"] = True
                g["models"] = {}
                for model in models:
                    paths = self.map_paths(s, model, self.out)
                    if not (paths.get("f") and paths.get("r")):
                        g["models"][model] = {"error": "forward or reverse map missing"}
                        continue
                    try:
                        g["models"][model] = labelxfer.score(c["out"], paths, refmaps.get(key, {}).get(model),
                                                             tr["displace_mm"], boot["draws"], boot["block_px"],
                                                             boot["seed"])
                    except (VerifyError, OSError, ValueError) as exc:
                        g["models"][model] = {"error": f"{type(exc).__name__}: {exc}"}
        (self.out / "scores.json").write_text(json.dumps(rec, indent=1))

    def ink_one(self, zarr, model, out, window=None):
        """One call of the ink tool: the plan's variants of one model on one render, in one layer window."""
        args = {"input": zarr, "purpose": self.s["purpose"], "model": model,
                "variants": self.s["ink"]["variants"], "device": self.ctx.env.get("KIT_AUTOPIPE_DEVICE", "cpu")}
        if window is not None:
            args["layers"] = list(window)
        if self.target:
            args["experiment"] = self.s["experiment"]
        else:
            args["out"] = str(out)
        try:
            res = self.call("ink", args)
        except self.agent.ToolError as exc:
            res = {"exit": str(exc)}
        return {k: res.get(k) for k in ("exit", "out", "maps", "comparison", "warnings", "device")}

    def ink_dest(self, first, sid, name):
        """Where a combined map goes: beside the run's ink maps, or for a target run beside the experiment's."""
        if self.target and first and first.get("out"):
            return Path(first["out"]).parent / f"{Path(first['out']).name}-{sid}-{name}"
        return self.out / "ink" / sid / name

    def ink_windows(self, sid, zarr, model, layers, root=None):
        """ink.layers: one model on each window; with more than one, each variant's maps combined (kit ensemble).
        root: the folder the maps go under (default the run's ink folder; ink.orient's turned maps go elsewhere)."""
        root = self.out / "ink" if root is None else root
        per = {}
        for w in layers["windows"]:
            tag = f"w{w[0]:02d}-{w[1]:02d}"
            per[tag] = self.ink_one(zarr, model, root / sid / model / tag, w)
            self.save()
        if len(per) == 1:
            (tag, one), = per.items()
            return dict(one, windows={tag: {k: one.get(k) for k in ("exit", "out")}})
        first = next(iter(per.values()))
        out = self.ink_dest(first, sid, f"{model}-windows") if self.target else root / sid / model
        return self.combine_maps(list(per.values()), layers["combine"], out, {"windows": per})

    def orient_one(self, sid, s, zarr, orient):
        """ink.orient: the in-plane turn that puts this surface's render canvas into the published layout,
        measured from the tifxyz that was rendered (kit canvasorient.measure, the run's umbilicus deciding the
        mirror), and the render turned by it (canvasorient.apply) into orient/<sid>. Kept in s["orient"]: the
        angle, mirror, measurement and transform, or why nothing was turned (a published segment, or a canvas the
        estimator does not find applicable: the surface is then inked as rendered), or failed (the surface is not
        inked). Measured once per render."""
        done = s.get("orient") or {}
        if done.get("source") == zarr and (done.get("failed") or not done.get("used")
                                           or Path(done.get("transform") or "").is_file()):
            return done
        rec = {"source": zarr, "method": orient["method"], "used": False}
        if self.published(sid):
            rec["why"] = ("a published segment: already in the published layout, and its labels sit on its own "
                          "canvas")
        else:
            from . import canvasorient
            render = s.get("render") or {}
            surface = render.get("surface") or s.get("render_surface") or s["surface"]
            umb = self.out / "umbilicus.json"
            try:
                m = canvasorient.measure(surface, umbilicus=str(umb) if umb.is_file() else None,
                                         min_consistency=orient["min_consistency"],
                                         min_vertical=orient["min_vertical"])
                rec["measured"] = {k: m.get(k) for k in (
                    "surface", "phi_deg", "plane_phi_deg", "consistency", "vertical", "spread_deg", "vertices",
                    "mirror", "angle_deg", "applicable", "why", "normal", "grid", "scale", "canvas")}
                if not m["applicable"]:
                    rec["why"] = "not turned: " + "; ".join(m["why"])
                else:
                    t = canvasorient.apply(zarr, m["angle_deg"], self.out / "orient" / sid, m["mirror"],
                                           orient["order"], measured=rec["measured"])
                    rec.update(used=True, angle_deg=t["angle_deg"], mirror=t["mirror"], order=t["order"],
                               zarr=t["zarr"], transform=str(self.out / "orient" / sid / "transform.json"),
                               source_shape=t["source_shape"], turned_shape=t["turned_shape"],
                               sampler=t["sampler"], source_sha256=t["source_sha256"],
                               turned_sha256=t["turned_sha256"])
                    if list(m["canvas"]) != list(t["source_shape"]):
                        rec["note"] = (f"the render's canvas {t['source_shape']} is not the {m['canvas']} the grid "
                                       "gives at scale 1 (a scaled or cropped render): the angle is the same")
            except (canvasorient.OrientError, OSError, ValueError, KeyError) as exc:
                rec["failed"] = f"{type(exc).__name__}: {exc}"[:600]
        s["orient"] = rec
        self.save()
        return rec

    def ink_turned(self, sid, turn, model, layers):
        """ink.orient: one model on the turned render (every planned variant, so the reverse and shuffled controls
        are made on the turned canvas too) into ink-turned/<sid>/<model>, then each map taken back to the render's
        canvas with the inverse turn (canvasorient.back), into the run's ink folder (a target run's beside its
        turned maps). The record is the ink tool's, with the maps taken back; the turned maps are kept under
        turned."""
        from . import canvasorient
        root = self.out / "ink-turned"
        if layers is None:
            res = self.ink_one(turn["zarr"], model, root / sid / model)
        else:
            res = self.ink_windows(sid, turn["zarr"], model, layers, root)
        rec = {k: res.get(k) for k in ("exit", "out", "maps", "comparison", "warnings")}
        rec["turned"] = {k: v for k, v in res.items() if k not in ("warnings",)}
        rec["orient"] = {k: turn.get(k) for k in ("angle_deg", "mirror", "order", "transform")}
        if res.get("exit") != 0:
            return rec
        if self.target:
            dest = Path(res["out"]).parent / f"{Path(res['out']).name}-back"
        else:
            dest = self.out / "ink" / sid / model
        back = {}
        try:
            for v in self.s["ink"]["variants"]:
                src = ((res.get("maps") or {}).get(v) or {}).get("path")
                if not src:
                    rec["exit"] = f"not taken back: the turned map of variant {v} is missing"
                    return rec
                b = canvasorient.back(src, turn["transform"], dest / f"ink_{v}.tif")
                back[v] = {"path": b["out"], "turned": src, "valid_px": b["valid_px"], "invalid_px": b["invalid_px"]}
        except (canvasorient.OrientError, OSError, ValueError) as exc:
            rec["exit"] = f"not taken back: {type(exc).__name__}: {exc}"[:600]
            return rec
        rec.update(exit=0, out=str(dest), maps=back)
        return rec

    def combine_maps(self, parts, method, out, extra, cfg=None):
        """Each variant's maps of several ink results combined into one map (kit ensemble; method zscore: kit
        inkensemble with the plan's ink.ensemble options cfg, each variant on its own maps, so the reverse ensemble
        is the forward one's control, and a provenance record beside each map); exit 0 only when every part
        finished and every combination was written."""
        rec = dict(extra, method=method, exit=None, maps={})
        bad = [i for i, p in enumerate(parts) if not p or p.get("exit") != 0]
        if bad:
            rec["exit"] = f"not combined: {len(bad)} of {len(parts)} inputs did not finish"
            return rec
        Path(out).mkdir(parents=True, exist_ok=True)
        for v in self.s["ink"]["variants"]:
            paths = [((p.get("maps") or {}).get(v) or {}).get("path") for p in parts]
            if not all(paths):
                rec["exit"] = f"not combined: a map of variant {v} is missing"
                return rec
            dest = Path(out) / f"ink_{v}.tif"
            if method == "zscore":
                from . import inkensemble
                names = extra["models"]
                code, res, err = self.kit_json("inkensemble", dest, *[f"{n}={p}" for n, p in zip(names, paths)],
                                               *inkensemble.plan_flags(cfg or {}, names), "--run", f"ap-ink-ensemble-{v}",
                                               "--json")
                tool = "kit inkensemble"
            else:
                code, res, err = self.kit_json("ensemble", dest, *paths, "--method", method, "--json")
                tool = "kit ensemble"
            if code != 0:
                rec["exit"] = f"{tool} exit {code}: {err.strip()}"
                return rec
            rec["maps"][v] = {"path": str(dest), "inputs": paths, "valid_px": (res or {}).get("valid_px")}
            if method == "zscore":
                rec["maps"][v]["provenance"] = (res or {}).get("provenance")
        rec.update(exit=0, out=str(out))
        return rec

    def s_score(self):
        bench = self.r["benchmark"]
        if self.transfer and not self.target:
            return self.score_transfer()
        if not bench:
            return {"skipped": "no labels: only published labeled segments are scored"}
        if self.target:
            return {"skipped": "target runs are never scored here"}
        from . import fetch
        lab = self.out / "labels"
        for z in ("inklabels", "supervision"):
            if not (lab / f"{z}.zarr").exists():
                fetch.fetch_prefix(f"{bench['labels']}/{z}.zarr", lab / f"{z}.zarr", workers=8)
        s = self.state["surfaces"].get("seg") or {}
        rec = {}
        for model, m in (s.get("ink") or {}).items():
            paths = {k: v.get("path") for k, v in (m.get("maps") or {}).items()}
            fwd, rev = paths.get("f"), paths.get("r")
            if not (fwd and rev):
                rec[model] = {"error": "forward or reverse map missing"}
                continue
            rec[model] = score_maps(self.ctx, fwd, rev, lab, bench, self.s["score"]["inner"], self.out / "scores")
            if paths.get("s"):      # the depth-shuffled map, scored the same way (its auc_as_stored is the shuffle's)
                rec[model]["shuffled_whole"] = _auc(self.ctx, paths["s"], rev, lab, [])
        (self.out / "scores.json").write_text(json.dumps(rec, indent=1))
        return rec

    def orient_summary(self, s):
        """ink.orient's outcome for one surface, as the report gives it: turned (with the angle and mirror), not
        turned and why, or failed and then inked as rendered (the plan's fallback) or left uninked."""
        o = s["orient"]
        out = {k: o[k] for k in ("used", "angle_deg", "mirror", "why", "failed") if o.get(k) is not None}
        if o.get("failed"):
            fb = (self.s["ink"].get("orient") or {}).get("fallback")
            out["then"] = "inked as rendered" if fb == "unturned" else "not inked"
        return out

    @staticmethod
    def warnings(s):
        """A surface's warnings: what qa and the render-distortion check found but, under the plan, did not stop."""
        dist = (s.get("flatten") or {}).get("render_distortion") or {}
        return [*((s.get("qa") or {}).get("warnings") or []), *([dist["warning"]] if dist.get("warning") else [])]

    # -- triage (opt in): a reading order for the maps, never a verdict
    def triage_private(self):
        """True when this run's triage list is private (AGENTS.md rule 1): a target run's, and any run's on a scroll
        without published labels (not in TRIAGE_PUBLIC), whatever its purpose."""
        return self.target or self.r["sample"] not in TRIAGE_PUBLIC

    def triage_withheld(self, name="triage.json"):
        """Why this run's triage (or another private list, `name`: crackle.json) may not be written, or None. A
        private list (triage_private) is written only in a run folder git ignores (work/, experiments/, or outside
        the repository), and a target run's only under experiments/<experiment>/ (where run_folder puts target
        runs); in any other folder (one copied into a tracked folder, say) the run keeps none."""
        if not self.triage_private():
            return None
        out = self.out.resolve()
        if self.target:
            base = (self.ctx.root / "experiments" / self.s["experiment"]).resolve()
            if out != base and base not in out.parents:
                return f"the run folder {out} is not under {base}"
        try:
            ignored = self.agent.ignored(self.ctx, out / name)
        except Exception:  # noqa: BLE001 - any doubt keeps the list unwritten
            ignored = False
        return None if ignored else f"git does not ignore the run folder {out}"

    @staticmethod
    def _file_sig(path):
        """[path, size, mtime_ns] of a map, so a report run again reuses the scores of maps that did not change."""
        if not path:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return [str(path), None, None]
        return [str(path), st.st_size, st.st_mtime_ns]

    @staticmethod
    def triage_map(path):
        """(map, non-finite pixel count): .npy as the v8in and TorchScript engines of scripts/vc3d/ink.py write it,
        else TIFF or PNG (kit verify's reader), as kit auc reads maps. Non-finite pixels become 0, rowscore's off the
        surface: ink.py exits 0 only when every such pixel lies off the surface, and a model whose ink did not exit 0
        is never read here (triage_one). One NaN would otherwise make the whole map's score NaN."""
        from .verify import _numpy, load_map
        np = _numpy()
        a = np.load(path) if str(path).endswith(".npy") else load_map(path)
        if a.dtype.kind != "f":
            return a, 0
        bad = ~np.isfinite(a)
        n = int(bad.sum())
        return (np.where(bad, 0, a).astype(a.dtype) if n else a), n

    @staticmethod
    def _finite(rec):
        """A rowscore record with every non-finite number replaced by None (JSON has no NaN); a score that is not a
        finite number becomes no score, with the reason."""
        out = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in rec.items()}
        if rec.get("score") is not None and out["score"] is None:
            out["reason"] = "the row score is not a finite number (a map flat inside the surface, say)"
        return out

    @staticmethod
    def _triage_errors(e):
        """True when a surface's triage record holds an error from reading or scoring a map (a missing file, too
        little memory, a missing library): such a record is scored again, never reused."""
        recs = [r for per in (e.get("models") or {}).values() for r in per.values()]
        return any("error" in r for r in [*recs, *(e.get("mean") or {}).values()])

    @staticmethod
    def _triage_problem(per):
        """What keeps one model out of the mean: its variants' shared reason, or the first map's."""
        bad = [(v, r.get("skipped") or r.get("error")) for v, r in per.items() if "skipped" in r or "error" in r]
        if len(bad) == len(per) and len({why for _, why in bad}) == 1:
            return bad[0][1]
        return f"{bad[0][0]} map: {bad[0][1]}"

    def triage_one(self, s, models, voxel_um, old):
        """One surface: each model's forward, reverse and shuffled maps scored by kit rowscore, and the mean of the
        models' maps of each variant (rowscore.mean_map) over the models whose three maps all read. A model whose
        ink did not exit 0 (exit 3: the ink stage found its maps unreadable) is not read. Reused from `old` (the last
        triage.json's record) when no map and no ink exit changed and nothing failed there."""
        from . import rowscore
        from .verify import VerifyError
        paths = {m: self.map_paths(s, m, self.out) for m in models}
        exits = {m: ((s.get("ink") or {}).get(m) or {}).get("exit") for m in models}
        inputs = {v: {m: self._file_sig(paths[m].get(v)) for m in models} for v in TRIAGE_VARIANTS}
        rec = {"origin": s.get("origin"), "inputs": inputs, "ink_exit": exits, "models": {}, "mean_of": [],
               "mean": {}}
        if not any(sig for per in inputs.values() for sig in per.values()):
            ink = (self.state["stages"].get("ink") or {}).get("status")
            rec.update(score=None, why=f"no ink maps (the ink stage is {ink})",
                       controls={v: None for v in TRIAGE_VARIANTS[1:]})
            return rec
        if (old.get("inputs") == inputs and old.get("ink_exit") == exits and old.get("mean")
                and not self._triage_errors(old)):
            return old

        def score(load):
            try:
                a, nonfinite = load()
                r = self._finite(rowscore.score_array(a, voxel_um))
            except (VerifyError, OSError, ValueError, MemoryError) as exc:
                return {"score": None, "error": f"{type(exc).__name__}: {exc}"[:400]}
            if nonfinite:
                r["nonfinite_px"] = nonfinite
            return r

        def mean(v):
            arrays = [self.triage_map(paths[m][v]) for m in ok]
            return rowscore.mean_map([a for a, _ in arrays]), sum(n for _, n in arrays)

        for m in models:
            if exits[m] != 0:
                why = ("ink exit 3: the ink stage found this model's maps unreadable (its ink.json says why)"
                       if exits[m] == 3 else "the ink stage has not run this model" if exits[m] is None
                       else f"ink exit {exits[m]}: the ink stage did not finish this model")
                rec["models"][m] = {v: {"score": None, "skipped": why} for v in TRIAGE_VARIANTS}
                continue
            rec["models"][m] = {v: score(lambda p=paths[m].get(v): self.triage_map(p)) if paths[m].get(v)
                                else {"score": None, "skipped": f"no {v} map"} for v in TRIAGE_VARIANTS}
        ok = [m for m in models if not any({"error", "skipped"} & set(rec["models"][m][v]) for v in TRIAGE_VARIANTS)]
        rec["mean_of"] = ok
        for v in TRIAGE_VARIANTS:
            if not ok:
                left = "; ".join(f"{m}: {self._triage_problem(rec['models'][m])}" for m in models)
                rec["mean"][v] = {"score": None, "skipped": "no model has forward, reverse and shuffled maps that "
                                                            f"read ({left})"[:600]}
            elif len(ok) == 1:      # the mean of one map is that map
                rec["mean"][v] = dict(rec["models"][ok[0]][v])
            else:
                rec["mean"][v] = score(lambda v=v: mean(v))
        f = rec["mean"]["f"]
        rec["score"] = f.get("score")
        if rec["score"] is None:
            rec["why"] = f.get("reason") or f.get("skipped") or f.get("error")
        rec["controls"] = {v: rec["mean"][v].get("score") for v in TRIAGE_VARIANTS[1:]}
        return rec

    @staticmethod
    def triage_ranking(surfaces):
        """Rows in reading order: scored surfaces by the forward score of the models' mean map, highest first; then
        the unscored, each with its reason (rowscore's own, such as a surface too small to score)."""
        def finite(v):
            return v if isinstance(v, (int, float)) and math.isfinite(v) else None

        rows = []
        for sid, e in surfaces.items():
            f = (e.get("mean") or {}).get("f") or {}
            ctl = {v: finite(c) for v, c in (e.get("controls") or {}).items()}
            sc = finite(e.get("score"))
            row = {"surface": sid, "origin": e.get("origin"), "score": sc, "controls": ctl, "beats_controls": None,
                   "models": {m: finite((v.get("f") or {}).get("score")) for m, v in (e.get("models") or {}).items()},
                   **({"partial": e["partial"]} if e.get("partial") else {})}
            if sc is None:
                row["why"] = e.get("why") or "the row score is not a finite number"
            else:
                row.update(period_mm=f.get("period_mm"), angle_deg=f.get("angle_deg"))
                if all(ctl.get(v) is not None for v in TRIAGE_VARIANTS[1:]):
                    row["beats_controls"] = all(sc > ctl[v] for v in TRIAGE_VARIANTS[1:])
                else:
                    row["why_no_control"] = "a control map has no row score"
            rows.append(row)
        scored = sorted((r for r in rows if r["score"] is not None), key=lambda r: (-r["score"], r["surface"]))
        rest = sorted((r for r in rows if r["score"] is None), key=lambda r: r["surface"])
        for k, r in enumerate(scored, 1):
            r["rank"] = k
        for r in rest:
            r["rank"] = None
        return scored + rest

    def triage(self):
        """The plan's triage (Run.triage_one on every accepted surface, then triage_ranking), written to triage.json
        in the run folder; returns report.json's record of it. The maps' pixels are taken as the plan's scan voxels
        (voxel_um), as the render gives them."""
        why = self.triage_withheld()
        if why:
            return {"withheld": f"{TRIAGE_PRIVATE}; not written: {why}", "note": TRIAGE_NOTE}
        path = self.out / "triage.json"
        try:
            old = json.loads(path.read_text()) if path.is_file() else {}
        except ValueError:
            old = {}
        if old.get("plan") != self.plan["digest"] or old.get("version") != TRIAGE_VERSION:
            old = {}
        models = list(self.s["ink"]["models"])
        voxel_um = self.r["voxel_um"]
        surfaces = {sid: self.triage_one(s, models, voxel_um, (old.get("surfaces") or {}).get(sid) or {})
                    for sid, s in self.surfaces(accepted=True)}
        for sid, s in self.surfaces(accepted=True):
            kind = (((s.get("trace") or {}).get("stop")) or {}).get("partial")
            if kind:
                # a partial surface (trace.budget) ranks like any other, and its row says it stopped short
                surfaces[sid]["partial"] = kind
        ranking = self.triage_ranking(surfaces)
        rec = {"version": TRIAGE_VERSION, "method": self.s["triage"]["method"], "source": TRIAGE_SOURCE,
               "plan": self.plan["digest"], "sample": self.r["sample"], "purpose": self.s["purpose"],
               "voxel_um": voxel_um, "models": models,
               "rule": "rank by the row score of the mean of the models' forward maps; beats_controls: that score "
                       "is above both the reverse and the shuffled mean map's",
               "ranking": ranking, "surfaces": surfaces, "note": TRIAGE_NOTE}
        if any(r.get("largest_piece") is False for e in surfaces.values() for r in (e.get("mean") or {}).values()):
            rec["warning"] = "scipy not found, so rowscore skipped its largest-piece step; thin strips can fake a period"
        if self.triage_private():
            rec["private"] = TRIAGE_PRIVATE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=1, allow_nan=False))    # every number was made finite above
        tmp.replace(path)
        out = {"method": rec["method"], "file": str(path), "ranking": ranking, "note": TRIAGE_NOTE}
        for k in ("warning", "private"):
            if k in rec:
                out[k] = rec[k]
        return out

    # -- Crackle Check (opt in): the control-set gate of the released Space on each surface's maps
    def render_middle(self, s):
        """The middle layer of a surface's render (layers x H x W), the CT the gate takes its papyrus from; a path
        that does not exist as given is read under the run folder."""
        from .vc3d_region import Volume
        loc = (s.get("render") or {}).get("zarr")
        if not loc:
            raise OSError("the surface has no render")
        if not str(loc).lower().startswith(("http://", "https://", "s3://")) and not Path(loc).exists() and \
                (self.out / loc).exists():
            loc = self.out / loc
        v = Volume(str(loc))
        shape = v.shape(0)
        if len(shape) != 3:
            raise ValueError(f"the render {loc} is {shape}, not layers x rows x columns")
        z = shape[0] // 2
        return v.read(0, [[z, z + 1], [0, shape[1]], [0, shape[2]]])[0]

    def crackle_one(self, sid, s, models, tile, old):
        """One surface: Crackle Check's gate (kit/crackle.py) on the mean of the models' forward maps against the
        mean of their reverse maps, over the papyrus of the render's middle layer, whole and in tiles; each model's
        own whole-surface gate beside it. A model whose ink did not exit 0 is not read. The kept-ink overlay goes to
        crackle/<sid>.tif. Reused from `old` (the last crackle.json's record) when no map, render or ink exit
        changed and nothing failed there."""
        from . import crackle
        from .verify import VerifyError
        np = crackle._np()
        paths = {m: self.map_paths(s, m, self.out) for m in models}
        exits = {m: ((s.get("ink") or {}).get(m) or {}).get("exit") for m in models}
        render = (s.get("render") or {}).get("zarr")
        inputs = {"maps": {v: {m: self._file_sig(paths[m].get(v)) for m in models} for v in ("f", "r")},
                  "render": render}
        rec = {"origin": s.get("origin"), "inputs": inputs, "ink_exit": exits, "models": {}, "mean_of": []}
        if old.get("inputs") == inputs and old.get("ink_exit") == exits and "error" not in old \
                and old.get("answer") is not None:
            return old
        errors = (VerifyError, crackle.CrackleError, OSError, ValueError, MemoryError)
        for m in models:
            if exits[m] != 0:
                rec["models"][m] = {"skipped": "the ink stage did not finish this model" if exits[m] is None
                                    else f"ink exit {exits[m]}"}
            elif not (paths[m].get("f") and paths[m].get("r")):
                rec["models"][m] = {"skipped": "no forward or no reverse map"}
        ok = [m for m in models if m not in rec["models"]]
        if not ok:
            left = "; ".join(f"{m}: {v['skipped']}" for m, v in rec["models"].items())
            rec.update(answer=None, why=f"no model has forward and reverse maps ({left})"[:600])
            return rec
        try:
            ct = np.asarray(self.render_middle(s))
            mask = crackle.papyrus(ct)
            F = R = None
            for m in ok:
                f, _ = self.triage_map(paths[m]["f"])
                r, _ = self.triage_map(paths[m]["r"])
                f, r = np.asarray(f, np.float32), np.asarray(r, np.float32)
                if f.ndim != 2 or f.shape != ct.shape or r.shape != ct.shape:
                    raise ValueError(f"model {m}'s maps are {f.shape} and {r.shape}, the render's layer {ct.shape}")
                rec["models"][m] = {k: v for k, v in crackle.decide_mask(f, r, mask).items()
                                    if k in ("status", "answer", "excess", "threshold")}
                F = f if F is None else F + f
                R = r if R is None else R + r
            rec["mean_of"] = ok
            F, R = F / len(ok), R / len(ok)
            got, kept = crackle.surface(F, R, ct, tile)
        except errors as exc:
            rec.update(answer=None, error=f"{type(exc).__name__}: {exc}"[:400])
            return rec
        rec.update(got)
        rec["answer"] = got["whole"]["answer"]
        if kept.any():
            import tifffile
            dest = self.out / "crackle" / f"{sid}.tif"
            dest.parent.mkdir(parents=True, exist_ok=True)
            tifffile.imwrite(str(dest), kept)
            rec["kept"] = str(dest)
        return rec

    @staticmethod
    def crackle_rows(surfaces):
        """One row per surface, in reading order: judged surfaces by their whole-surface excess, highest first, then
        the rest with their reason."""
        rows = []
        for sid, e in surfaces.items():
            w = e.get("whole") or {}
            rows.append({"surface": sid, "origin": e.get("origin"), "answer": e.get("answer"),
                         "excess": w.get("excess"), "tiles": e.get("tiles"), "yes_share": e.get("yes_share"),
                         "models": {m: v.get("excess") for m, v in (e.get("models") or {}).items()},
                         **({"kept": e["kept"]} if e.get("kept") else {}),
                         **({"why": e.get("why") or e.get("error")} if e.get("answer") is None else {}),
                         **({"partial": e["partial"]} if e.get("partial") else {})})
        judged = sorted((r for r in rows if r["excess"] is not None), key=lambda r: (-r["excess"], r["surface"]))
        return judged + sorted((r for r in rows if r["excess"] is None), key=lambda r: r["surface"])

    def crackle(self):
        """The plan's Crackle Check (Run.crackle_one on every accepted surface), written to crackle.json in the run
        folder; returns report.json's record of it. Private where a triage list is (triage_private)."""
        from . import crackle
        why = self.triage_withheld("crackle.json")
        if why:
            return {"withheld": f"{TRIAGE_PRIVATE}; not written: {why}", "note": CRACKLE_NOTE}
        path = self.out / "crackle.json"
        try:
            old = json.loads(path.read_text()) if path.is_file() else {}
        except ValueError:
            old = {}
        c = self.s["crackle"]
        if old.get("plan") != self.plan["digest"] or old.get("version") != CRACKLE_VERSION:
            old = {}
        models = list(self.s["ink"]["models"])
        surfaces = {sid: self.crackle_one(sid, s, models, c["tile_px"], (old.get("surfaces") or {}).get(sid) or {})
                    for sid, s in self.surfaces(accepted=True)}
        for sid, s in self.surfaces(accepted=True):
            kind = (((s.get("trace") or {}).get("stop")) or {}).get("partial")
            if kind:
                surfaces[sid]["partial"] = kind
        rows = self.crackle_rows(surfaces)
        rec = {"version": CRACKLE_VERSION, "rule": c["rule"], "tile_px": c["tile_px"], "space": crackle.SPACE,
               "prereg": crackle.PREREG, "plan": self.plan["digest"], "sample": self.r["sample"],
               "purpose": self.s["purpose"], "models": models, "rows": rows, "surfaces": surfaces,
               "note": CRACKLE_NOTE}
        if self.triage_private():
            rec["private"] = TRIAGE_PRIVATE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=1))
        tmp.replace(path)
        out = {"rule": rec["rule"], "file": str(path), "rows": rows, "note": CRACKLE_NOTE}
        if "private" in rec:
            out["private"] = rec["private"]
        return out

    def stackcheck(self):
        """The plan's stack check (kit/apstackcheck.py) on the accepted traces, written to stackcheck.json in the run
        folder with stackcheck's own report and flags under stackcheck/; returns report.json's record of it."""
        paths = {sid: s.get("surface") for sid, s in self.surfaces(accepted=True)}
        rec = apstackcheck.run(paths, self.out / "umbilicus.json", self.r["voxel_um"], self.out / "stackcheck",
                               settings=self.s["stackcheck"], public_root=os.environ.get("SCROLLS_PUBLIC_ROOT"))
        rec["plan"] = self.plan["digest"]
        apstackcheck.write(self.out / "stackcheck.json", rec)
        return {"file": str(self.out / "stackcheck.json"),
                **{k: rec[k] for k in ("status", "why", "surface_checks_flagged", "stack_checks_flagged",
                                       "not_checked", "surfaces", "note") if k in rec}}

    def trace_extent(self, s):
        """For a report's surface entry under trace.budget: whether the trace is partial (its kind), and how many
        generations it placed of the plan's. {} for a plan without trace.budget, so its report is as before."""
        if not self.s["trace"].get("budget"):
            return {}
        stop = (s.get("trace") or {}).get("stop") or {}
        if not stop:
            return {}
        return {"partial": stop.get("partial"), "generations_done": stop.get("generations_done"),
                "generations_planned": stop.get("generations_planned") or self.s["trace"]["generations"]}

    def trace_counts(self):
        """For report.json under trace.budget: planned traces counted as whole, partial, deferred and failed, and
        the trace stage's warning (a normal-grid cache that thrashes). {} for a plan without trace.budget."""
        if not self.s["trace"].get("budget"):
            return {}
        n = {"whole": 0, "partial": 0, "deferred": 0, "failed": 0}
        for e in trace_entries(self.state):
            s = self.state["surfaces"].get(e["sid"])
            if s is not None:
                n["partial" if e.get("partial") else "whole"] += 1
            elif e.get("deferred"):
                n["deferred"] += 1
            else:
                n["failed"] += 1
        out = {"trace_counts": n}
        warn = (self.state.get("trace_runtime") or {}).get("warning")
        if warn:
            out["trace_warning"] = warn
        return out

    def s_report(self):
        rep = {"plan": self.plan["digest"], "sample": self.r["sample"], "volume": self.r["volume"],
               "purpose": self.s["purpose"], "stages": {k: v.get("status") for k, v in self.state["stages"].items()},
               "surfaces": {sid: {"origin": s.get("origin"), "accepted": s.get("accepted"),
                                  **self.trace_extent(s),
                                  "reasons": (s.get("qa") or {}).get("reasons"),
                                  "warnings": self.warnings(s),
                                  "rule_verdict": (s.get("qa") or {}).get("rule_verdict"),
                                  "flatten": (s.get("flatten") or {}).get("used"),
                                  "render": (s.get("render") or {}).get("zarr"),
                                  "published_check": (s.get("render") or {}).get("published_check"),
                                  "bench": {k: (s.get("bench") or {}).get(k) for k in ("verdict", "valid")}
                                  if s.get("bench") else None,
                                  "ink": {m: v.get("exit") for m, v in (s.get("ink") or {}).items()},
                                  **({"orient": self.orient_summary(s)} if s.get("orient") else {}),
                                  **({"trim": {k: s["render"]["trim"].get(k) for k in ("used", "area_share", "why")}}
                                     if (s.get("render") or {}).get("trim") else {}),
                                  **({"transfer": {k: v.get("labelled_cm2", v.get("error"))
                                                   for k, v in s["transfer"].items()}}
                                     if s.get("transfer") else {}),
                                  **({"canvas_check": s["canvas_check"].get("passes")} if s.get("canvas_check")
                                     else {}),
                                  **({"report_overlap": {k: v.get("overlap_cm2", v.get("error"))
                                                         for k, v in s["report_overlap"].items()}}
                                     if s.get("report_overlap") else {})}
                            for sid, s in self.state["surfaces"].items()},
               **({"trace_failures": self.state["trace_failures"]} if self.state.get("trace_failures") else {}),
               # partial surfaces (trace.budget): traces that stopped short of their generations and kept their
               # last complete surface, by kind (tracebudget.PARTIAL_KINDS), apart from failures and whole traces
               **({"partial_traces": self.state["partial_traces"]} if self.state.get("partial_traces") else {}),
               **self.trace_counts(),
               "note": "Every surface, map and score here is model output, not a reading."}
        if self.s.get("triage") is not None:
            # a step of report, not a stage of its own: plans without it keep their stages, state and report
            rep["triage"] = self.triage()
        if self.s.get("crackle") is not None:
            rep["crackle"] = self.crackle()
        if self.s.get("stackcheck") is not None:
            rep["stackcheck"] = self.stackcheck()
        (self.out / "report.json").write_text(json.dumps(rep, indent=1))
        rep["digest"] = hashlib.sha256((self.out / "report.json").read_bytes()).hexdigest()
        if "ranking" in rep.get("triage", {}) and self.triage_private():
            # a private list (a target's, or any on a scroll without published labels) stays in its run folder: the
            # stage record (state.json, and what the autopipeline tool and command line return) names the file only
            t = rep["triage"]
            rep["triage"] = {"file": t["file"], "surfaces": len(t["ranking"]),
                             "scored": sum(r["score"] is not None for r in t["ranking"]), "private": TRIAGE_PRIVATE,
                             "note": TRIAGE_NOTE}
        if "rows" in rep.get("crackle", {}) and self.triage_private():
            # the same for Crackle Check's answers: the stage record names the file and counts, never the answers
            c = rep["crackle"]
            rep["crackle"] = {"file": c["file"], "surfaces": len(c["rows"]),
                              "judged": sum(r["excess"] is not None for r in c["rows"]), "private": TRIAGE_PRIVATE,
                              "note": CRACKLE_NOTE}
        return rep

    def run(self, until=None, only=None):
        """Run the stages in order from the first one not finished, up to and including `until`. A failed stage
        stops the run (its error is in state.json); ink handed off to Modal leaves score for the runner there.
        While a stage runs, state.json holds it under "running" (with the process and host), outside "stages", so
        done() and the report read what they read before; progress lines and stage events go to events.jsonl, of
        bounded size (kit/autopipe_monitor.py reads both)."""
        from . import autopipe_monitor
        self.events = autopipe_monitor.EventLog(self.out)
        said, self.ctx.progress = self.ctx.progress, self.events.tee(self.ctx.progress)
        try:
            state = self._stages(until, only)
        finally:
            self.ctx.progress, self.events = said, None
        self.write_graph()
        self.learn_record()
        return state

    def learn_record(self):
        """This run's record in the learning ledger (kit/aplearn.py): its settings, each stage's status, seconds and
        backend, and each planned trace's fate; the stages this process ran are named this machine's, whatever
        marker the folder holds. Never a map, score or triage list, and nothing of a target run. A record that
        cannot be written is logged, never a failed run."""
        try:
            from . import aplearn
            res = aplearn.record_run(self.ctx, self.out, plan=self.plan, state=self.state,
                                     ran=sorted(getattr(self, "ran_here", ())))
        except ImportError:
            return
        except Exception as exc:    # noqa: BLE001 (the ledger is a record of the run, not part of it)
            self.log(f"learning ledger not written: {type(exc).__name__}: {exc}")
            return
        if res.get("ledger") and res.get("excluded"):
            self.log(f"learning ledger: recorded as excluded, never learned from ({res['excluded']})")
        elif res.get("ledger"):
            self.log(f"learning ledger: {res['traces']} traces recorded in {res['ledger']}")
        elif res.get("skipped"):
            self.log(f"learning ledger: nothing written ({res['skipped']})")

    def write_graph(self):
        """graph.json, the run's provenance graph (kit/apgraph.py): which stage, backend, inputs and settings made
        each output. A graph that cannot be written is logged, never a failed run."""
        from . import apgraph
        try:
            apgraph.write(self.out)
        except Exception as exc:    # noqa: BLE001 (the graph is a record of the run, not part of it)
            self.log(f"graph.json not written: {type(exc).__name__}: {exc}")

    def _stages(self, until, only):
        order = list(STAGES)
        if until:
            if until not in STAGES:
                raise AutoError(f"until is one of {', '.join(STAGES)}")
            order = order[:order.index(until) + 1]
        for stage in order:
            if only and stage not in only:
                continue
            if self.done(stage) and stage != "report":
                continue
            if stage == "score" and self.state["stages"].get("ink", {}).get("status") == "handoff":
                continue
            t = time.time()
            try:
                self.state["running"] = self.events.running(stage, t)
                self.save()
                self.log(f"stage {stage}")
                rec = getattr(self, f"s_{stage}")()
            except (AutoError, self.agent.ToolError, OSError) as exc:
                # who decided it (FAILURE_KINDS): ours only where the stage says so
                kind = getattr(exc, "kind", None) or "infrastructure"
                detail = getattr(exc, "detail", None)     # s_qa: each trace's failed checks and their counts
                self.mark(stage, "failed", error=str(exc), kind=kind, seconds=round(time.time() - t, 1),
                          **({"detail": detail} if detail else {}))
                self.ran_here.add(stage)
                return self.state
            except BaseException as exc:
                # a bug or Ctrl-C: the mark says the stage ended and how, still outside "stages" (a resume reruns it)
                self.state["running"] = self.events.ended(self.state.get("running"), stage, exc, time.time() - t)
                try:
                    self.save()
                except OSError:
                    pass
                raise
            status = "handoff" if isinstance(rec, dict) and rec.get("handoff") else \
                "skipped" if isinstance(rec, dict) and set(rec) == {"skipped"} else "done"
            self.mark(stage, status, rec, seconds=round(time.time() - t, 1))
            self.ran_here.add(stage)
            if status == "handoff":
                self.log(f"stage {stage}: handed off ({rec.get('why')})")
        return self.state

    # -- the trace of one seed (TRACE_METHODS)
    def trace_call(self, sid, args):
        """One seed's trace: the trace tool, or the plan's trace method (register_trace_method)."""
        method = trace_method(self.s)
        if method is None:
            return self.call("trace", args)
        return method.trace(self, sid, args)


# ---------------------------------------------------------------- agent tools

def estimate_umbilicus(agent, ctx, row, grids_url, out, every=500, repeats=3, seed=1, window=5, max_jump_um=None,
                       z_range=None, threads=None, estimator=None, sample=None, polish=None):
    """The scroll axis of one scan with no person marking it: per-slice estimates from one backend (estimator,
    kit/apbackends.py; default villa's vc_gen_umbilicus on every `every`-th slice of the published normal grids,
    repeats estimates per slice, their median), then robust_axis drops estimates far from their neighbors: more
    than max_jump_um, or by default more than 4 robust deviations. estimator may be a list, tried in order: the
    first that makes an axis is used and the result lists why the ones before it did not. polish (umbilicus.polish,
    kit/axispolish.py) then moves the axis to the highest winding coverage nearby on the published grids, or records
    why it could not. Returns the result dict; writes out/umbilicus.json (villa's control_points)."""
    from . import apbackends
    chain = apbackends.estimator_chain(estimator)
    tried = []
    for name in chain:
        try:
            pts, prov, extra = AXIS_ESTIMATORS[name](agent, ctx, row, grids_url, Path(out), every=every,
                                                     repeats=repeats, seed=seed, z_range=z_range, threads=threads,
                                                     sample=sample)
            kept, dropped = robust_axis(pts, window=window,
                                        max_jump=None if max_jump_um is None else max_jump_um / row["voxel_um"])
            if len(kept) < 2:
                raise agent.ToolError(f"only {len(kept)} axis estimates survived the outlier rule")
        except (agent.ToolError, AutoError, vc3d_orient.OrientError) as exc:
            if len(chain) == 1:
                raise agent.ToolError(str(exc)) from exc
            tried.append({"estimator": name, "error": str(exc)})
            continue
        prov = {**prov, "estimator": name, "window": window, "max_jump_um": max_jump_um, "dropped": dropped,
                **({"fell_back": tried} if tried else {})}
        pol = None
        if polish:
            kept, pol = polish_axis(row, grids_url, Path(out), kept, polish, z_range=z_range, estimator=name)
            prov["polish"] = pol
        extra = dict(extra)
        raw_meta = extra.pop("_axis_metadata", None)
        path = Path(out) / "umbilicus.json"
        path.write_text(json.dumps(umbilicus_json(kept, prov, raw_meta), indent=1))
        return {"umbilicus": str(path), "source": "estimated", "estimator": name,
                "backend": apbackends.describe("umbilicus", name), "estimates": len(pts), "kept": len(kept),
                "dropped": len(dropped), **extra, "z_span": [kept[0][0], kept[-1][0]],
                **({"fell_back": tried} if tried else {}), **({"polish": pol} if pol else {})}
    raise agent.ToolError("no axis estimator made an axis: " + "; ".join(f"{t['estimator']}: {t['error']}"
                                                                         for t in tried))


def polish_axis(row, grids_url, out, kept, setting, z_range=None, estimator=None):
    """umbilicus.polish on an estimated axis: (points, record). The estimate is kept unchanged, the record saying
    why, when the scan has no published grids, kit's Python has no numpy, or fewer than 2 slices polish."""
    s = _polish_setting(setting)
    rec = {"version": s["version"], "every": s["every"], "rule": axispolish.RULE, "label": axispolish.LABEL,
           "evidence": ("tested on the centre finder's line (a frozen test of the source repository)"
                        if estimator == "centrenet" else
                        f"untested: the frozen test polished the centre finder's line, not {estimator}'s")}
    if not grids_url:
        return kept, {**rec, "skipped": "no published normal grids to polish on"}
    try:
        axispolish._np()
    except axispolish.PolishError as exc:
        return kept, {**rec, "skipped": str(exc)}
    zs = axispolish.heights(kept, s["every"], z_range)
    got, missing = fetch_grids(grids_url, out / "grids", zs)
    t = time.time()
    line, recs = axispolish.polish_line(kept, got, axispolish.grid_segments(out / "grids"), row["voxel_um"])
    (out / "polish.json").write_text(json.dumps({**rec, "slices": recs}, indent=1))
    done = [r for r in recs if not r.get("skipped")]
    rec.update(slices=len(zs), missing_grids=len(missing), polished=len(done), seconds=round(time.time() - t, 1))
    if line is None:
        return kept, {**rec, "skipped": f"{len(done)} of {len(zs)} slices polished (a grid with at least "
                                        f"{axispolish.RULE['min_segments']} traced segments each); 2 needed"}
    moved = sorted(r["moved_mm"] for r in done)
    gain = sorted(r["coverage"] - r["guess_coverage"] for r in done)
    rec.update(points=len(line), median_moved_mm=moved[len(moved) // 2], max_moved_mm=moved[-1],
               median_gain_wraps=round(gain[len(gain) // 2], 4))
    return line, rec


def _polish_arg(value):
    """The umbilicus tool's polish argument, checked: None (no polish) or the setting merged over its defaults."""
    if value is None or value is False:
        return None
    s = _polish_setting(value)
    try:
        axispolish.check(s)
    except axispolish.PolishError as exc:
        raise AutoError(str(exc)) from exc
    return s


def _polish_setting(setting):
    """umbilicus.polish as given (true or an object) merged over its defaults."""
    return {**axispolish.DEFAULTS, **(setting if isinstance(setting, dict) else {})}


def _axis_points(agent, path):
    """Convert malformed backend files into a recorded estimator failure, including fallback."""
    try:
        points = vc3d_orient.load_umbilicus(str(path))
        if not all(math.isfinite(v) for point in points for v in point):
            raise ValueError("axis coordinates must be finite")
        return points
    except (OSError, ValueError, TypeError, KeyError, AttributeError, vc3d_orient.OrientError) as exc:
        raise agent.ToolError(f"invalid axis output {path}: {exc}") from exc


def _axis_villa(agent, ctx, row, grids_url, out, every=500, repeats=3, seed=1, z_range=None, threads=None, **_):
    """villa's vc_gen_umbilicus on the published normal grids: (points, provenance, result extras)."""
    tools = ctx.tools()
    if not tools.has("vc_gen_umbilicus"):
        raise agent.ToolError(f"vc_gen_umbilicus is not in {tools.bindir} (villa #1823 or later)")
    if not grids_url:
        raise agent.ToolError(f"{row['volume']} has no published normal grids to estimate an axis from")
    grids = out / "grids"
    zs = grid_slices(row["shape_zyx"][0], every, z_range)
    got, missing = fetch_grids(grids_url, grids, zs)
    if len(got) < 3:
        raise agent.ToolError(f"only {len(got)} normal grids found under {grids_url}")
    raw = out / "raw.json"
    argv = ["-i", grids, "-o", raw, "--seed", seed, "--repeats", repeats, "--slices", ",".join(map(str, got)),
            "--threads", threads or min(4, agent.vc3d.cpu_limit()), "--voxelsize-um", row["voxel_um"],
            "--volume-width", row["shape_zyx"][2], "--volume-height", row["shape_zyx"][1],
            "--volume-slices", row["shape_zyx"][0]]
    if row.get("url"):
        argv += ["--volume", row["url"]]
    rc, seconds = agent.run_logged(ctx, tools.argv("vc_gen_umbilicus", *argv), out / "vc_gen_umbilicus.log",
                                   env=agent.vc3d.headless_env(ctx.env), timeout=3600)
    if rc != 0 or not raw.is_file():
        raise agent.ToolError(f"vc_gen_umbilicus failed ({rc}): {agent.tail(out / 'vc_gen_umbilicus.log', 15)}")
    pts = _axis_points(agent, raw)
    prov = {"method": "vc_gen_umbilicus on published normal grids, outliers dropped by robust_axis",
            "grids": grids_url, "every": every, "repeats": repeats, "seed": seed, "slices": len(zs),
            "missing_grids": missing}
    try:
        raw_meta = json.loads(raw.read_text()).get("metadata")
    except (ValueError, AttributeError):
        raw_meta = None
    return pts, prov, {"missing_grids": len(missing), "seconds": seconds, "_axis_metadata": raw_meta}


def _axis_normals(agent, ctx, row, grids_url, out, every=500, z_range=None, threads=None, **_):
    """kit normalaxis (numpy) on the same normal grids villa's estimator reads: (points, provenance, extras)."""
    from . import normalaxis
    try:
        normalaxis._np()
    except normalaxis.NormalAxisError as exc:
        raise agent.ToolError(f"the normals estimator needs numpy in kit's Python ({exc})") from exc
    if not grids_url:
        raise agent.ToolError(f"{row['volume']} has no published normal grids to estimate an axis from")
    grids = out / "grids"
    zs = grid_slices(row["shape_zyx"][0], every, z_range)
    got, missing = fetch_grids(grids_url, grids, zs)
    if len(got) < 3:
        raise agent.ToolError(f"only {len(got)} normal grids found under {grids_url}")
    t = time.time()
    pts, per = normalaxis.estimate_axis(grids, got, workers=threads or 4)
    seconds = round(time.time() - t, 1)
    refused = {z: r.get("reason") for z, r in per.items() if r.get("x") is None}
    (out / "raw.json").write_text(json.dumps({"control_points": [{"z": z, "y": y, "x": x} for z, y, x in pts],
                                              "per_slice": per}, indent=1))
    if len(pts) < 3:
        raise agent.ToolError(f"kit normalaxis gave an estimate on {len(pts)} of {len(got)} slices (first reasons: "
                              f"{'; '.join(sorted(set(r for r in refused.values() if r))[:2])})")
    prov = {"method": f"kit normalaxis v{normalaxis.VERSION} (numpy) on published normal grids, outliers dropped "
                      "by robust_axis", "grids": grids_url, "every": every, "slices": len(zs),
            "missing_grids": missing, "rule": normalaxis.RULE, "refused": refused}
    return pts, prov, {"missing_grids": len(missing), "seconds": seconds, "refused": len(refused)}


def bucket_path(url):
    """The open-data bucket's key of a scan URL (scripts/umbilicus reads the bucket by key), or None for any
    other location."""
    from urllib.parse import urlparse
    u = urlparse(str(url or ""))
    if u.scheme not in ("http", "https") or "vesuvius-challenge-open-data" not in u.netloc:
        return None
    return u.path.strip("/") or None


def centrenet_weights(ctx, opener=None):
    """{"first": path, "zoom": path}: the released all-scroll weights of the scroll center finder, downloaded once
    into the cache and checked against their sha256 (kit/apbackends.py CENTRENET_WEIGHTS)."""
    from . import apbackends
    folder = apbackends.weights_dir(ctx)
    out = {}
    for stage, (name, sha) in apbackends.CENTRENET_WEIGHTS.items():
        f = folder / name
        if not f.is_file() or vc3d_catalog.sha256_file(f) != sha:
            download(apbackends.CENTRENET_RELEASE + name, f, opener=opener, tries=4)
            got = vc3d_catalog.sha256_file(f)
            if got != sha:
                f.unlink()
                raise AutoError(f"{name}: sha256 {got[:12]}, the release pins {sha[:12]}")
        out[stage] = f
    return out


def _axis_centrenet(agent, ctx, row, grids_url, out, threads=None, sample=None, **_):
    """Our scroll center finder (scripts/umbilicus/predict.py, two-stage U-Nets on level-3 CT slices) in the ink
    Python: (points, provenance, extras). It reads CT, not normal grids, so it needs no grids and no villa build."""
    from . import apbackends
    um = row["voxel_um"]
    lo, hi = apbackends.CENTRENET_UM
    if not lo <= um <= hi:
        raise agent.ToolError(f"centrenet takes {lo:g} to {hi:g} um scans; {row['volume']} is {um:g} um")
    key = bucket_path(row.get("url"))
    if not key or not sample:
        raise agent.ToolError("centrenet reads its slices from the open-data bucket: it needs a catalog scan "
                              f"(this one is at {row.get('url')})")
    env = agent.ink_env(ctx)
    if not env.get("torch"):
        raise agent.ToolError(f"centrenet needs torch in the ink Python ({env.get('python')}); set KIT_INK_PYTHON")
    script = ctx.env.get("KIT_CENTRENET_PREDICT")
    if not script:
        from . import kithome
        try:
            script = str(kithome.source_file("scripts/umbilicus/predict.py", need="the centrenet estimator"))
        except kithome.MissingSource as exc:
            raise agent.ToolError(str(exc)) from exc
    w = centrenet_weights(ctx)
    data = Path(ctx.home) / "cache" / "umbilicus-slices" / row["volume"]
    pred_out = out / "centrenet"
    device = "cuda" if env.get("cuda") else "cpu"     # scripts/umbilicus/README.md: mps is untested
    argv = [env.get("python") or sys.executable, script, sample, "--first", str(w["first"]), "--zoom",
            str(w["zoom"]), "--data", str(data), "--out", str(pred_out), "--volume", key, "--device", device]
    run_env = dict(agent.vc3d.headless_env(ctx.env))
    if threads:
        run_env.update(OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads))
    rc, seconds = agent.run_logged(ctx, argv, out / "centrenet.log", env=run_env, timeout=4 * 3600)
    line = pred_out / f"{sample}_umbilicus.json"
    if rc != 0 or not line.is_file():
        raise agent.ToolError(f"centrenet failed ({rc}): {agent.tail(out / 'centrenet.log', 15)}")
    pts = _axis_points(agent, line)
    prov = {"method": "scroll center finder (scripts/umbilicus/predict.py, release umbilicus-v1 all-scroll "
                      "weights) on level-3 CT slices, outliers dropped by robust_axis", "volume": key,
            "weights": {k: {"file": v.name, "sha256": apbackends.CENTRENET_WEIGHTS[k][1]} for k, v in w.items()},
            "device": device, "held_out": "not on the 13 scrolls with published lines: the all-scroll weights "
                                          "trained on them"}
    return pts, prov, {"seconds": seconds, "device": device}


AXIS_ESTIMATORS = {"villa": _axis_villa, "normals": _axis_normals, "centrenet": _axis_centrenet}


def register(agent):
    tool, STR, INT, NUM, BOOL, ARR, OBJ = agent.tool, agent.STR, agent.INT, agent.NUM, agent.BOOL, agent.ARR, agent.OBJ
    ToolError = agent.ToolError

    def catalog_row(ctx, sample, volume):
        try:
            cat = vc3d_catalog.load(ctx.home / "cache")
            return cat, pick_volume(cat, sample, volume)
        except (vc3d_catalog.CatalogError, AutoError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("umbilicus", "Scroll axis", "The umbilicus (scroll axis) of an open-data scan with no person marking it: the "
          "catalog's when it has one (source catalog), else estimated from the scan's published normal grids with "
          "villa's vc_gen_umbilicus on every n-th slice and outliers dropped by a fixed rule (source estimate). "
          "compare scores an estimate against the catalog's axis, the check that this estimate can fail. Writes "
          "villa's control_points JSON, which render, check_surface, orientation, windaudit and the spiral fitter read.",
          {"sample": STR("sample id, e.g. PHerc0826"), "volume": STR("volume id (default: the scan nearest 9 um with a "
                                                                    "prediction)"),
           "grids": STR("estimate from these normal grids instead of the catalog's (a folder or URL holding xy/"
                        "NNNNNN.grid, as vc_gen_normalgrids writes); needs voxel_um and shape_zyx"),
           "voxel_um": NUM("voxel size of the grids' frame in um (with grids)"),
           "shape_zyx": ARR("slices, rows, columns of the grids' frame (with grids)", {"type": "integer"},
                            minItems=3, maxItems=3),
           "source": STR("auto (catalog when it has one, else estimate), catalog, estimate or compare",
                         enum=["auto", "catalog", "estimate", "compare"]),
           "every": INT("estimate: every n-th slice (default 500)", minimum=1),
           "repeats": INT("estimates per slice; their median is kept (default 3)", minimum=1),
           "seed": INT("vc_gen_umbilicus seed (default 1), so a run repeats exactly", minimum=0),
           "window": INT("neighbors each estimate is compared with (default 5)", minimum=2),
           "max_jump_um": NUM("drop an estimate farther than this from its neighbors' median (default: more "
                              "than 4 robust deviations of all such distances)"),
           "z_range": ARR("slices [z0, z1) to estimate over (default the whole scan)", {"type": "integer"},
                          minItems=2, maxItems=2),
           "polish": OBJ("estimate: coverage polish of the estimated axis on the published normal grids "
                         "(kit/axispolish.py; AutoPipeline's umbilicus.polish): {version: 1, every: slices between "
                         "polished slices, default 100}; absent, no polish. Never applied to the catalog's line"),
           "estimator": ARR("estimate: the backends to try in order (default [villa]): villa (vc_gen_umbilicus on "
                            "the normal grids), centrenet (our scroll center finder on CT slices; torch, 8 to 10 um "
                            "scans) or normals (kit normalaxis, numpy); the result says which ran",
                            {"type": "string", "enum": ["villa", "centrenet", "normals"]}, minItems=1),
           "out": STR("output folder (default work/vc3d/umbilicus/<sample>-<volume>-<time>)")},
          openworld=True)
    def h_umbilicus(ctx, a):
        src = a.get("source", "auto")
        if a.get("grids"):
            if not (a.get("voxel_um") and a.get("shape_zyx")):
                raise ToolError("grids needs voxel_um and shape_zyx")
            if src in ("catalog", "compare"):
                raise ToolError(f"source {src} reads the catalog; give sample instead of grids")
            cat, cat_url, grids = None, None, [a["grids"]]
            row = {"volume": a.get("volume") or "local", "voxel_um": a["voxel_um"], "shape_zyx": a["shape_zyx"],
                   "url": None}
        else:
            if not a.get("sample"):
                raise ToolError("umbilicus needs sample (the catalog's scans) or grids")
            cat, row = catalog_row(ctx, a["sample"], a.get("volume"))
            cat_url = vc3d_catalog.umbilicus_for(cat, row["volume"])
            grids = [g["url"] for g in row.get("normal_grids") or []]
        name = f"{a.get('sample') or 'grids'}-{row['volume']}-{agent.stamp()}"
        out = agent.out_dir(ctx, a.get("out"), "umbilicus", name)
        result = {"sample": a.get("sample"), "volume": row["volume"], "voxel_um": row["voxel_um"]}
        if src in ("auto", "catalog") and cat_url:
            try:
                download(cat_url, out / "umbilicus.json", tries=8)
            except AutoError as exc:
                raise ToolError(str(exc)) from exc
            pts = vc3d_orient.load_umbilicus(str(out / "umbilicus.json"))
            return {**result, "source": "catalog", "url": cat_url, "umbilicus": str(out / "umbilicus.json"),
                    "points": len(pts)}
        if src == "catalog":
            raise ToolError(f"the catalog has no umbilicus for {row['volume']}; source estimate makes one")
        chain = a.get("estimator") or ["villa"]
        if not grids and "centrenet" not in chain:
            raise ToolError(f"{row['volume']} has no published normal grids to estimate an axis from")
        try:
            est = estimate_umbilicus(agent, ctx, row, grids[0] if grids else None, out, a.get("every", 500),
                                     a.get("repeats", 3), a.get("seed", 1), a.get("window", 5), a.get("max_jump_um"),
                                     a.get("z_range"), estimator=chain, sample=a.get("sample"),
                                     polish=_polish_arg(a.get("polish")))
        except AutoError as exc:
            raise ToolError(str(exc)) from exc
        result.update(est)
        if src == "compare":
            if not cat_url:
                raise ToolError(f"the catalog has no umbilicus for {row['volume']} to compare with")
            download(cat_url, out / "catalog_umbilicus.json", tries=8)
            ref = vc3d_orient.load_umbilicus(str(out / "catalog_umbilicus.json"))
            mine = vc3d_orient.load_umbilicus(est["umbilicus"])
            d = axis_distance(mine, ref)
            result["compare"] = {"catalog": cat_url, "voxels": d,
                                 "um": {k: round(v * row["voxel_um"], 1) if k != "n" else v for k, v in d.items()}}
        return result

    @tool("seeds", "Propose seeds", "Seed points for tracing with no person picking them: on a surface prediction "
          "(0 to 255) at the tracer's threshold, inside a radial band around the umbilicus, on papyrus in the CT, "
          "spaced apart, at random heights from a fixed seed (the same data and seed give the same points). Each "
          "seed passes the same check trace runs (seed_check).",
          {"prediction": STR("surface prediction zarr: path or URL"), "ct": STR("CT volume in the same frame, for "
                                                                               "the papyrus or air check"),
           "umbilicus": STR("umbilicus file (villa JSON or text)"), "count": INT("seeds wanted (default 4)", minimum=1),
           "voxel_um": NUM("voxel size in um"), "z_range": ARR("slices [z0, z1) (default the middle 80 %)",
                                                              {"type": "integer"}, minItems=2, maxItems=2),
           "radius_um": ARR("radial band [min, max] in um from the axis (default [1500, none])",
                            {"type": ["number", "null"]}, minItems=2, maxItems=2),
           "level": INT("pyramid level of the coarse search (default 4)", minimum=0),
           "min_spacing_um": NUM("least distance between seeds (default 2000 um)"),
           "seed": INT("random seed (default 0)", minimum=0), "max_planes": INT("heights tried at most (default 24)",
                                                                              minimum=1),
           "box": ARR("keep seeds inside [[y0, y1], [x0, x1]] (level-0 voxels, half-open): a prediction made over one "
                      "box (with z_range for z)", {"type": "array"}, minItems=2, maxItems=2)},
          required=["prediction", "umbilicus", "voxel_um"], openworld=True, readonly=True)
    def h_seeds(ctx, a):
        from . import vc3d_prep_tools
        pred = vc3d_prep_tools._volume(agent, ctx, a["prediction"], "prediction")
        axis = vc3d_orient.load_umbilicus(str(agent.existing(ctx, a["umbilicus"], "umbilicus")))

        def check(xyz):
            return vc3d_prep_tools.check_seed(agent, ctx, a["prediction"], xyz, ct=a.get("ct"))

        try:
            seeds, stats = propose_seeds(pred, axis, a.get("count", 4), pred.shape(0), a["voxel_um"], a.get("z_range"),
                                         a.get("radius_um") or (1500.0, None), a.get("level", 4),
                                         a.get("min_spacing_um", 2000.0), a.get("seed", 0), a.get("max_planes", 24),
                                         check=check, log=ctx.say, box_yx=a.get("box"))
        except AutoError as exc:
            raise ToolError(str(exc)) from exc
        return {"seeds": seeds, "stats": stats, "chunks_read": pred.chunks_read}

    @tool("distortion", "Measure distortion", "How far a tifxyz surface's grid is from an isometric map of the plane: "
          "stretch along rows and columns in grid steps (1 is isometric), shear between them and area per cell. Use "
          "it on a flattened surface to accept or refuse the flattening, or on any trace.",
          {"surface": STR("tifxyz folder"), "limits": OBJ("optional pass limits: max_p95_stretch (0.25), "
                                                          "max_shear_deg_p95 (20), min_area_ratio (0.8), "
                                                          "max_area_ratio (1.25)")},
          required=["surface"], readonly=True)
    def h_distortion(ctx, a):
        surface = agent.existing(ctx, a["surface"], "surface", "tifxyz")
        try:
            d = grid_distortion(surface)
        except (AutoError, vc3d_io.IOFormatError) as exc:
            raise ToolError(str(exc)) from exc
        limits = {**DEFAULTS["flatten"], **(a.get("limits") or {})}
        ok, why = distortion_passes(d, limits)
        return {**d, "passes": ok, "reasons": why,
                "limits": {k: limits[k] for k in ("max_p95_stretch", "max_shear_deg_p95", "min_area_ratio",
                                                  "max_area_ratio")}}

    def learn_schema(*builders):
        try:
            from . import aplearn
        except ImportError:      # a copy without the learner
            return OBJ("learn: not in this copy")
        return aplearn.tool_schema(*builders)

    ext_actions = {name: ext for ext in ACTION_EXTENSIONS for name in ext.actions}
    actions = ["plan", "run", "status", "backends", "preflight", "graph", "why", "swap", "diff", "learn"]
    actions += list(ext_actions)
    ext_about = "".join(ext.about for ext in ACTION_EXTENSIONS)
    ext_params = {k: v for ext in ACTION_EXTENSIONS for k, v in ext.params(agent).items()}

    @tool("autopipeline", "Run AutoPipeline", "AutoPipeline, the whole chain on one scan with no person in between: "
          "acquire, umbilicus, seeds, trace, qa (fixed acceptance rule), flatten (kept only when its distortion "
          "passes), render (after a chunk audit), ink (with the reverse control; handed to the Modal runner when this "
          "machine has no model), score (labeled benchmarks only) and report (with settings triage, the surfaces "
          "ranked by kit rowscore's text-row score of their maps, the reverse and shuffled maps beside: a reading "
          "order, not a verdict; with crackle, Crackle Check's control-set gate on each surface's forward and "
          "reverse maps, whole and per tile). action plan freezes a plan; run runs "
          "or resumes one; status reads it. A target run needs a preregistered experiment. Called autopipe before "
          "9 Oct 2026; that name still works. Hot-swap and causal links (kit/apbackends.py, kit/apgraph.py): backends "
          "lists each stage's backends, ours and the community's, and whether this machine can run them; preflight "
          "checks a plan's; graph writes the run's provenance graph (graph.json: which stage, backend, inputs and "
          "settings made each output); why traces one output; swap makes a sibling plan with one stage's backend "
          "replaced and the rest held (reuse carries the earlier stages over); diff compares two runs and names the "
          "first stage where they diverge. Learning from past runs (kit/aplearn.py, no compute): every run leaves a "
          "record in a ledger; learn reads it (status, suggest settings for the next plan with their evidence, "
          "estimate stage times and where the compute rule puts the job, review a trace as a person, ingest run "
          "folders, evaluate the preregistered check); plan with learned adds the suggestion under the given "
          "settings." + ext_about,
          {"action": STR(", ".join(actions[:-1]) + " or " + actions[-1], enum=actions),
           "sample": STR("plan: sample id"), "settings": OBJ("plan: settings over the defaults, optional ones such "
                                                             "as triage included (see a note of the source repository). For a "
                                                             "fresh scroll name trace.budget (time budgets, snapshots, "
                                                             "partial surfaces), or pass new_defaults"),
           "out": STR("run folder (default work/autopipe/<sample>-<time>; target runs go under experiments/<slug>/)"),
           "until": STR("run: last stage to run", enum=list(STAGES)),
           "path": STR("why: an output of the run, relative to out or absolute"),
           "stage": STR("swap: the stage whose backend changes (umbilicus, trace, flatten, snap, repair, ink, "
                        "triage or crackle)"),
           "backend": ARR("swap: the new backend; umbilicus takes several, tried in order", {"type": "string"}),
           "to": STR("swap: the new run folder (default beside out, named for the swap)"),
           "reuse": BOOL("swap: carry over the stages before the swapped one, so the new run starts there "
                         "(default false)"),
           "other": STR("diff: the run folder to compare with out"),
           "learned": BOOL("plan: add the learning ledger's suggested settings under the given ones; learned.json in "
                           "the run folder says what changed and why"),
           "learned_from": STR("plan: replay a verified local frozen-advice file; exclusive with learned"),
           "new_defaults": BOOL("plan: add the settings recommended for a new plan on a fresh scroll "
                                "(NEW_PLAN_DEFAULTS: trace.budget, and for an axis AutoPipeline estimates "
                                "umbilicus.estimator [centrenet, villa] with umbilicus.polish) where the given "
                                "settings do not name them, to a "
                                "benchmark or smoke plan (default false: the plan is exactly the settings given)"),
           "learn": learn_schema(OBJ, STR, NUM, INT, ARR), **ext_params},
          required=["action"], background=True, openworld=True)
    def h_autopipe(ctx, a):
        action = a["action"]
        if action == "backends":
            from . import apbackends
            return apbackends.listing(ctx, agent)
        if action in ext_actions:
            return ext_actions[action].call(ctx, agent, a)
        if action == "learn":
            from . import aplearn
            return aplearn.tool_call(ctx, agent, a)
        if action == "plan":
            if not a.get("sample"):
                raise ToolError("plan needs sample")
            settings, learned, frozen, added = a.get("settings"), None, None, []
            if a.get("learned") and a.get("learned_from"):
                raise ToolError("learned and learned_from are mutually exclusive")
            if a.get("new_defaults") and a.get("learned_from") is not None:
                raise ToolError("new_defaults and learned_from are mutually exclusive: frozen advice replays the "
                                "settings it was made for")
            if a.get("new_defaults"):
                # asked for: the recommended settings for a new plan (NEW_PLAN_DEFAULTS), put in before the learner
                # reads the settings, so the arm it suggests for is the arm the plan's traces are recorded under
                settings, added = new_plan_settings(settings)
            if a.get("learned_from") is not None:
                from . import aplearn, aplearn_frozen
                try:
                    if not isinstance(a["learned_from"], str) or not a["learned_from"].strip():
                        raise aplearn.LearnError("learned_from must be a frozen-advice file path")
                    frozen_path = agent.resolve(ctx, a["learned_from"])
                    frozen = aplearn_frozen.read(frozen_path)
                    settings, learned = aplearn_frozen.for_plan(frozen, a["sample"], settings)
                    learned["frozen_file"] = str(frozen_path)
                except (aplearn.LearnError, OSError, ValueError) as exc:
                    raise ToolError(str(exc)) from exc
            elif a.get("learned"):
                from . import aplearn
                try:
                    settings, learned = aplearn.for_plan(ctx, a["sample"], settings)
                except aplearn.LearnError as exc:
                    raise ToolError(str(exc)) from exc
            try:
                plan = make_plan(a["sample"], settings, cache_dir=ctx.home / "cache", root=ctx.root,
                                 models=agent.load_models(ctx))
                if frozen is not None:
                    try:
                        aplearn_frozen.check_plan(frozen, learned, plan)
                    except aplearn.LearnError as exc:
                        raise ToolError(str(exc)) from exc
                elif learned is not None and aplearn.axis_conflict(learned, plan):
                    # the catalog has this scan's axis, or the earlier axis is of another scan than the plan's
                    base = new_plan_settings(a.get("settings"))[0] if a.get("new_defaults") else a.get("settings")
                    settings, learned = aplearn.for_plan(ctx, a["sample"], base, axis=False)
                    plan = make_plan(a["sample"], settings, cache_dir=ctx.home / "cache", root=ctx.root,
                                     models=agent.load_models(ctx))
            except (AutoError, vc3d_catalog.CatalogError) as exc:
                raise ToolError(str(exc)) from exc
            out = run_folder(agent, ctx, plan, a.get("out"))
            if frozen is not None and any((out / name).exists() or (out / name).is_symlink()
                                          for name in ("plan.json", "learned.json")):
                raise ToolError("frozen advice needs a new plan folder; existing plan/provenance stays unchanged")
            if (out / "plan.json").is_file():       # another run's plan stays; the same plan again is that run
                try:
                    old = json.loads((out / "plan.json").read_text()).get("digest")
                except (OSError, ValueError, AttributeError):
                    old = None
                if old != plan["digest"]:
                    raise ToolError(f"{out} holds the plan of another run ({str(old or 'unreadable')[:12]}), which "
                                    "this plan would overwrite. Give a new folder with out, or leave out unset")
            (out / "plan.json").write_text(json.dumps(plan, indent=1))
            res = {"plan": str(out / "plan.json"), "digest": plan["digest"], "out": str(out),
                   "resolved": plan["resolved"], **({"new_defaults": added} if added else {})}
            if learned is not None:
                res["learned"] = aplearn.summary(learned, aplearn.write_learned(out, learned, plan["digest"]))
            return res
        if not a.get("out"):
            raise ToolError(f"{action} needs out=<run folder> (from plan)")
        out = agent.resolve(ctx, a["out"])
        if not (out / "plan.json").is_file():
            raise ToolError(f"{out} has no plan.json; make one with action plan")
        plan = json.loads((out / "plan.json").read_text())
        if action in ("preflight", "graph", "why", "swap", "diff"):
            return causal(ctx, a, out, plan)
        if action == "status":
            st = json.loads((out / "state.json").read_text()) if (out / "state.json").is_file() else {}
            return {"out": str(out), "digest": plan.get("digest"), "running": st.get("running"),
                    **({"graph": str(out / "graph.json")} if (out / "graph.json").is_file() else {}),
                    "stages": {k: {kk: v.get(kk) for kk in ("status", "at", "error", "seconds")}
                               for k, v in (st.get("stages") or {}).items()},
                    "surfaces": {k: {"accepted": v.get("accepted"), "render": (v.get("render") or {}).get("zarr")}
                                 for k, v in (st.get("surfaces") or {}).items()}}
        try:
            check_target(agent, ctx, plan)
            r = Run(agent, ctx, out, plan, log=ctx.say)
            st = r.run(until=a.get("until"))
        except AutoError as exc:
            raise ToolError(str(exc)) from exc
        failed = {k: v.get("error") for k, v in st["stages"].items() if v.get("status") == "failed"}
        return {"out": str(out), "stages": {k: v.get("status") for k, v in st["stages"].items()},
                "failed": failed or None, "report": (st["stages"].get("report") or {}).get("record"),
                **({"graph": str(out / "graph.json")} if (out / "graph.json").is_file() else {}),
                "note": "model output, not a reading"}

    def causal(ctx, a, out, plan):
        """preflight, graph, why, swap and diff (kit/apbackends.py, kit/apgraph.py)."""
        from . import apbackends, apgraph
        action = a["action"]
        try:
            if action == "preflight":
                check_plan(plan)
                return apbackends.preflight(plan, ctx, agent)
            if action == "graph":
                path = apgraph.write(out)
                g = json.loads(path.read_text())
                kinds = {}
                for n in g["nodes"]:
                    kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
                return {"graph": str(path), "digest": g["digest"], "nodes": kinds, "edges": len(g["edges"]),
                        "stages": {n["stage"]: {"status": n["status"], "backend": (n.get("backend") or {}).get("name"),
                                                **({"reused_from": n["reused_from"]} if n.get("reused_from") else {})}
                                   for n in g["nodes"] if n["kind"] == "stage"},
                        "swap_of": g.get("swap_of")}
            if action == "why":
                if not a.get("path"):
                    raise ToolError("why needs path=<an output of the run>")
                return apgraph.why(out, a["path"])
            if action == "swap":
                if not a.get("stage") or not a.get("backend"):
                    raise ToolError("swap needs stage and backend")
                names = a["backend"]
                backend = names[0] if len(names) == 1 else names
                dest = agent.writable(ctx, agent.resolve(ctx, a["to"])) if a.get("to") else None
                return apgraph.swap(out, a["stage"], backend, new_out=dest, reuse=bool(a.get("reuse")),
                                    models=agent.load_models(ctx))
            if not a.get("other"):
                raise ToolError("diff needs other=<a second run folder>")
            return apgraph.diff(out, agent.resolve(ctx, a["other"]))
        except (AutoError, apgraph.GraphError, apbackends.BackendError, OSError) as exc:
            raise ToolError(str(exc)) from exc


def run_folder(agent, ctx, plan, given=None):
    """Where a run's files go: under work/autopipe for benchmarks and smoke runs, under experiments/<slug>/autopipe
    for a target, never in a folder git tracks."""
    s = plan["settings"]
    name = f"{plan['resolved']['sample']}-{plan['resolved']['volume']}-{plan['digest'][:10]}"
    if s["purpose"] == "target":
        base = ctx.root / "experiments" / s["experiment"] / "autopipe"
        out = agent.resolve(ctx, given) if given else base / name
        if not str(out).startswith(str(base)):
            raise agent.ToolError(f"target runs stay under {base}")
    else:
        out = agent.resolve(ctx, given) if given else ctx.root / "work" / "autopipe" / name
    out = agent.writable(ctx, out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def check_target(agent, ctx, plan):
    """A target run needs its ledger experiment to exist, pass its check and be planned or running, before any
    stage runs (the same rule the ink tool applies before a map)."""
    s = plan["settings"]
    if s["purpose"] != "target":
        return
    from . import ledger, prizes
    root = ctx.root / "experiments"
    try:
        rec = ledger.load(s["experiment"], root=root)
        problems = ledger.check(s["experiment"], root=root)
    except ledger.LedgerError as exc:
        raise AutoError(f"experiment {s['experiment']!r}: {exc}. Preregister it first (kit run init)") from exc
    if problems:
        raise AutoError(f"experiment {s['experiment']!r} fails its ledger check: {'; '.join(problems)}")
    if rec["status"] not in ("planned", "running"):
        raise AutoError(f"experiment {s['experiment']!r} is {rec['status']}, not planned or running")
    sample = plan.get("resolved", {}).get("sample")
    if sample and prizes.normalize_scroll(str(rec.get("scroll") or "")) != prizes.normalize_scroll(sample):
        raise AutoError(f"experiment {s['experiment']!r} is preregistered for {rec.get('scroll')!r}, not {sample}")


# ---------------------------------------------------------------- command line

def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("plan", help="freeze a plan for one scan (resolves scan, prediction, grids, axis)")
    a.add_argument("sample")
    a.add_argument("--settings", help="JSON object, or @file, of settings over the defaults")
    a.add_argument("--out", help="run folder (default work/autopipe/<sample>-<volume>-<digest>)")
    learning = a.add_mutually_exclusive_group()
    learning.add_argument("--learned", action="store_true",
                   help="add the learning ledger's suggested settings under the given ones (kit/aplearn.py); "
                        "learned.json in the run folder says what changed and why")
    learning.add_argument("--learned-from", metavar="FILE",
                          help="replay verified frozen advice without reading today's learning ledger")
    a.add_argument("--new-defaults", action="store_true",
                   help="add the settings recommended for a new plan on a fresh scroll (NEW_PLAN_DEFAULTS: "
                        "trace.budget, and for an estimated axis umbilicus.estimator [centrenet, villa] with "
                        "umbilicus.polish) where --settings does not name them; without it the plan is exactly the "
                        "settings given")
    a = actions.add_parser("run", help="run or resume a planned run")
    a.add_argument("out")
    a.add_argument("--until", choices=STAGES)
    a.add_argument("--monitor", nargs="?", const=8765, type=int, metavar="PORT",
                   help="serve the live monitor page on 127.0.0.1 while the run lasts (default port 8765)")
    a = actions.add_parser("status", help="each stage's status and each surface's result")
    a.add_argument("out")
    actions.add_parser("defaults", help="print the default settings")
    actions.add_parser("backends", help="each stage's backends, ours and the community's, and whether this machine "
                                        "can run them")
    a = actions.add_parser("preflight", help="the backends a planned run will use, what is missing and how to get it")
    a.add_argument("out")
    a = actions.add_parser("graph", help="write the run's provenance graph (graph.json) and summarize it")
    a.add_argument("out")
    a = actions.add_parser("why", help="the stage, backend, settings and inputs that made one output, and what is "
                                       "upstream of it")
    a.add_argument("out")
    a.add_argument("path", help="an output of the run, relative to OUT or absolute")
    a = actions.add_parser("swap", help="a sibling plan with one stage's backend replaced and everything else held")
    a.add_argument("out")
    a.add_argument("--stage", required=True)
    a.add_argument("--backend", required=True, nargs="+",
                   help="the new backend; umbilicus takes several, tried in order")
    a.add_argument("--to", help="the new run folder (default beside OUT)")
    a.add_argument("--reuse", action="store_true",
                   help="carry over the stages before the swapped one, so the new run starts there")
    a = actions.add_parser("diff", help="two runs compared stage by stage: the first stage where they diverge")
    a.add_argument("out")
    a.add_argument("other")
    for ext in ACTION_EXTENSIONS:
        ext.add_parser(actions)
    from . import aplearn, autopipe_monitor
    autopipe_monitor.add_parser(actions)
    aplearn.add_parser(actions)


def cmd_autopipe(args):
    from . import vc3d_agent
    if args.action == "defaults":
        print(json.dumps(DEFAULTS, indent=1))
        return 0
    if args.action == "monitor":
        from . import autopipe_monitor
        return autopipe_monitor.cli(args)
    if args.action == "learn":
        from . import aplearn
        return aplearn.cli(args)
    if args.action == "plan":
        settings = None
        if args.settings:
            text = Path(args.settings[1:]).read_text() if args.settings.startswith("@") else args.settings
            settings = json.loads(text)
        call = {"action": "plan", "sample": args.sample, "settings": settings, "out": args.out,
                "learned": True if args.learned else None, "learned_from": args.learned_from,
                "new_defaults": True if getattr(args, "new_defaults", False) else None}
    elif args.action == "backends":
        call = {"action": "backends"}
    elif any(args.action in ext.commands for ext in ACTION_EXTENSIONS):
        call = next(ext for ext in ACTION_EXTENSIONS if args.action in ext.commands).cli_call(args)
    else:
        call = {"action": args.action, "out": args.out}
        for k in ("until", "path", "stage", "backend", "to", "other"):
            if getattr(args, k, None):
                call[k] = getattr(args, k)
        if getattr(args, "reuse", False):
            call["reuse"] = True
    ctx = vc3d_agent.Context(progress=lambda m: print(m, file=sys.stderr, flush=True))
    mon = None
    if getattr(args, "monitor", None) is not None and args.action == "run":
        from . import autopipe_monitor
        mon = autopipe_monitor.start(vc3d_agent.resolve(ctx, args.out), args.monitor)
    try:
        res = vc3d_agent.call("autopipeline", {k: v for k, v in call.items() if v is not None}, ctx)
    except vc3d_agent.ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        ctx.close()
        if mon is not None:
            mon.stop()
    print(json.dumps(res, indent=1, default=str))
    return 1 if res.get("failed") or res.get("status") == "failed" else 0


# ---------------------------------------------------------------- trace methods

def register_actions(ext):
    """Add agent tool actions and their command: an object with actions (the tool actions it handles), commands (the
    `kit autopipeline` commands it adds), about (text added to the tool's description), params(agent) (its tool
    parameters, a dict of agent schema builders' values), call(ctx, agent, a) (one of its actions),
    add_parser(actions) (its commands' parsers) and cli_call(args) (the tool call one of its commands makes)."""
    ACTION_EXTENSIONS.append(ext)


def register_trace_method(method):
    """Add a trace method: an object with name, defaults (the setting's defaults, a dict), check(settings) (make_plan's
    refusals; may fill defaults in place), resolved(settings) (a dict merged into the plan's resolved part, such as a
    rule digest) and trace(run, sid, args) (a result shaped as the trace tool's, with the method's summary under its
    name). Its setting trace.<name> is optional, so plans that do not use it keep their digest."""
    if not isinstance(method.defaults, dict):
        raise TypeError("a trace method's defaults are a dict")
    TRACE_METHODS[method.name] = method
    OPTIONAL[f"trace.{method.name}"] = method.defaults


def trace_method(s):
    """The plan's trace method, or None for the trace tool. A plan that names one this kit lacks is refused."""
    names = [k for k, v in s["trace"].items() if v is not None and k not in DEFAULTS["trace"]
             and f"trace.{k}" not in PLAIN_OPTIONAL]
    unknown = [k for k in names if k not in TRACE_METHODS]
    if unknown:
        raise AutoError(f"this kit has no trace method {', '.join(unknown)} (a plan made by a kit with an extension "
                        f"this one lacks)")
    if len(names) > 1:
        raise AutoError(f"one trace method at a time, not {', '.join(names)}")
    return TRACE_METHODS[names[0]] if names else None


def check_trace_methods(s):
    method = trace_method(s)
    if method is not None:
        if s["trace"].get("budget") is not None:
            raise AutoError(f"trace.budget sets the trace tool's budget and snapshots; trace.{method.name} runs its "
                            "own loop, so a plan names one or the other")
        method.check(s)


def trace_method_resolved(s):
    method = trace_method(s)
    return dict(method.resolved(s)) if method is not None else {}


def _load_extensions():
    """Import every kit/autopipe_ext_*.py beside this module; each registers itself on import."""
    import importlib
    import pkgutil
    for info in sorted(pkgutil.iter_modules([str(Path(__file__).resolve().parent)]), key=lambda i: i.name):
        if info.name.startswith("autopipe_ext_"):
            importlib.import_module(f"{__package__}.{info.name}")


_load_extensions()
