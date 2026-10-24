"""Tests for kit doctor's AMD, Intel and --remote checks, with fakes (no GPU, no rocm-smi, no RunPod needed).

rocm-smi's JSON is parsed by its own keys (ROCm rocm_smi.py: "Card Series", "VRAM Total Memory (B)"); an AMD or
Intel card reports as a warning, never a pass; ROCm installed with no card listed warns; nothing at all fails. VC3D's
cache folder is found in VC3D's own order (cache.json, VC3D.ini, /volpkgs or /ephemeral, the default), a cache.json
VC3D would refuse fails, low free space warns, and on RunPod the folder's survival follows RunPod's storage page."""

import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path

from kit import cli, doctor

ROCM_JSON = json.dumps({
    "card0": {"Card Series": "AMD Radeon RX 7900 XTX", "Card Model": "0x744c", "VRAM Total Memory (B)": "25753026560",
              "VRAM Total Used Memory (B)": "15867904"},
    "card1": {"Card Series": "AMD Instinct MI210", "VRAM Total Memory (B)": "68702699520"},
    "system": {"Driver version": "6.8.5"},
})


class Usage:
    def __init__(self, gb):
        self.free = gb * 1024**3


class TestGpus(unittest.TestCase):
    def test_parse_rocm_smi(self):
        self.assertEqual(doctor.parse_rocm_smi(ROCM_JSON),
                         [("AMD Radeon RX 7900 XTX", 24560), ("AMD Instinct MI210", 65520)])
        self.assertEqual(doctor.parse_rocm_smi("not json"), [])
        self.assertEqual(doctor.parse_rocm_smi(json.dumps({"card0": {"Card Series": "X"}})), [("X", 0)])

    def test_amd_gpus_runs_rocm_smi_only_when_present(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=ROCM_JSON)
        self.assertEqual(doctor.amd_gpus(run, which=lambda name: None), [])
        self.assertEqual(calls, [])
        self.assertEqual(len(doctor.amd_gpus(run, which=lambda name: "/usr/bin/rocm-smi")), 2)
        self.assertEqual(calls[0], ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])

        def fails(cmd, **kw):
            raise subprocess.CalledProcessError(1, cmd)
        self.assertEqual(doctor.amd_gpus(fails, which=lambda name: "rocm-smi"), [])

    def test_amd_and_intel_warn_never_pass(self):
        st, detail = doctor.check_gpu([], amd=[("AMD Radeon RX 7900 XTX", 24560)], hip="6.2.41133")
        self.assertEqual(st, doctor.WARN)
        self.assertIn("AMD GPU (ROCm): AMD Radeon RX 7900 XTX 23 GB", detail)
        self.assertIn("torch 6.2.41133 (ROCm)", detail)
        self.assertIn("NVIDIA GPU", detail)
        st, detail = doctor.check_gpu([], amd=[("small", 8192)])
        self.assertIn("Below 12 GB", detail)
        self.assertIn("not a ROCm build", detail)
        st, detail = doctor.check_gpu([], xpu=[("Intel Arc A770", 16384)])
        self.assertEqual(st, doctor.WARN)
        self.assertIn("Intel GPU (torch.xpu)", detail)
        st, detail = doctor.check_gpu([], rocm=True)
        self.assertEqual(st, doctor.WARN)
        self.assertIn("ROCm is installed", detail)
        self.assertEqual(doctor.check_gpu([])[0], doctor.FAIL)
        self.assertEqual(doctor.check_gpu([("NVIDIA A10", 23028)], amd=[("x", 1)])[0], doctor.PASS)

    def test_rocm_present(self):
        self.assertTrue(doctor.rocm_present(lambda p: p == "/dev/kfd"))
        self.assertFalse(doctor.rocm_present(lambda p: False))

    def test_torch_gpus_without_torch(self):
        out = doctor.torch_gpus()
        self.assertEqual(set(out), {"hip", "amd", "xpu"})


class TestCache(unittest.TestCase):
    def files(self, d):
        return (lambda p: str(p) in d), (lambda p: d[str(p)])

    def test_order(self):
        env = {"HOME": "/opt/u"}
        exists, read = self.files({})
        self.assertEqual(doctor.vc3d_cache_root(env, exists, read)[0], Path("/opt/u/.VC3D/remote_cache"))
        exists, read = self.files({"/ephemeral": ""})
        self.assertEqual(doctor.vc3d_cache_root(env, exists, read)[0], Path("/ephemeral/remote_cache"))
        exists, read = self.files({"/volpkgs": "", "/ephemeral": ""})
        self.assertEqual(doctor.vc3d_cache_root(env, exists, read)[0], Path("/volpkgs/remote_cache"))
        ini = "[perf]\nremote_cache_dir=/wrong\n[viewer]\n; a comment\nremote_cache_dir = \"/data/vc cache\"\n"
        exists, read = self.files({"/volpkgs": "", "/opt/u/.VC3D/VC3D.ini": ini})
        root, how = doctor.vc3d_cache_root(env, exists, read)
        self.assertEqual(root, Path("/data/vc cache"))
        self.assertIn("VC3D.ini", how)
        conf = {"/cfg/cache.json": json.dumps({"version": 1, "root": "/fast/cache"}), "/cfg/VC3D.ini": ini}
        exists, read = self.files(conf)
        self.assertEqual(doctor.vc3d_cache_root({"HOME": "/opt/u", "VC3D_CONFIG_DIR": "/cfg"}, exists, read)[0],
                         Path("/fast/cache"))

    def test_bad_cache_json_fails(self):
        for body in ('{"version": 2, "root": "/x"}', '{"version": 1, "root": "rel"}', "nope"):
            exists, read = self.files({"/h/.VC3D/cache.json": body})
            with self.assertRaises(ValueError):
                doctor.vc3d_cache_root({"HOME": "/h"}, exists, read)
            st, detail = doctor.check_cache({"HOME": "/h"}, exists, lambda p: Usage(100), read)
            self.assertEqual(st, doctor.FAIL)
            self.assertIn("cache.json", detail)

    def test_free_space_and_runpod(self):
        exists, read = self.files({"/": "", "/workspace": ""})
        st, detail = doctor.check_cache({"HOME": "/root"}, exists, lambda p: Usage(10), read)
        self.assertEqual(st, doctor.WARN)
        self.assertIn("Under 25 GB", detail)
        st, detail = doctor.check_cache({"HOME": "/root", "RUNPOD_POD_ID": "p"}, exists, lambda p: Usage(100), read)
        self.assertEqual(st, doctor.PASS)
        self.assertIn("is cleared when the Pod stops", detail)
        ini = {"/root/.VC3D/VC3D.ini": "[viewer]\nremote_cache_dir=/workspace/vc\n", "/workspace": ""}
        exists, read = self.files(ini)
        _, detail = doctor.check_cache({"HOME": "/root", "RUNPOD_POD_ID": "p"}, exists, lambda p: Usage(100), read)
        self.assertIn("survives Pod stops and restarts", detail)
        _, detail = doctor.check_cache({"HOME": "/root", "RUNPOD_POD_ID": "p", "RUNPOD_VOLUME_ID": "v"}, exists,
                                       lambda p: Usage(100), read)
        self.assertIn("network volume", detail)
        self.assertIn("--disk /workspace", detail)

    def test_cli_remote_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["doctor", "--remote", "--no-speed"])
        self.assertIn("] cache ", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["doctor", "--no-speed"])
        self.assertNotIn("] cache ", out.getvalue())


if __name__ == "__main__":
    unittest.main()
