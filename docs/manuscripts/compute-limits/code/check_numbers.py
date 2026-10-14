"""Check the numbers in paper/compute-limits.tex against data/.

Each check recomputes a value from the files in data/, formats it as the
paper prints it, and requires that exact text in the manuscript. It also
checks every data file's sha256 against data/SHA256SUMS.

Usage, from the folder above code/:  python3 code/check_numbers.py
Exit status 0 when every check passes. Standard library only.
"""
import hashlib
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEX = (ROOT / "paper" / "compute-limits.tex").read_text()
FAILS = []


def load(name):
    return json.loads((DATA / name).read_text())


def need(label, text):
    if text not in TEX:
        FAILS.append(f"{label}: '{text}' not in the manuscript")


def f(x, d):
    """Round half up on the value as written, as the paper does."""
    return str(Decimal(repr(x)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def signed(x, d):
    return ("+" if x >= 0 else "-") + f(abs(x), d)


def mean(row):
    return (row["0841-w00"] + row["0841-ag896"]) / 2


def check_sums():
    for line in (DATA / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        got = hashlib.sha256((DATA / name).read_bytes()).hexdigest()
        if got != digest:
            FAILS.append(f"sha256 of data/{name} does not match SHA256SUMS")


def check_rounds():
    r = load("selftrain_rounds.json")["rounds"]
    tx = lambda tag, k: r[tag]["rows"][k]["texture"]
    base = mean(tx("round1", "readerv2"))
    need("Reader v2 mean", f(base, 4))
    for tag, k, label in (("round1", "readerv2", "Reader v2"), ("round1", "d9v2", "d9v2"),
                          ("round1", "S0-ens", "Round 1, S0 (no pseudo-labels)"),
                          ("round1", "S1-ens", "Round 1, \\textbf{S1} (chosen)"), ("round1", "S2-ens", "Round 1, S2"),
                          ("round2", "V1-ens", "Round 2, \\textbf{V1} (chosen)"), ("round2", "V2-ens", "Round 2, V2"),
                          ("round2", "V3-ens", "Round 2, V3")):
        row = tx(tag, k)
        need(f"table row {k}", f"{label} & {f(row['0841-w00'], 4)} & {f(row['0841-ag896'], 4)} & {f(mean(row), 4)}")
        lead = mean(row) - base
        if k != "readerv2":
            need(f"lead {k}", f"${signed(lead, 4)}$" if k not in ("S1-ens", "V1-ens") else f"$\\mathbf{{{signed(lead, 4)}}}$")
    for tag, arm in (("round1", "S1"), ("round2", "V1")):
        assert r[tag]["chosen"] == arm and r[tag]["go"] is False
        need(f"{arm} lead as stored", f"${signed(r[tag]['lead']['as_stored']['lead'], 4)}$ as stored")
    s1, v1 = mean(tx("round1", "S1-ens")), mean(tx("round2", "V1-ens"))
    need("round 2 below round 1", f"scored ${f(s1 - v1, 4)}$ lower")
    rev = lambda k: mean(r["round2"]["rows"][k + " reverse"]["texture"])
    need("V3 reverse", f"${f(rev('V3-ens'), 3)}$, against V1's ${f(rev('V1-ens'), 3)}$")
    w = [tx(t, k) for t, ks in (("round1", ("S0-ens", "S1-ens", "S2-ens")), ("round2", ("V1-ens", "V2-ens", "V3-ens"))) for k in ks]
    rb = tx("round1", "readerv2")
    if not all(x["0841-w00"] > rb["0841-w00"] and x["0841-ag896"] < rb["0841-ag896"] for x in w):
        FAILS.append("not every arm gained on w00 and lost on ag896")


def check_costs():
    c = {x["run"]: x["usd"] for x in load("costs.json")["runs"]}
    refit = c["fine-tune on CT-registered labels, development"] + c["fine-tune on CT-registered labels, fresh test"]
    r1 = c["self-training round 1, teacher check"] + c["self-training round 1, nine trainings and maps"]
    r2 = c["self-training round 2, nine trainings and maps"]
    total = sum(c.values())
    need("total", f"cost {f(total, 2)}~USD in all")
    need("parts", f"fine-tune {f(refit, 2)}, round~1 {f(r1, 2)}, round~2 {f(r2, 2)}, the probe of Section~\\ref{{sec:probe}} "
                  f"{f(c['B300 throughput probe'], 2)}, and a third round stopped in its speed test {f(c['round 3 launch stopped during its speed test'], 2)}")
    need("round 2 cost", f"Round~2 cost {f(r2, 2)}~USD against round~1's {f(c['self-training round 1, nine trainings and maps'], 2)}~USD")
    need("cost ratio", f"about ${f(r2 / c['self-training round 1, nine trainings and maps'], 1)}$ times the first")


def check_probe():
    p = load("b300_probe.json")
    g = {x["batch"]: x for x in p["gpu"]["runs"]}
    real = {x["batch"]: x for x in p["real"]}
    for b in (16, 64):
        wait = 1 - g[b]["s_per_step"] / real[b]["s_per_step"]
        dw = [x for x in p["data_wait"] if x["batch"] == b][0]["data_wait"]
        assert abs(wait - dw) < 1e-9
    need("table gpu", f"GPU step alone (s) & {f(g[16]['s_per_step'], 4)} & {f(g[64]['s_per_step'], 4)}")
    need("table real", f"Real training step (s) & {f(real[16]['s_per_step'], 4)} & {f(real[64]['s_per_step'], 4)}")
    need("table wait", f"waiting on data & {f(1 - g[16]['s_per_step'] / real[16]['s_per_step'], 2)} & {f(1 - g[64]['s_per_step'] / real[64]['s_per_step'], 2)}")
    need("abstract wait", f"${round(100 * (1 - g[16]['s_per_step'] / real[16]['s_per_step']))}\\%$ of its time at batch 16")
    need("table busy", f"& ${round(real[16]['busy_pct'])}\\%$ & ${round(real[64]['busy_pct'])}\\%$")
    need("table patches", f"Real patches per second & {round(16 / real[16]['s_per_step'])} & {round(64 / real[64]['s_per_step'])}")
    need("batch scaling", f"from {round(g[16]['patches_per_s'])} patches per second at batch 16 to {round(g[256]['patches_per_s'])} at batch 256: "
                          f"${f(g[256]['patches_per_s'] / g[16]['patches_per_s'], 1)}$ times")
    packs = [round(x["patches_per_s"]) for x in p["pack"]["runs"]]
    need("pack", f"delivered {packs[0]}, {packs[1]}, {packs[2]} and {packs[3]} patches per second")
    busy = [round(x["busy_pct"]) for x in p["pack"]["runs"]]
    need("pack busy", f"from ${busy[0]}\\%$ to ${busy[-1]}\\%$")
    th = {(x["batch"], x["workers"]): x["batches_per_s"] for x in p["loader"]["threads"]}
    pr = {(x["batch"], x["workers"]): x["batches_per_s"] for x in p["loader"]["procs"]}
    need("loader 1 thread", f"gave {f(th[(16, 1)], 1)} batches per second with one thread and {round(th[(16, 8)])} with eight")
    hi = [th[(16, w)] for w in (16, 22, 32, 44)]
    need("loader plateau", f"between {round(min(hi))} and {round(max(hi))} from 16 to 44 threads")
    need("procs", f"peaked at {round(pr[(16, 16)])} batches per second with 16 workers and fell to {round(pr[(16, 44)])} with 44")
    need("b64 real", f"real step's {f(1 / real[64]['s_per_step'], 1)}")
    t6 = p["gpu_teacher6"]["runs"][0]
    need("teacher6", f"took {f(t6['s_per_step'], 3)}~s at batch 16 against {f(g[16]['s_per_step'], 3)}~s")
    need("b16 need", f"({round(th[(16, 22)])} against {round(1 / g[16]['s_per_step'])}), yet the real step runs at {round(1 / real[16]['s_per_step'])}")


def check_error_analysis():
    e = load("error_analysis.json")
    t = e["teacher_retention"]
    need("teacher leads", f"${signed(t['teacher_lead_w00'], 4)}$ on w00 and ${signed(t['teacher_lead_ag896'], 4)}$ on ag896")
    need("retention", f"kept ${round(100 * t['S1_share_kept_w00'])}\\%$ of the teacher's lead on w00, ${round(100 * t['S1_share_kept_ag896'])}\\%$ on ag896 and ${round(100 * t['S1_share_kept_mean'])}\\%$")
    need("change corr", f"${t['S1_rank_change_corr_with_S0'][0]}$ and ${t['S1_rank_change_corr_with_S0'][1]}$ with that of S0")
    need("change corr proxy", f"${t['S1_rank_change_corr_with_teacher_proxy'][0]}$ and ${t['S1_rank_change_corr_with_teacher_proxy'][1]}$ with that of the reader average")
    b = e["S1_vs_readerv2_bootstrap_texture"]
    need("boot w00", f"${signed(b['w00'][0], 4)}$ on w00 ($95\\%$ interval ${f(b['w00'][1][0], 4)}$ to ${f(b['w00'][1][1], 4)}$)")
    need("boot ag896", f"${signed(b['ag896'][0], 4)}$ on ag896 (${f(b['ag896'][1][0], 4)}$ to ${f(b['ag896'][1][1], 4)}$)")
    n = e["near_copies"]
    need("spearman", f"${n['spearman_finetune_vs_readerv2'][0]}$ to ${n['spearman_finetune_vs_readerv2'][1]}$ for the fine-tunes")
    need("seed spearman", f"${n['spearman_seed_vs_seed_S1'][0]}$ to ${n['spearman_seed_vs_seed_S1'][1]}$ between seeds")
    need("rv2 d9v2", f"${n['spearman_readerv2_vs_d9v2_w00_ag896'][0]}$ and ${n['spearman_readerv2_vs_d9v2_w00_ag896'][1]}$ between Reader~v2 and d9v2")
    need("seed ens", f"${signed(n['seed_ensemble_minus_best_seed_mean'][0], 4)}$ to ${signed(n['seed_ensemble_minus_best_seed_mean'][1], 4)}$")
    need("lineage", f"at most ${signed(n['best_lineage_only_ensemble_gain_over_S1'], 4)}$ over S1")
    m = e["models_texture"]["rv2+d9v2 rank mean (ranks over all box px)"]
    need("rank mean", f"scores ${f(m['w00'], 4)}$ and ${f(m['ag896'], 4)}$, a mean of ${f(m['mean'], 4)}$ and a lead of ${signed(m['lead_vs_readerv2'], 4)}$")
    te = e["models_texture"]["rv2+d9x3 teacher (diag.json)"]
    need("teacher row", f"Teacher, reader ensemble & {f(te['w00'], 4)} & {f(te['ag896'], 4)} & {f(te['mean'], 4)} & ${signed(te['lead_vs_readerv2'], 4)}$")
    ep = e["ensembles_and_postprocessing"]
    fr = ep["rv2_d9v2_gain_fresh_region"]
    need("fresh pair", f"(${signed(fr[0], 4)}$, interval ${f(fr[1][0], 4)}$ to ${f(fr[1][1], 4)}$)")
    need("fresh S1", f"S1's shrinks to ${signed(b['fresh_region_old_crop_plus107_excluded']['mean'][0], 4)}$")
    need("configs", f"Of {ep['configs_searched'] // 1000}{{,}}{ep['configs_searched'] % 1000:03d} ensemble")
    assert ep["configs_reaching_0.8748"] == 0
    need("best configs", f"the best scores ${f(ep['best_in_sample_any'], 4)}$, and ${f(ep['best_in_sample_no_blur'], 4)}$ without blur")
    sf = e["shared_floor"]
    nb = sf["blocks_all_five_below_0.65"]
    need("blocks", f"In {nb['w00'] + nb['ag896']} blocks of 107 pixels ({nb['w00']} on w00, {nb['ag896']} on ag896)")
    need("pairs", f"${100 * sf['share_of_pairs'][0]:.1f}\\%$ and ${100 * sf['share_of_pairs'][1]:.1f}\\%$")
    need("deficit", f"${round(100 * sf['share_of_each_model_deficit'][0])}\\%$ to ${round(100 * sf['share_of_each_model_deficit'][1])}\\%$ of its deficit")
    rg = e["registration"]
    need("offset", f"gains ${f(rg['best_common_offset_gain_mean'][0], 4)}$ to ${f(rg['best_common_offset_gain_mean'][1], 4)}$")
    need("S1 range", f"between ${f(rg['S1_lead_range_all_registrations'][0], 4)}$ and ${f(rg['S1_lead_range_all_registrations'][1], 4)}$")
    le = e["label_edges"]
    need("ring", f"Reader~v2 to ${f(le['ring5_readerv2_S1'][0], 4)}$ and S1 to ${f(le['ring5_readerv2_S1'][1], 4)}$")
    need("ring gap", f"from ${f(le['gap_ring0_ring5'][0], 4)}$ to ${f(le['gap_ring0_ring5'][1], 4)}$")
    need("target", f"{f(e['targets']['target_plus_0.02'], 4)}")


def check_tracing():
    t = {r["cores"]: r for r in load("tracer_cores.json")["runs"]}
    need("times", f"It took {round(t[2]['trace_s'])}~s on 2 cores, {round(t[4]['trace_s'])}~s on 4 and {round(t[8]['trace_s'])}~s on 8")
    assert not t[16]["finished"]
    need("shares", f"${f(t[2]['dominant_share'], 3)}$, ${f(t[4]['dominant_share'], 3)}$ and ${f(t[8]['dominant_share'], 3)}$")
    s = load("seed_anchor.json")
    fs = s["first_step_10_generations"]
    need("seed dist", f"${s['seed_distance_voxels']['w031']}$ voxels from w031 and ${s['seed_distance_voxels']['w033']}$ from w033")
    need("first step", f"{fs['on_w033']} of {fs['vertices']} vertices, on w033, ${fs['nearest_vertex_to_seed_voxels']}$ voxels")
    g = {x["run"]: x for x in s["generations_60_threads_2"]}
    need("anchored", f"${f(g['anchored']['dominant_share'], 3)}$ share on w031 and {g['anchored']['area_on_w031_cm2']}~cm$^2$ on it, against ${f(g['unanchored']['dominant_share'], 3)}$ on w033")
    need("anchored time", f"The anchored run took {g['anchored']['trace_s']}~s against {g['unanchored']['trace_s']}~s")


def check_false404():
    d = load("false404.json")
    g = d["gets"]
    need("gets", f"{g[0]['false_404']} of {g[0]['requests']} requests with 32 workers, {g[1]['false_404']} of {g[1]['requests']} with one worker, "
                 f"{g[2]['false_404']} of {g[2]['requests']} from separate processes, none of {g[3]['requests']} on one reused connection "
                 f"and none of {g[4]['requests']} HEAD")
    r = d["w035_crop_render"]
    need("render", f"${r['zero_samples_pct']}\\%$ zero samples")
    need("render after", f"${r['after_removing_false_markers_zero_pct']:.2f}\\%$")


if __name__ == "__main__":
    for check in (check_sums, check_rounds, check_costs, check_probe, check_error_analysis, check_tracing, check_false404):
        try:
            check()
        except Exception as exc:  # a broken check is a failure, not a pass
            FAILS.append(f"{check.__name__}: {exc!r}")
    for line in FAILS:
        print("FAIL", line)
    print("all checks passed" if not FAILS else f"{len(FAILS)} checks failed")
    sys.exit(1 if FAILS else 0)
