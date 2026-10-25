"""kit.crowdmerge on synthetic parallel sheets: the vote keeps a minority's slips off the consensus, flags them,
follows a wrong majority, and leaves a lone trace as it is."""

import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

GAP = 12.0  # voxels between the two sheets


def sheet(z, n=50, step=4.0, x0=0.0, y0=0.0):
    yy, xx = np.mgrid[0:n, 0:n] * step
    return np.stack([xx + x0, yy + y0, np.full(xx.shape, z)], -1).astype(np.float64)


def slipped(n=50, step=4.0, at=25, ramp=3):
    """A trace on z = 100 that slides onto z = 100 + GAP from column `at` over `ramp` columns."""
    P = sheet(100.0, n, step)
    w = np.clip((np.arange(n) - at) / ramp, 0, 1)[None, :]
    P[..., 2] += GAP * w
    return P


@unittest.skipUnless(HAVE, "needs numpy, scipy and tifffile")
class CrowdMergeTest(unittest.TestCase):
    def setUp(self):
        from kit import crowdmerge
        self.cm = crowdmerge
        self.ok = np.ones((50, 50), bool)

    def crowd(self, n_slip, n=5):
        out = []
        for i in range(n):
            P = slipped() if i < n_slip else sheet(100.0)
            out.append((f"t{i}", P, self.ok.copy()))
        return out

    def test_minority_slip_stays_on_sheet_and_is_flagged(self):
        traces = self.crowd(2)
        # the base is a slipped trace, so the vote has to move it back
        res = self.cm.merge(traces, base="t0")
        z = res["xyz"][res["valid"]][:, 2]
        self.assertLess(np.abs(z - 100.0).max(), 1.0)
        f = res["flags"]["t0"]
        self.assertTrue((f[:, 30:] == 2).all())
        self.assertTrue((f[:, :20] == 1).all())
        self.assertTrue((res["flags"]["t4"] != 2).all())

    def test_wrong_majority_wins(self):
        res = self.cm.merge(self.crowd(4), base="t4")
        z = res["xyz"][res["valid"]].reshape(-1, 3)
        far = z[z[:, 0] > 140]
        self.assertGreater(far[:, 2].min(), 100.0 + GAP - 1.0)
        self.assertTrue((res["flags"]["t4"][:, 35:] == 2).all())

    def test_lone_trace_is_kept(self):
        P = slipped()
        res = self.cm.merge([("only", P, self.ok)])
        self.assertTrue(res["valid"].all())
        self.assertLess(np.abs(res["xyz"] - P).max(), 1e-6)
        self.assertEqual(res["summary"]["single_trace_share"], 1.0)

    def test_grows_past_the_base(self):
        # the base covers columns 0 to 24 only; three full traces carry the consensus over the rest
        traces = self.crowd(0, 4)
        half = self.ok.copy()
        half[:, 25:] = False
        traces[0] = ("t0", traces[0][1], half)
        res = self.cm.merge(traces, base="t0")
        P = res["xyz"][res["valid"]]
        self.assertGreater(P[:, 0].max(), 180.0)
        self.assertLess(np.abs(P[:, 2] - 100.0).max(), 1.0)
        self.assertGreater(res["summary"]["grown_vertices"], 0)
        # a lone trace beyond the base is not enough to grow
        lone = self.crowd(0, 2)
        lone[0] = ("t0", lone[0][1], half)
        res = self.cm.merge(lone, base="t0")
        self.assertLess(res["xyz"][res["valid"]][:, 0].max(), 100.0)

    def test_beyond_judges_vertices_off_the_consensus(self):
        from scipy.spatial import cKDTree
        S = dict(self.cm.SETTINGS)
        dense = []
        for P in (sheet(100.0), sheet(100.0), sheet(100.0 + GAP)):
            pts = P.reshape(-1, 3)
            dense.append((pts, None, cKDTree(pts)))
        f = np.zeros((50, 50), np.uint8)
        # trace 2 (on the other sheet) against two traces on the first: a slip by majority
        self.assertEqual(self.cm.beyond(f, sheet(100.0 + GAP), self.ok, 2, dense, S), 2500)
        self.assertTrue((f == 2).all())
        g = np.zeros((50, 50), np.uint8)
        self.cm.beyond(g, sheet(100.0), self.ok, 0, dense, S)
        self.assertTrue((g == 1).all())
        # two against two is no verdict
        h = np.zeros((50, 50), np.uint8)
        self.cm.beyond(h, sheet(100.0), self.ok, 0, dense + [dense[2]], S)
        self.assertTrue((h == 0).all())
        # with weights, a reliable trace outvotes a less reliable one, even one against one
        k = np.zeros((50, 50), np.uint8)
        self.cm.beyond(k, sheet(100.0 + GAP), self.ok, 1, dense[1:], S, weights=[0.95, 0.5])
        self.assertTrue((k == 2).all())

    def test_extrapolate_continues_a_line(self):
        X = np.zeros((1, 5, 3))
        X[0, :, 0] = np.arange(5) * 2.0
        valid = np.array([[True, True, True, False, False]])
        Y, new = self.cm.extrapolate(X, valid, np.zeros_like(valid))
        self.assertEqual(new[0].tolist(), [False, False, False, True, False])
        self.assertAlmostEqual(Y[0, 3, 0], 6.0)

    def test_mean_lands_between_sheets(self):
        # the naive mean is pulled off both sheets where traces disagree
        res = self.cm.merge(self.crowd(2), base="t4", method="mean")
        z = res["xyz"][res["valid"]].reshape(-1, 3)
        far = z[z[:, 0] > 140, 2]
        self.assertGreater(np.median(far), 103.0)
        self.assertLess(np.median(far), 100.0 + GAP - 3.0)

    def test_ray_hits_and_tie_break(self):
        from scipy.spatial import cKDTree
        pts = np.array([[0.0, 0.0, 5.0], [0.0, 0.0, -5.0]])
        h = self.cm.ray_hits(np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]), cKDTree(pts), 8, 0.5)
        offs = np.arange(-8, 9)
        self.assertEqual(sorted(offs[h[0]].tolist()), [-5, 5])
        votes = np.zeros((1, 1, 17), np.float32)
        votes[0, 0, [3, 9]] = 2  # offsets -5 and +1 tie, no neighbors to break it
        self.assertEqual(offs[self.cm.choose(votes, np.ones((1, 1), bool), offs.astype(float), 1)[0, 0]], 1)

    def test_crowd_truth_and_slipping(self):
        from scipy import ndimage  # noqa: F401
        n = 60
        up = sheet(100.0, n, 2.0)
        ok = np.ones((n, n), bool)
        nA = np.zeros((n, n, 3))
        nA[..., 2] = 1.0
        s = np.full((n, n), -GAP)       # B lies GAP above A: A's offset from B along B's normal is -GAP
        s[25:35, 25:35] = -2.0          # a contact
        res = self.cm.crowd(up, ok, nA, s, ok, nA, 2.0, np.random.default_rng(1), n=4, slipping=1)
        self.assertEqual(len(res), 4)
        name, P, v, t = res[0]
        self.assertGreater(t.max(), GAP - 0.5)
        for _, _, _, t2 in res[1:]:
            self.assertEqual(float(t2.max()), 0.0)

    def test_tally_verdicts(self):
        def arm(off, matched, flags, maj=(0, 1)):
            return {"vote": {"off": off, "matched": matched, "covered": 9},
                    "mean": {"off": 50, "matched": 100, "covered": 9},
                    "largest": {"off": 40, "matched": 100}, "flags": flags, "majority_slipped": list(maj)}
        good = {"tp": 95, "fp": 2, "fn": 5, "on": 1000, "on_flagged": 2, "slipped": 100}
        row = {"window_points": 10, "main": arm(1, 100, good), "clean": arm(0, 100, good),
               "sham": arm(40, 100, good, (50, 100))}
        self.assertEqual(self.cm.tally([row])["verdict"], "PASS")
        row["sham"] = arm(1, 100, good, (50, 100))
        self.assertEqual(self.cm.tally([row])["verdict"], "VOID")

    def test_write_and_command_line(self):
        import tifffile
        from kit import cli
        with tempfile.TemporaryDirectory() as d:
            dirs = []
            for name, P, v in self.crowd(1, 3):
                p = Path(d) / name
                p.mkdir()
                for i, a in enumerate("xyz"):
                    tifffile.imwrite(str(p / f"{a}.tif"), P[..., i].astype(np.float32))
                (p / "meta.json").write_text('{"type": "seg", "format": "tifxyz", "scale": [0.05, 0.05]}')
                dirs.append(str(p))
            out = Path(d) / "out"
            rc = cli.main(["crowdmerge", "merge", *dirs, "--out", str(out), "--json"])
            self.assertEqual(rc, 0)
            z = tifffile.imread(str(out / "consensus" / "z.tif"))
            self.assertLess(np.abs(z[z > 0] - 100.0).max(), 1.0)
            self.assertEqual(int((tifffile.imread(str(out / "flags" / "t0.tif")) == 2).sum() > 0), 1)
            self.assertTrue((out / "crowdmerge.json").is_file())


if __name__ == "__main__":
    unittest.main()
