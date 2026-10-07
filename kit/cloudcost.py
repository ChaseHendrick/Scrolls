"""Modal cost calculator for scroll compute jobs: rates from a dated JSON, no network.

Rates, limits and their source URLs live in docs/compute/modal-rates.json (access date
inside the file). Job assumptions live in docs/compute/modal-jobs.json. Every estimate is
low / typical / high, because GPU hours for these jobs are assumptions, not measurements.

Usage (from the repository root):

    python3 -m kit.cloudcost rates                       # hourly rates per GPU type
    python3 -m kit.cloudcost cost --gpu H100 --gpus 1 --hours 2 --cpu 4 --mem 32
    python3 -m kit.cloudcost infer --profile 2p5d_9um --area 40 --um 7.91 --passes 2
    python3 -m kit.cloudcost jobs                        # table for every job in modal-jobs.json
    python3 -m kit.cloudcost budget 30 100 500           # GPU hours a budget buys

Standard library only. Prices are list prices on the access date; check
https://modal.com/pricing before spending.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATES = ROOT / "docs" / "compute" / "modal-rates.json"
JOBS = ROOT / "docs" / "compute" / "modal-jobs.json"
LEVELS = ("low", "typical", "high")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_rates(path=None):
    return load(path or RATES)


def load_jobs(path=None):
    return load(path or JOBS)


def gpu_per_hour(rates, gpu):
    try:
        return rates["gpu_usd_per_s"][gpu] * 3600.0
    except KeyError:
        raise ValueError(f"unknown GPU {gpu!r}; known: {', '.join(rates['gpu_usd_per_s'])}") from None


def container_cost(rates, hours, gpu=None, gpus=1, cpu=0.125, mem_gib=0.125, containers=1,
                   region="none", nonpreemptible=False):
    """USD for `containers` identical containers running `hours` each.

    CPU is in physical cores (2 vCPU each), memory in GiB; both are raised to Modal's
    per-container minimums. Region multiplier applies to everything; nonpreemptible
    triples CPU and memory and is refused for GPU containers (Modal does not support it).
    """
    if hours < 0 or containers < 0 or gpus < 0 or cpu < 0 or mem_gib < 0:
        raise ValueError("negative input")
    if gpu and nonpreemptible:
        raise ValueError("Modal does not support nonpreemptible GPU Functions")
    if gpu:
        limit = rates["max_gpus_per_container"].get(gpu)
        if isinstance(limit, int) and gpus > limit:
            raise ValueError(f"{gpu} allows at most {limit} GPUs per container")
    secs = hours * 3600.0 * containers
    mult = rates["region_multiplier"][region]
    cm = rates["nonpreemptible_cpu_mem_multiplier"] if nonpreemptible else 1.0
    g = rates["gpu_usd_per_s"][gpu] * gpus * secs if gpu else 0.0
    c = max(cpu, rates["min_cpu_cores"]) * rates["cpu_usd_per_core_s"] * secs * cm
    m = max(mem_gib, rates["min_mem_gib"]) * rates["mem_usd_per_gib_s"] * secs * cm
    out = {"gpu": g * mult, "cpu": c * mult, "mem": m * mult}
    out["total"] = out["gpu"] + out["cpu"] + out["mem"]
    return out


def volume_cost(rates, gib, months=1.0, free_gib=None):
    free = rates["volume_free_gib"] if free_gib is None else free_gib
    return max(0.0, gib - free) * rates["volume_usd_per_gib_month"] * months


def egress_cost(rates, gib, plan="starter", already_used_gib=0.0):
    free = rates["egress_free_gib"][plan]
    billable = max(0.0, gib + already_used_gib - max(free, already_used_gib))
    return billable * rates["egress_usd_per_gib"]


def _triple(x):
    if isinstance(x, (int, float)):
        return [float(x)] * 3
    if len(x) != 3:
        raise ValueError(f"expected [low, typical, high], got {x!r}")
    return [float(v) for v in x]


def surface_volume_gb(area_cm2, um, layers, bytes_per_voxel=1):
    """Uncompressed size of a flattened surface volume: area x (1 cm / voxel)^2 x layers."""
    px = (1e4 / um) ** 2
    return area_cm2 * px * layers * bytes_per_voxel / 1e9


def inference_phases(profile, area_cm2, um, passes=1):
    """Phases (image build, staging on CPU, GPU inference) for one reader over area_cm2.

    GPU seconds per cm2 are given at the profile's reference voxel size and scale with
    voxel count, (ref_um / um)^p: p = 2 for 2.5D readers (fixed layer count), p = 3 for
    native 3D readers (fixed physical thickness, so the layer count also grows). Staging time is uncompressed surface volume size over an
    assumed download rate (fast, typical, slow): an upper bound when data are compressed.
    """
    power = profile.get("scale_power", 2)
    scale = (profile["ref_um"] / um) ** power
    gpu_s = [v * scale * area_cm2 * passes for v in _triple(profile["gpu_s_per_cm2"])]
    layers = profile["layers"] * (profile["ref_um"] / um) ** (power - 2)
    gb = surface_volume_gb(area_cm2, um, layers, profile.get("bytes_per_voxel", 1))
    rate = _triple(profile.get("stage_mb_per_s", [100, 50, 20]))
    stage_h = [gb * 1000.0 / r / 3600.0 for r in rate]
    phases = [
        {"name": "image build (CPU, first run only)", "gpu": None, "cpu": 2, "mem_gib": 4,
         "hours": _triple(profile.get("image_build_h", [0.1, 0.25, 0.5]))},
        {"name": f"stage {gb:.1f} GB surface volume to a Volume (CPU)", "gpu": None, "cpu": 4,
         "mem_gib": 16, "hours": stage_h},
        {"name": f"inference on {profile['gpu']}, {passes} pass(es)", "gpu": profile["gpu"],
         "gpus": 1, "cpu": profile.get("cpu", 4), "mem_gib": profile.get("mem_gib", 32),
         "hours": [s / 3600.0 + profile.get("startup_h", 0.05) for s in gpu_s]},
    ]
    return phases, gb


def expand(job, profiles):
    """A job dict with explicit phases; an 'inference' block is expanded through its profile."""
    job = dict(job)
    phases = list(job.get("phases", []))
    inf = job.get("inference")
    if inf:
        prof = profiles[inf["profile"]]
        extra, gb = inference_phases(prof, inf["area_cm2"], inf["um"], inf.get("passes", 1))
        phases = extra + phases
        job.setdefault("volume_gib", [gb, gb, gb])
    job["phases"] = phases
    return job


def estimate(rates, job, profiles=None, region="none", plan="starter"):
    """Low / typical / high USD for a job, with a per-phase breakdown."""
    job = expand(job, profiles or {})
    out = {"id": job.get("id"), "name": job.get("name"), "phases": []}
    totals = [0.0, 0.0, 0.0]
    gpu_h = [0.0, 0.0, 0.0]
    for ph in job["phases"]:
        hrs = _triple(ph["hours"])
        row = {"name": ph["name"], "gpu": ph.get("gpu"), "gpus": ph.get("gpus", 1),
               "containers": ph.get("containers", 1), "hours": hrs, "usd": []}
        for i, h in enumerate(hrs):
            c = container_cost(rates, h, gpu=ph.get("gpu"), gpus=ph.get("gpus", 1),
                               cpu=ph.get("cpu", 0.125), mem_gib=ph.get("mem_gib", 0.125),
                               containers=ph.get("containers", 1), region=region)
            row["usd"].append(c["total"])
            totals[i] += c["total"]
            if ph.get("gpu"):
                gpu_h[i] += h * ph.get("gpus", 1) * ph.get("containers", 1)
        out["phases"].append(row)
    vol = _triple(job.get("volume_gib", 0))
    months = job.get("volume_months", 1.0)
    egr = _triple(job.get("egress_gib", 0))
    for i in range(3):
        totals[i] += volume_cost(rates, vol[i], months) + egress_cost(rates, egr[i], plan)
    out["gpu_hours"] = dict(zip(LEVELS, gpu_h))
    out["usd"] = dict(zip(LEVELS, totals))
    out["volume_gib"] = vol
    return out


def budget_hours(rates, budget, gpu, gpus=1, cpu=4, mem_gib=32):
    """Wall hours of one container (gpus x gpu plus cpu and memory) that `budget` USD buys."""
    per_h = container_cost(rates, 1.0, gpu=gpu, gpus=gpus, cpu=cpu, mem_gib=mem_gib)["total"]
    return budget / per_h


def work_cost(rates, gpu, cpu=4, mem_gib=32):
    """USD per A100-80GB-equivalent hour of CNN training (None if no speed figure)."""
    sp = rates["speed_vs_a100_80gb"].get(gpu, {}).get("value")
    if not sp:
        return None
    return container_cost(rates, 1.0, gpu=gpu, cpu=cpu, mem_gib=mem_gib)["total"] / sp


def _usd(x):
    return f"{x:,.2f}" if x >= 0.995 else f"{x:.3f}"


def rates_table(rates, cpu=4, mem_gib=32):
    lines = [f"Modal list prices, accessed {rates['accessed']} ({rates['gpu_source']}).",
             f"Container column adds {cpu:g} cores and {mem_gib:g} GiB memory.", "",
             "| GPU | USD/s | USD/h GPU only | USD/h container | USD per A100-80GB-equivalent hour |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for g, s in rates["gpu_usd_per_s"].items():
        wc = work_cost(rates, g, cpu, mem_gib)
        cont = container_cost(rates, 1.0, gpu=g, cpu=cpu, mem_gib=mem_gib)["total"]
        lines.append(f"| {g} | {s:.6f} | {s * 3600:.4f} | {cont:.4f} | {'n/a' if wc is None else f'{wc:.2f}'} |")
    cpu_h = rates["cpu_usd_per_core_s"] * 3600
    mem_h = rates["mem_usd_per_gib_s"] * 3600
    lines.append(f"\nCPU {cpu_h:.5f} USD per core-hour; memory {mem_h:.6f} USD per GiB-hour.")
    return "\n".join(lines)


def jobs_table(rates, jobs_doc, region="none", plan="starter"):
    profiles = jobs_doc.get("inference_profiles", {})
    lines = ["| Job | GPU hours (low / typical / high) | USD low | USD typical | USD high |",
             "| --- | --- | ---: | ---: | ---: |"]
    for job in jobs_doc["jobs"]:
        e = estimate(rates, job, profiles, region, plan)
        gh = e["gpu_hours"]
        lines.append(f"| {e['name']} | {gh['low']:.2f} / {gh['typical']:.2f} / {gh['high']:.2f} | "
                     f"{_usd(e['usd']['low'])} | {_usd(e['usd']['typical'])} | {_usd(e['usd']['high'])} |")
    return "\n".join(lines)


def budget_table(rates, budgets, gpus=None, cpu=4, mem_gib=32):
    gpus = gpus or list(rates["gpu_usd_per_s"])
    head = "| GPU | " + " | ".join(f"{b:g} USD: h GPU only / h container" for b in budgets) + " |"
    lines = [head, "| --- |" + " ---: |" * len(budgets)]
    for g in gpus:
        cells = []
        for b in budgets:
            only = b / gpu_per_hour(rates, g)
            cont = budget_hours(rates, b, g, cpu=cpu, mem_gib=mem_gib)
            cells.append(f"{only:.1f} / {cont:.1f}")
        lines.append(f"| {g} | " + " | ".join(cells) + " |")
    lines.append(f"\nContainer hours include {cpu:g} cores and {mem_gib:g} GiB memory per GPU container.")
    return "\n".join(lines)


def build_parser():
    p = argparse.ArgumentParser(prog="python3 -m kit.cloudcost", description=__doc__.split("\n")[0])
    p.add_argument("--rates", help="rates JSON (default docs/compute/modal-rates.json)")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("rates", help="hourly rates per GPU type")
    r.add_argument("--cpu", type=float, default=4)
    r.add_argument("--mem", type=float, default=32)
    c = sub.add_parser("cost", help="cost of one phase")
    c.add_argument("--gpu")
    c.add_argument("--gpus", type=int, default=1)
    c.add_argument("--containers", type=int, default=1)
    c.add_argument("--hours", type=float, required=True)
    c.add_argument("--cpu", type=float, default=4)
    c.add_argument("--mem", type=float, default=32)
    c.add_argument("--region", choices=["none", "broad", "narrow"], default="none")
    c.add_argument("--nonpreemptible", action="store_true")
    i = sub.add_parser("infer", help="one reader over an area")
    i.add_argument("--profile", required=True)
    i.add_argument("--area", type=float, required=True, help="cm2")
    i.add_argument("--um", type=float, required=True, help="voxel size of the surface volume")
    i.add_argument("--passes", type=int, default=1, help="e.g. 2 for forward plus reversed depth")
    i.add_argument("--jobs", help="jobs JSON with inference_profiles")
    j = sub.add_parser("jobs", help="table of all jobs in a jobs JSON")
    j.add_argument("file", nargs="?", help="jobs JSON (default docs/compute/modal-jobs.json)")
    j.add_argument("--json", action="store_true")
    b = sub.add_parser("budget", help="GPU hours bought by budgets")
    b.add_argument("budgets", nargs="+", type=float)
    b.add_argument("--cpu", type=float, default=4)
    b.add_argument("--mem", type=float, default=32)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    rates = load_rates(args.rates)
    if args.command == "rates":
        print(rates_table(rates, args.cpu, args.mem))
    elif args.command == "cost":
        c = container_cost(rates, args.hours, gpu=args.gpu, gpus=args.gpus, cpu=args.cpu, mem_gib=args.mem,
                           containers=args.containers, region=args.region, nonpreemptible=args.nonpreemptible)
        print(json.dumps({k: round(v, 4) for k, v in c.items()}))
    elif args.command == "infer":
        doc = load_jobs(args.jobs)
        job = {"id": "infer", "name": f"{args.profile} over {args.area:g} cm2 at {args.um:g} um",
               "inference": {"profile": args.profile, "area_cm2": args.area, "um": args.um, "passes": args.passes}}
        e = estimate(rates, job, doc["inference_profiles"])
        for ph in e["phases"]:
            print(f"{ph['name']}: hours {' / '.join(f'{h:.2f}' for h in ph['hours'])}, "
                  f"USD {' / '.join(_usd(u) for u in ph['usd'])}")
        print(f"total USD low {_usd(e['usd']['low'])}, typical {_usd(e['usd']['typical'])}, high {_usd(e['usd']['high'])}")
    elif args.command == "jobs":
        doc = load_jobs(args.file)
        if args.json:
            out = [estimate(rates, job, doc.get("inference_profiles", {})) for job in doc["jobs"]]
            print(json.dumps(out, indent=1))
        else:
            print(jobs_table(rates, doc))
    elif args.command == "budget":
        print(budget_table(rates, args.budgets, cpu=args.cpu, mem_gib=args.mem))
    return 0


if __name__ == "__main__":
    sys.exit(main())
