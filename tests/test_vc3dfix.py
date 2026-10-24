"""kit s3relay and kit vc3dcache (kit/vc3dfix.py) against a local S3-like server that answers false 404s."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import cli, vc3d_cache, vc3dfix  # noqa: E402

# A stand-in for a VC3D tool: it records its argv, reads one chunk through the URL it was given (a false 404 there
# would have been cached as empty), and writes the two markers VC3D could have left: one for a chunk the bucket
# holds (false) and one for a chunk it does not (true).
CHILD = r'''
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from kit import vc3d_cache
url, out = sys.argv[1], Path(sys.argv[2])
opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
data = opener(url + "/0/0/0/0", timeout=30).read()
vdir = vc3d_cache.volume_dir(url)
for rel in ("level_0/0/0/0.empty", "level_0/1/1/1.empty"):
    (vdir / rel).parent.mkdir(parents=True, exist_ok=True)
    (vdir / rel).write_text("")
out.write_text(json.dumps({"argv": sys.argv[1:], "bytes": len(data)}))
'''


def value(z, y, x):
    return (z + y + x) % 251


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.bucket = self.d / "bucket"
        fakes.write_group(self.bucket / "vol.zarr", (32, 32, 32), value, chunk=(16, 16, 16))
        (self.bucket / "vol.zarr" / "0" / "1" / "1" / "1").unlink()       # a chunk the bucket does not hold
        self.env = fakes.env_for(self.d / "home", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        self.root = self.d / "home" / "remote_cache"
        self.ledger = self.d / "ledger"
        self.opener = fakes.no_proxy_opener()
        self.env_patch = unittest.mock.patch.dict(os.environ, {"VC3D_CONFIG_DIR": self.env["VC3D_CONFIG_DIR"]})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()


class TestForms(unittest.TestCase):
    def test_spellings_of_one_bucket_url(self):
        f = vc3dfix.forms("s3://vesuvius-challenge-open-data/PHerc0139/v.zarr/")
        self.assertIn("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/v.zarr", f)
        self.assertIn("https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0139/v.zarr", f)
        self.assertEqual(vc3dfix.forms("http://127.0.0.1:9/v.zarr"), ["http://127.0.0.1:9/v.zarr"])

    def test_swap_replaces_every_spelling_and_counts(self):
        args = ["vc_render_tifxyz", "--volume", "s3://vesuvius-challenge-open-data/P/v.zarr",
                "--other=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/P/v.zarr/0", "keep"]
        out, n = vc3dfix.swap(args, "s3://vesuvius-challenge-open-data/P/v.zarr", "http://127.0.0.1:1/P/v.zarr")
        self.assertEqual(n, 2)
        self.assertEqual(out[2], "http://127.0.0.1:1/P/v.zarr")
        self.assertEqual(out[3], "--other=http://127.0.0.1:1/P/v.zarr/0")
        self.assertEqual(out[4], "keep")


class TestRelayRun(Base):
    def test_command_gets_the_relay_url_and_false_marker_is_found(self):
        child = self.d / "child.py"
        child.write_text(CHILD)
        out = self.d / "child.json"
        with fakes.S3LikeServer(self.bucket, false=1) as srv:
            url = f"{srv.url}/vol.zarr"
            r = vc3dfix.run_through(url, [sys.executable, str(child), url, str(out), str(fakes.ROOT)],
                                    ledger=self.ledger, env=self.env, opener=self.opener, say=lambda s: None)
        got = json.loads(out.read_text())
        self.assertEqual(r["swapped"], 1)
        self.assertNotEqual(got["argv"][0], url)                   # the child never saw the bucket URL
        self.assertEqual(got["argv"][0], r["relay_url"])
        self.assertEqual(got["bytes"], 16 ** 3)                      # the first false 404 was asked again
        self.assertGreaterEqual(r["stats"]["false_404"], 1)
        self.assertEqual(r["returncode"], 0)
        self.assertEqual(r["affected"], ["level_0/0/0/0.empty"])     # the false marker, not the true one
        vdir = vc3d_cache.volume_dir(r["relay_url"], root=self.root)
        self.assertFalse((vdir / "level_0/0/0/0.empty").exists())
        self.assertTrue((vdir / "level_0/1/1/1.empty").exists())

    def test_cli_exit_code_four_when_a_run_may_have_read_zeros(self):
        child = self.d / "child.py"
        child.write_text(CHILD)
        with fakes.S3LikeServer(self.bucket, false=1) as srv:
            url = f"{srv.url}/vol.zarr"
            real = vc3dfix.run_through
            with unittest.mock.patch.object(vc3dfix, "run_through", lambda *a, **k: real(
                    *a, **{**k, "env": self.env, "opener": self.opener})):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(["s3relay", url, "--ledger", str(self.ledger), "--json", "--",
                                     sys.executable, str(child), url, str(self.d / "c.json"), str(fakes.ROOT)])
        self.assertEqual(code, vc3dfix.AFFECTED_EXIT)


class TestCacheCheck(Base):
    def plant(self, given):
        vdir = vc3d_cache.volume_dir(given, root=self.root)
        for rel in ("level_0/0/0/0.empty", "level_0/1/1/1.empty"):
            (vdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (vdir / rel).write_text("")
        return vdir

    def test_relay_folder_is_found_and_repaired(self):
        with fakes.S3LikeServer(self.bucket, false=1) as srv:
            url = f"{srv.url}/vol.zarr"
            from kit import s3relay
            vdir = self.plant(s3relay.candidate_urls(url)[3])         # VC3D read it through a relay on a later port
            r = vc3dfix.check_cache(url, root=self.root, ledger=self.ledger, opener=self.opener)
        self.assertEqual(r["false_found"], 1)
        self.assertEqual(r["false_deleted"], 1)
        self.assertFalse((vdir / "level_0/0/0/0.empty").exists())
        self.assertTrue((vdir / "level_0/1/1/1.empty").exists())

    def test_no_delete_only_reports(self):
        with fakes.S3LikeServer(self.bucket, false=1) as srv:
            url = f"{srv.url}/vol.zarr"
            vdir = self.plant(url)
            r = vc3dfix.check_cache(url, delete=False, root=self.root, ledger=self.ledger, opener=self.opener)
        self.assertEqual((r["false_found"], r["false_deleted"]), (1, 0))
        self.assertTrue((vdir / "level_0/0/0/0.empty").exists())

    def test_cache_json_vc3d_would_refuse_stops_both_commands(self):
        Path(self.env["VC3D_CONFIG_DIR"], "cache.json").write_text('{"version": 2, "root": "/c"}')
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["vc3dcache", "http://127.0.0.1:9/v.zarr"]), 2)
            self.assertEqual(cli.main(["vc3dcache", "--all"]), 2)
            self.assertEqual(cli.main(["s3relay", "http://127.0.0.1:9/v.zarr", "--", sys.executable, "-c", "0"]), 2)
        self.assertIn("needs version 1 and an absolute root", err.getvalue())

    def test_list_counts_markers(self):
        self.plant("http://127.0.0.1:9/elsewhere.zarr")
        r = vc3dfix.list_cache(self.root, self.ledger)
        self.assertEqual([v["markers"] for v in r["volumes"]], [2])


class TestServe(unittest.TestCase):
    def test_serve_prints_the_url_to_give_vc3d(self):
        lines = []
        r = vc3dfix.serve("s3://vesuvius-challenge-open-data/PHerc0139/v.zarr", seconds=0.05, say=lines.append)
        self.assertTrue(r["relay_url"].startswith("http://127.0.0.1:"))
        self.assertTrue(r["relay_url"].endswith("/PHerc0139/v.zarr"))
        self.assertIn(f"give VC3D this URL: {r['relay_url']}", lines)

    def test_bad_url_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["s3relay", "ftp://x/y"]), 2)
            self.assertEqual(cli.main(["vc3dcache"]), 2)


if __name__ == "__main__":
    unittest.main()
