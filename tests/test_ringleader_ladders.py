"""scripts/ringleader/ladders.py: Ringleader's sure pieces as villa relative-winding ladders.

Synthetic slices only. A spiral's outward position P (in turns) puts a pixel at angle 2 pi P about the axis and
radius r0 + dr P; its turn is floor(P). Pieces are runs of 40 pixels inside one turn; continuity edges join
consecutive pieces (shift 1 across the start ray), radial samples join a pixel to the one a turn outward. A block
of pieces given a wrong label must be marked bad and kept out of the ladder, with its neighbors up to the sure
distance; every other piece keeps its true turn up to one offset, points are ordered by theta', and the plus-one
control must change every step. Ringleader solves each connected component of its graph on its own offset, so a
slice drawn as two components (`island`) must give a ladder of one of them only. Skipped without numpy and scipy.
"""

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ringleader"))

try:
    import numpy as np
    import scipy  # noqa: F401
    import ladders
except ImportError:          # pragma: no cover
    ladders = None


def synthetic(n_turns=8, per_turn=1200, piece=40, wrong=(), offset=5, hand=1, island=None, island_offset=37):
    """One slice as a Ringleader zNNNNN.npz dict; `wrong` lists pieces whose label is raised by one. With `island`,
    the pieces from that one outward are a second connected component (no edge joins the two) whose labels sit on
    another offset, as Ringleader leaves them: every label there is `island_offset` too large."""
    P = 3.0 + (np.arange(n_turns * per_turn) + 0.5) / per_turn
    T = np.floor(P).astype(np.int64)
    theta = 2 * math.pi * (P - T)
    r = 100.0 + 25.0 * P
    xs = np.rint(2000 + r * np.cos(theta)).astype(np.int64)
    ys = np.rint(2000 + r * np.sin(theta)).astype(np.int64)
    pid = np.zeros(len(P), np.int64)
    k, cnt, prev = 0, 0, T[0]
    for i in range(len(P)):
        if T[i] != prev or cnt == piece:
            k, cnt, prev = k + 1, 0, T[i]
        pid[i] = k
        cnt += 1
    npc = k + 1
    plabel = np.zeros(npc, np.int64)
    for q in range(npc):
        plabel[q] = T[pid == q][0] + offset
    for q in wrong:
        plabel[q] += 1
    out = np.arange(npc) >= (npc if island is None else island)      # the pieces of the second component
    plabel[out] += island_offset
    label = plabel[pid].astype(float)
    cont = []
    for q in range(npc - 1):
        if out[q] != out[q + 1]:
            continue
        a, b = np.flatnonzero(pid == q)[-1], np.flatnonzero(pid == q + 1)[0]
        cont.append((q, q + 1, int(T[b] - T[a])))
    rows = np.stack([np.arange(0, len(P) - per_turn, 17), np.arange(0, len(P) - per_turn, 17) + per_turn], 1)
    rows = rows[out[pid[rows[:, 0]]] == out[pid[rows[:, 1]]]]
    return {"ys": ys, "xs": xs, "label": label, "pid": pid, "theta_p": theta, "r": r, "hand": np.int64(hand),
            "comp": out[pid].astype(np.int64), "rows": rows.astype(np.int64),
            "cont": np.asarray(cont, np.int64).reshape(-1, 3)}, T, plabel


IDENT = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]


@unittest.skipIf(ladders is None, "needs numpy and scipy")
class LaddersTest(unittest.TestCase):
    def test_sure_rule_keeps_wrong_pieces_out(self):
        d, T, plabel = synthetic(wrong=(60, 61, 62))
        sure, has_px, dist, bad, lp = ladders.sure_mask(d)
        self.assertTrue(bad[60] and bad[62])
        self.assertFalse(sure[60] or sure[61] or sure[62])
        self.assertTrue(np.isfinite(dist).any())
        self.assertGreater(sure.sum(), 0.8 * len(sure))
        # every sure piece carries its true turn plus one constant
        for q in np.flatnonzero(sure):
            self.assertEqual(lp[q] - T[d["pid"] == q][0], 5)

    def test_clean_slice_is_all_sure(self):
        d, _, _ = synthetic()
        sure, _, dist, bad, _ = ladders.sure_mask(d)
        self.assertFalse(bad.any())
        self.assertTrue(sure.all())
        self.assertTrue(np.isinf(dist).all())

    def test_ladder_points_and_order(self):
        d, T, _ = synthetic(wrong=(30,))
        doc, rec = ladders.build_e({2000: d}, ladders.Frame(IDENT, 1.0))
        self.assertEqual(doc["vc_pointcollections_json_version"], "1")
        col = doc["collections"]["1"]
        self.assertFalse(col["metadata"]["winding_is_absolute"])
        ids = sorted(col["points"], key=int)
        w = [col["points"][i]["wind_a"] for i in ids]
        self.assertEqual(min(w), 0.0)
        self.assertEqual(len(set(w)), 8)                    # eight turns, relative to the innermost sure one
        th = [math.atan2(col["points"][i]["p"][1] - 2000, col["points"][i]["p"][0] - 2000) % (2 * math.pi)
              for i in ids]
        self.assertLess(max(abs(a - b) for a, b in zip(th, sorted(th))), 0.05)     # numbered by theta' ascending
        self.assertLessEqual(rec["slices"]["2000"]["points"], 8 * rec["slices"]["2000"]["sure"])
        self.assertLess(rec["slices"]["2000"]["max_theta_gap"], math.pi)
        # a point's wind_a is its piece's true turn minus the innermost turn
        for i in ids:
            x, y, z = col["points"][i]["p"]
            self.assertEqual(z, 2000.0)

    def test_frame_maps_points(self):
        d, _, _ = synthetic()
        M = [[2, 0, 0, 10], [0, 2, 0, 20], [0, 0, 2, 30]]
        a, _ = ladders.build_e({100: d}, ladders.Frame(IDENT, 1.0))
        b, _ = ladders.build_e({100: d}, ladders.Frame(M, 4.0))
        pa = [p["p"] for p in a["collections"]["1"]["points"].values()]
        pb = [p["p"] for p in b["collections"]["1"]["points"].values()]
        for u, v in zip(pa, pb):
            self.assertAlmostEqual(v[0], (2 * u[0] + 10) / 4, places=3)
            self.assertAlmostEqual(v[2], (2 * u[2] + 30) / 4, places=3)

    def test_plus_one_control_changes_every_step(self):
        d, _, _ = synthetic()
        e, _ = ladders.build_e({7: d}, ladders.Frame(IDENT, 1.0))
        q = ladders.plus_one_levels(e)
        lv_e = sorted({p["wind_a"] for p in e["collections"]["1"]["points"].values()})
        lv_q = sorted({p["wind_a"] for p in q["collections"]["1"]["points"].values()})
        self.assertEqual(lv_e, [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(lv_q, [0, 2, 4, 6, 8, 10, 12, 14])
        self.assertEqual(q["kit"]["control"], "plus_one")
        self.assertTrue(q["collections"]["1"]["name"].startswith("ringleader-Q-"))

    def test_grow_adds_agreeing_pieces_only(self):
        d, T, plabel = synthetic(wrong=(60, 61, 62))
        frame = ladders.Frame(IDENT, 1.0)
        e, _ = ladders.build_e({50: d}, frame)
        conv = dict(d)
        fit = (T + 9).astype(float)                    # a taught fit that has every turn right, offset 9 - 5 = 4
        conv["label"] = fit
        conv["hand"] = np.int64(1)
        g, rec = ladders.build_g({50: d}, {50: conv}, frame, e)
        s = rec["slices"]["50"]
        self.assertEqual(s["offset"], 4.0)
        # the wrongly labeled pieces disagree with the fit and stay out; their unsure neighbors come back
        self.assertGreater(s["agree"], 0)
        self.assertEqual(s["agree"], s["uncertified"] - 3)
        self.assertGreater(rec["points"], sum(len(c["points"]) for c in e["collections"].values()))

    def test_grow_refuses_other_geometry(self):
        d, _, _ = synthetic()
        frame = ladders.Frame(IDENT, 1.0)
        e, _ = ladders.build_e({50: d}, frame)
        other, _, _ = synthetic(wrong=(10,))
        with self.assertRaises(ladders.LadderError):
            ladders.build_g({50: other}, {50: d}, frame, e)

    def test_only_the_main_component_is_written(self):
        """Two components, no edge between them, every label consistent inside its component: every piece is sure,
        and the outer component's labels are 37 windings off. The ladder holds the larger component only."""
        d, T, _ = synthetic(island=160)                      # 240 pieces: 160 inside, 80 on the island
        sure, _, _, bad, lp = ladders.sure_mask(d)
        self.assertFalse(bad.any())
        self.assertTrue(sure.all())                          # the sure rule alone cannot tell the island apart
        written, same, component, ncomp = ladders.main_component(d, sure)
        self.assertEqual((component, ncomp, int(written.sum()), int(same.sum())), (0, 2, 160, 160))
        doc, rec = ladders.build_e({9: d}, ladders.Frame(IDENT, 1.0))
        s = rec["slices"]["9"]
        self.assertEqual((s["sure"], s["written"], s["sure_left_out"], s["components_with_sure"], s["component"]),
                         (240, 160, 80, 2, 0))
        self.assertEqual(rec["sure_left_out"], 80)
        self.assertEqual(rec["components"], "main")
        col = doc["collections"]["1"]
        self.assertEqual(col["metadata"]["component"], 0)
        # every written point carries its true turn minus the innermost turn: no level is 37 off
        turn_of = {}
        for q in np.flatnonzero(written):
            for i in np.flatnonzero(d["pid"] == q):
                turn_of[(float(d["xs"][i]), float(d["ys"][i]))] = int(T[i])
        for p in col["points"].values():
            self.assertEqual(p["wind_a"], turn_of[(p["p"][0], p["p"][1])] - int(T.min()))
        self.assertLess(max(p["wind_a"] for p in col["points"].values()), 8)

    def test_all_components_is_the_rule_up_to_1_1_0(self):
        d, T, _ = synthetic(island=160)
        frame = ladders.Frame(IDENT, 1.0)
        new, _ = ladders.build_e({9: d}, frame)
        old, rec = ladders.build_e({9: d}, frame, all_components=True)
        self.assertEqual(rec["components"], "all")
        self.assertNotIn("sure_left_out", rec)
        self.assertNotIn("component", old["collections"]["1"]["metadata"])
        w_old = [p["wind_a"] for p in old["collections"]["1"]["points"].values()]
        self.assertGreater(len(w_old), len(new["collections"]["1"]["points"]))
        self.assertGreater(max(w_old), 37)                   # the island's points sit on its own offset: wrong
        # the new ladder is the old walk without the island's points, with the same levels
        def walk(doc):
            return [tuple(p["p"]) for _, p in sorted(doc["collections"]["1"]["points"].items(),
                                                     key=lambda kv: int(kv[0]))]
        pos_old, pos_new = walk(old), walk(new)
        it = iter(pos_old)
        self.assertTrue(all(any(q == p for q in it) for p in pos_new))

    def test_component_with_the_most_sure_pieces_and_ties(self):
        d, _, _ = synthetic(island=60)                       # 60 inside, 180 on the island: the island is larger
        sure = ladders.sure_mask(d)[0]
        written, same, component, ncomp = ladders.main_component(d, sure)
        self.assertEqual((component, int(written.sum())), (1, 180))
        # a wrong block inside the island takes sure pieces from it; the count is of sure pieces, not of pieces
        d2, _, _ = synthetic(island=100, wrong=tuple(range(110, 236, 6)))
        sure2 = ladders.sure_mask(d2)[0]
        self.assertGreater(100, int(sure2[100:].sum()))
        self.assertEqual(ladders.main_component(d2, sure2)[2], 0)
        d3, _, _ = synthetic(island=120)                     # 120 and 120: the smallest component number wins
        self.assertEqual(ladders.main_component(d3, ladders.sure_mask(d3)[0])[2], 0)

    def test_a_file_without_comp_is_refused(self):
        d, _, _ = synthetic()
        del d["comp"]
        frame = ladders.Frame(IDENT, 1.0)
        with self.assertRaises(ladders.LadderError) as cm:
            ladders.build_e({50: d}, frame)
        self.assertIn("z 50", str(cm.exception))
        self.assertIn("comp", str(cm.exception))
        doc, _ = ladders.build_e({50: d}, frame, all_components=True)       # the old rule never read comp
        self.assertEqual(len(doc["collections"]), 1)

    def test_grow_stays_inside_the_component(self):
        """Round 2 adds an uncertified piece only from the written component. Here the other component's offset
        happens to equal the main one's, so each of its pieces agrees with the fit under the slice's offset; it is
        still another component, its agreement is chance, and it stays out."""
        d, T, plabel = synthetic(island=160, island_offset=0, wrong=(60, 61, 62))
        frame = ladders.Frame(IDENT, 1.0)
        e, _ = ladders.build_e({50: d}, frame)
        conv = dict(d)
        conv["label"] = (T + 9).astype(float)                # the fit has every turn right; offset 4
        conv["hand"] = np.int64(1)
        sure = ladders.sure_mask(d)[0]
        self.assertTrue(sure[160:].all())
        g, rec = ladders.build_g({50: d}, {50: conv}, frame, e)
        s = rec["slices"]["50"]
        self.assertEqual(s["offset"], 4.0)
        self.assertEqual((s["written"], s["sure_left_out"]), (int(sure[:160].sum()), 80))
        self.assertEqual(s["uncertified"], int((~sure[:160]).sum()))     # no piece of the island is a candidate
        self.assertEqual(s["agree"], s["uncertified"] - 3)   # only the three wrong pieces disagree
        island_px = {(float(x), float(y)) for x, y, q in zip(d["xs"], d["ys"], d["pid"]) if q >= 160}
        main_px = {(float(x), float(y)) for x, y, q in zip(d["xs"], d["ys"], d["pid"]) if q < 160}
        got = {(pt["p"][0], pt["p"][1]) for pt in g["collections"]["1"]["points"].values()}
        self.assertFalse(got & (island_px - main_px))
        # under the old rule the island's pieces are in
        e_old, _ = ladders.build_e({50: d}, frame, all_components=True)
        g_old, _ = ladders.build_g({50: d}, {50: conv}, frame, e_old, all_components=True)
        got_old = {(pt["p"][0], pt["p"][1]) for pt in g_old["collections"]["1"]["points"].values()}
        self.assertTrue(got_old & (island_px - main_px))
        with self.assertRaises(ladders.LadderError):         # round 1 and round 2 must use one rule
            ladders.build_g({50: d}, {50: conv}, frame, e_old)

    def test_command_line(self):
        d, _, _ = synthetic(wrong=(40,))
        with tempfile.TemporaryDirectory() as td:
            geo = Path(td) / "run"
            geo.mkdir()
            np.savez_compressed(geo / "z01000.npz", **d)
            np.savez_compressed(geo / "z01004.npz", **d)
            m = Path(td) / "m.json"
            m.write_text(json.dumps({"matrix": IDENT}))
            out = Path(td) / "lad"
            r = subprocess.run([sys.executable, str(REPO / "scripts" / "ringleader" / "ladders.py"), "ladders",
                                "--geo", str(geo), "--out", str(out), "--matrix", str(m), "--fit-scale", "1",
                                "--control"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads((out / "relative_windings.json").read_text())
            self.assertEqual(len(doc["collections"]), 2)
            self.assertTrue((out / "relative_windings_control.json").is_file())
            rec = json.loads((out / "ladders.json").read_text())
            self.assertEqual(rec["version"], ladders.VERSION)
            self.assertEqual((rec["components"], rec["sure_left_out"]), ("main", 0))
            old = Path(td) / "old"
            r = subprocess.run([sys.executable, str(REPO / "scripts" / "ringleader" / "ladders.py"), "ladders",
                                "--geo", str(geo), "--out", str(old), "--matrix", str(m), "--fit-scale", "1",
                                "--all-components"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads((old / "ladders.json").read_text())["components"], "all")
            r = subprocess.run([sys.executable, str(REPO / "scripts" / "ringleader" / "ladders.py"), "ladders",
                                "--geo", str(geo), "--out", str(out), "--matrix", str(m), "--exclude-z", "1002:1010"],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
