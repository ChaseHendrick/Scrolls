"""integrations/vc3d/ap_vc3d.py without VC3D or AutoPipeline: a stand-in scrolls-kit, a stand-in plugin host
(tests/vc3d_plugin_host.py) and a stand-in VC3D agent bridge on a Unix socket.

Covers: planning from a point on a catalog volume and every refusal; the digest check and the one-run rule of start;
load copying only accepted surfaces and writing VC3D's point collection format; the plugin manifests passing the
host's rules and running end to end through it; open calling only the bridge methods VC3D offers; reading the point
from VC3D's state; bridge discovery. With VILLA_ROOT set, the host's rules are compared with villa's docs/plugins.md.
"""

import importlib.util
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import vc3d_plugin_host as host  # noqa: E402

spec = importlib.util.spec_from_file_location("ap_vc3d", ROOT / "integrations" / "vc3d" / "ap_vc3d.py")
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

URL = ("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/"
       "20250821151531-9.366um-1.2m-113keV-masked.zarr/")

FAKE_KIT = r'''#!PYTHON
"""Stand-in for scrolls-kit autopipeline plan and run."""
import hashlib, json, os, sys, time
from pathlib import Path
home = Path(os.environ["FAKE_KIT_HOME"])
with open(home / "calls.log", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
cmd = sys.argv[1:]
if cmd[:2] == ["autopipeline", "plan"]:
    sample, settings = cmd[2], json.loads(cmd[cmd.index("--settings") + 1])
    if "bad" in settings:
        print("unknown plan setting bad", file=sys.stderr)
        sys.exit(2)
    digest = hashlib.sha256(json.dumps([sample, settings], sort_keys=True).encode()).hexdigest()
    out = home / "work" / "autopipe" / f"{sample}-{settings['volume']}-{digest[:10]}"
    out.mkdir(parents=True, exist_ok=True)
    url = f"https://example.org/{sample}/volumes/{settings['volume']}-x.zarr/"
    (out / "plan.json").write_text(json.dumps({"settings": settings, "digest": digest,
                                               "resolved": {"volume_url": url}}))
    print(json.dumps({"plan": str(out / "plan.json"), "digest": digest, "out": str(out),
                      "resolved": {"volume_url": url}}))
elif cmd[:2] == ["autopipeline", "run"]:
    out = Path(cmd[2])
    time.sleep(float(os.environ.get("FAKE_KIT_SLEEP", "0")))
    surfaces = {}
    for sid, ok in (("t00", True), ("t01", False)):
        d = out / "traces" / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text("{}")
        (d / "x.tif").write_bytes(b"x")
        surfaces[sid] = {"surface": str(d), "accepted": ok}
    plan = json.loads((out / "plan.json").read_text())
    pts = plan["settings"]["seeds"]["points"]
    (out / "seeds.json").write_text(json.dumps({"seeds": [{"xyz": p} for p in pts]}))
    (out / "state.json").write_text(json.dumps({"surfaces": surfaces, "stages": {}}))
else:
    sys.exit(3)
'''


def short_tmp():
    base = "/tmp" if os.path.isdir("/tmp") else None
    return tempfile.mkdtemp(prefix="apv", dir=base)


class FakeBridge:
    """VC3D's agent bridge: newline-delimited JSON-RPC 2.0 on a Unix socket, answering a few methods."""

    def __init__(self, path, methods, state=None):
        self.path, self.methods, self.state, self.calls, self.fail = path, methods, state or {}, [], set()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(8)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                if not buf:
                    continue
                msg = json.loads(buf.decode())
                self.calls.append((msg["method"], msg.get("params")))
                if msg["method"] == "rpc.describe":
                    res = {"methods": {m: {} for m in self.methods}}
                elif msg["method"] == "state.get":
                    res = self.state
                elif msg["method"] in self.methods and msg["method"] not in self.fail:
                    res = {"ok": True}
                else:
                    reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no method"}}
                    conn.sendall((json.dumps(reply) + "\n").encode())
                    continue
                conn.sendall((json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}) + "\n").encode())

    def close(self):
        self.sock.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(short_tmp())
        self.kit_home = self.tmp / "kit"
        self.kit_home.mkdir()
        self.kit = self.tmp / "scrolls-kit"
        self.kit.write_text(FAKE_KIT.replace("PYTHON", sys.executable))
        self.kit.chmod(0o755)
        env = {"AP_VC3D_HOME": str(self.tmp / "aphome"), "FAKE_KIT_HOME": str(self.kit_home),
               "AP_KIT": str(self.kit), "FAKE_KIT_SLEEP": "0"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ap(self, *argv):
        out = self.tmp / "stdout.txt"
        with open(out, "w") as fh, mock.patch.object(sys, "stdout", fh), mock.patch.object(sys, "stderr", fh):
            code = ap.main(list(argv))
        return code, out.read_text()

    def calls(self):
        f = self.kit_home / "calls.log"
        return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []

    def plan(self, point="10,20,30"):
        code, text = self.ap("here", "--point", point, "--volume", URL, "--json")
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def finished_run(self):
        rec = self.plan()
        code, text = self.ap("start", "--json")
        self.assertEqual(code, 0, text)
        self.wait_for(Path(rec["out"]) / "state.json")
        return rec

    def wait_for(self, path, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            if path.exists():
                time.sleep(0.2)
                return
            time.sleep(0.05)
        self.fail(f"{path} did not appear")


class Here(Base):
    def test_plans_the_catalog_scan_with_the_point_as_the_seed(self):
        rec = self.plan("3960,3700.5,9500")
        call = self.calls()[-1]
        self.assertEqual(call[:3], ["autopipeline", "plan", "PHerc0841"])
        settings = json.loads(call[call.index("--settings") + 1])
        self.assertEqual(settings["volume"], "20250821151531")
        self.assertEqual(settings["seeds"]["points"], [[3960.0, 3700.5, 9500.0]])
        last = json.loads((Path(os.environ["AP_VC3D_HOME"]) / "last.json").read_text())
        self.assertEqual(last["digest"], rec["digest"])
        self.assertIn("start --run", rec["start_command"])

    def test_keeps_other_settings(self):
        code, text = self.ap("here", "--point", "1,2,3", "--volume", URL, "--settings",
                             '{"trace": {"repeats": 2}, "seeds": {"count": 1}}', "--json")
        self.assertEqual(code, 0, text)
        settings = json.loads(self.calls()[-1][-1])
        self.assertEqual(settings["trace"], {"repeats": 2})
        self.assertEqual(settings["seeds"], {"count": 1, "points": [[1.0, 2.0, 3.0]]})

    def test_refusals(self):
        cases = [
            (["--point", "1,2", "--volume", URL], "the point must be x,y,z"),
            (["--point", "1,-2,3", "--volume", URL], "the point must be x,y,z"),
            (["--point", "1,nan,3", "--volume", URL], "the point must be x,y,z"),
            (["--point", "1,2,3", "--volume", "/data/my-scan.zarr"], "is not an open-data catalog volume"),
            (["--point", "1,2,3", "--volume", URL, "--settings", "[1]"], "must be a JSON object"),
            (["--point", "1,2,3", "--volume", URL, "--settings", "{"], "the settings are not JSON"),
            (["--point", "1,2,3", "--volume", URL, "--settings", '{"segment": "0841-w00"}'], "replaces the seed point"),
            (["--point", "1,2,3", "--volume", URL, "--settings", '{"seeds": {"points": [[1,1,1]]}}'],
             "is filled from the VC3D point"),
            (["--point", "1,2,3", "--volume", URL, "--settings", '{"volume": "20230101000000"}'],
             "differs from the volume open in VC3D"),
            (["--point", "1,2,3", "--volume", URL, "--settings", '{"bad": 1}'], "autopipeline plan exited 2"),
            (["--volume", URL], "give --point and --volume"),
        ]
        for argv, message in cases:
            with self.subTest(argv=argv):
                code, text = self.ap("here", *argv)
                self.assertEqual(code, 2, text)
                self.assertIn(message, text)

    def test_no_kit_command(self):
        with mock.patch.dict(os.environ, {"AP_KIT": "", "PATH": str(self.tmp / "empty")}):
            code, text = self.ap("here", "--point", "1,2,3", "--volume", URL)
        self.assertEqual(code, 2)
        self.assertIn("no scrolls-kit command", text)

    def test_summary_file_for_vc3d(self):
        out = self.tmp / "run" / "plan.txt"
        code, _ = self.ap("here", "--point", "1,2,3", "--volume", URL, "--summary", str(out))
        self.assertEqual(code, 0)
        self.assertIn("Nothing was computed or launched", out.read_text())


class Start(Base):
    def test_wrong_or_short_digest_is_refused(self):
        self.plan()
        for digest in ("0123456789abcdef", "abc"):
            code, text = self.ap("start", "--digest", digest)
            self.assertEqual(code, 2)
            self.assertIn("plan again with ap_vc3d.py here", text)
        self.assertFalse(any(c[:2] == ["autopipeline", "run"] for c in self.calls()))

    def test_starts_once_in_the_background(self):
        os.environ["FAKE_KIT_SLEEP"] = "3"
        rec = self.plan()
        t0 = time.time()
        code, text = self.ap("start", "--digest", rec["digest"][:12], "--json")
        self.assertEqual(code, 0, text)
        self.assertLess(time.time() - t0, 2.5, "start must return before the run ends")
        started = json.loads(text)
        code, text = self.ap("start")
        self.assertEqual(code, 2)
        self.assertIn("is already going", text)
        self.wait_for(Path(rec["out"]) / "state.json")
        self.assertEqual(started["digest"], rec["digest"])
        time.sleep(0.3)

    def test_unknown_folder(self):
        code, text = self.ap("start", "--run", str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("has no plan.json", text)

    def test_nothing_planned_yet(self):
        code, text = self.ap("start")
        self.assertEqual(code, 2)
        self.assertIn("no plan made here yet", text)


class Load(Base):
    def test_copies_only_accepted_surfaces_and_writes_vc3d_points(self):
        rec = self.finished_run()
        dest = self.tmp / "load"
        code, text = self.ap("load", "--dest", str(dest), "--json")
        self.assertEqual(code, 0, text)
        out = json.loads(text)
        segs = sorted(p.name for p in (dest / "segments").iterdir())
        self.assertEqual(segs, [f"ap-{rec['digest'][:10]}-t00"])
        self.assertTrue((dest / "segments" / segs[0] / "meta.json").is_file())
        self.assertEqual(out["skipped"][0]["surface"], "t01")
        doc = json.loads((dest / "seeds.json").read_text())
        self.assertEqual(doc["vc_pointcollections_json_version"], "1")
        self.assertEqual(doc["collections"]["1"]["points"]["1"]["p"], [10.0, 20.0, 30.0])
        self.assertIn("model output, not a reading", json.loads((dest / "load.json").read_text())["note"])

    def test_refuses_before_the_run_made_anything(self):
        self.plan()
        code, text = self.ap("load", "--dest", str(self.tmp / "load"), "--need", "segments")
        self.assertEqual(code, 2)
        self.assertIn("has no accepted surface yet", text)


class Manifests(Base):
    def install(self, *extra):
        folder = self.tmp / "plugins"
        code, text = self.ap("manifests", "--install", str(folder), *extra)
        return folder, code, text

    def test_manifests_pass_the_host_rules(self):
        folder, code, text = self.install()
        self.assertEqual(code, 0, text)
        files = sorted(folder.iterdir())
        self.assertEqual([f.name for f in files], ["autopipeline-here.json", "autopipeline-seeds.json",
                                                   "autopipeline-start.json", "autopipeline-surfaces.json"])
        for f in files:
            m = host.parse(f.read_text(), f)
            self.assertTrue(Path(m["program"]).is_absolute())
            if "--kit" in m["args"]:
                self.assertEqual(m["args"][m["args"].index("--kit") + 1], str(self.kit.resolve()))

    def test_install_refuses_to_overwrite_an_edited_manifest(self):
        folder, code, _ = self.install()
        self.assertEqual(self.install()[1], 0, "the same files again is fine")
        f = folder / "autopipeline-here.json"
        f.write_text(f.read_text().replace("Plan an AutoPipeline run here", "Edited"))
        _, code, text = self.install()
        self.assertEqual(code, 2)
        self.assertIn("exists and differs", text)
        self.assertEqual(self.install("--force")[1], 0)

    def test_the_host_rules_catch_bad_manifests(self):
        good = ap.manifests("/usr/bin/scrolls-kit")[0]
        bad = [dict(good, extra=1), dict(good, program="{volume}"), dict(good, id="a b"),
               dict(good, args=["{nope}"]), dict(good, args=["{input:missing}"]),
               dict(good, result={"kind": "file", "path": "/etc/passwd"}),
               dict(good, result={"kind": "file", "path": "{output}/../x"}), dict(good, result={"kind": "mesh"})]
        for doc in bad:
            with self.subTest(doc=doc):
                with self.assertRaises(host.ManifestError):
                    host.parse(json.dumps(doc))

    def test_plugins_run_end_to_end_through_the_host(self):
        folder, code, _ = self.install()
        self.assertEqual(code, 0)
        load = {f.stem: host.parse(f.read_text(), f) for f in folder.iterdir()}
        runs = self.tmp / "plugin-runs"
        ctx = {"point": [3960.0, 3700.25, 9500.0], "volume": URL, "volume_id": "masked"}
        proc, result = host.run(load["autopipeline-here"], ctx, runs / "here")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Plan digest:", result.read_text())
        settings = json.loads(self.calls()[-1][self.calls()[-1].index("--settings") + 1])
        self.assertEqual(settings["seeds"]["points"], [[3960.0, 3700.25, 9500.0]])
        proc, result = host.run(load["autopipeline-start"], ctx, runs / "start")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        last = json.loads((Path(os.environ["AP_VC3D_HOME"]) / "last.json").read_text())
        self.wait_for(Path(last["out"]) / "state.json")
        proc, result = host.run(load["autopipeline-surfaces"], ctx, runs / "surfaces")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([p.name for p in result.iterdir()], [f"ap-{last['digest'][:10]}-t00"])
        proc, result = host.run(load["autopipeline-seeds"], ctx, runs / "seeds")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(result.read_text())["vc_pointcollections_json_version"], "1")

    def test_a_point_that_is_missing_stops_the_host(self):
        folder, _, _ = self.install()
        m = host.parse((folder / "autopipeline-here.json").read_text(), folder / "autopipeline-here.json")
        with self.assertRaises(host.ManifestError):
            host.run(m, {"volume": URL}, self.tmp / "runs" / "x")


class Bridge(Base):
    def bridge(self, methods, state=None):
        b = FakeBridge(str(self.tmp / "b.sock"), methods, state)
        self.addCleanup(b.close)
        return b

    def test_open_calls_only_offered_methods_in_order(self):
        rec = self.finished_run()
        b = self.bridge(["volume.attach", "segments.attach", "points.load_json"])
        code, text = self.ap("open", "--socket", b.path, "--json")
        self.assertEqual(code, 0, text)
        out = json.loads(text)
        self.assertEqual([c[0] for c in b.calls], ["rpc.describe", "volume.attach", "segments.attach",
                                                    "points.load_json"])
        self.assertEqual(b.calls[1][1]["location"], f"https://example.org/PHerc0841/volumes/20250821151531-x.zarr/")
        self.assertTrue(b.calls[2][1]["location"].endswith("segments"))
        skipped = [s for s in out["bridge_calls"] if not s["done"]]
        self.assertEqual([s["method"] for s in skipped], ["viewer.center_on_point"])
        self.assertIn(rec["digest"][:16], b.calls[2][1]["location"])

    def test_here_reads_the_point_and_volume_from_vc3d(self):
        state = {"volume": {"id": "v", "path": URL}, "focusPoi": {"position": {"x": 5, "y": 6.5, "z": 7}}}
        b = self.bridge([], state)
        code, text = self.ap("here", "--bridge", "--socket", b.path, "--json")
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(text)["point_xyz"], [5.0, 6.5, 7.0])

    def test_here_without_a_focus_point(self):
        b = self.bridge([], {"volume": {"path": URL}, "focusPoi": None})
        code, text = self.ap("here", "--bridge", "--socket", b.path)
        self.assertEqual(code, 2)
        self.assertIn("VC3D has no focus point", text)

    def test_a_refused_bridge_call_stops_open(self):
        self.finished_run()
        b = self.bridge(["volume.attach", "segments.attach"])
        b.fail = {"segments.attach"}
        code, text = self.ap("open", "--socket", b.path)
        self.assertEqual(code, 2)
        self.assertIn("VC3D refused segments.attach", text)

    def test_discovery_takes_the_newest_live_record(self):
        reg = self.tmp / "registry"
        reg.mkdir()
        (reg / "dead.json").write_text(json.dumps({"pid": 2 ** 22 + 12345, "path": "/dead", "startedAt": 9e9}))
        (reg / "old.json").write_text(json.dumps({"pid": os.getpid(), "path": "/old", "startedAt": 1.0}))
        (reg / "new.json").write_text(json.dumps({"pid": os.getpid(), "path": "/new", "startedAt": 2.0}))
        (reg / "junk.json").write_text("{")
        self.assertEqual(ap.bridge_socket(registry=reg), "/new")
        with self.assertRaises(ap.Refusal):
            ap.bridge_socket(registry=self.tmp / "none")

    def test_no_bridge_running(self):
        with mock.patch.object(Path, "home", return_value=self.tmp):
            code, text = self.ap("here", "--bridge")
        self.assertEqual(code, 2)
        self.assertIn("no running VC3D bridge", text)


@unittest.skipUnless(os.environ.get("VILLA_ROOT"), "set VILLA_ROOT to a villa checkout with VC3D's plugin host")
class AgainstVilla(unittest.TestCase):
    def test_host_rules_match_villa_docs(self):
        doc = Path(os.environ["VILLA_ROOT"]) / "volume-cartographer" / "docs" / "plugins.md"
        if not doc.is_file():
            self.skipTest(f"{doc} is not there: this villa has no plugin host yet")
        text = doc.read_text(encoding="utf-8")
        placeholders = set(re.findall(r"^\| `\{([a-z_]+)\}`", text, flags=re.M))
        placeholders |= set(re.findall(r"`\{(point_[xyz])\}`", text))
        self.assertEqual(placeholders, host.CONTEXT)
        kinds = set(re.findall(r"^\| `([a-z_]+)` \| (?!yes|no)", text, flags=re.M)) - {"kind"}
        self.assertEqual(kinds, host.KINDS)
        keys = set(re.findall(r"^\| `([a-z]+)` \| (?:yes|no) \|", text, flags=re.M))
        keys |= {"description", "homepage", "license"}
        self.assertEqual(keys, host.KEYS)
        self.assertIn(f'"schema": "{host.SCHEMA}"', text)


if __name__ == "__main__":
    unittest.main()
