"""Opt-in volcomp decoding (kit/vc3d_io.py volcomp_decode, used by kit/vc3d_audit.py's v3 codec chain)."""

import ctypes
import os
import unittest
from unittest import mock

from kit import vc3d_audit, vc3d_io


class FakeLib:
    """Stands in for libvolcomp: 'decodes' a chunk by repeating its first byte over 128^3 voxels."""

    def __init__(self, status=0):
        self.status = status
        self.calls = []

    def volcomp_lib_decode(self, enc, n, dst, cap):
        self.calls.append((len(enc), n, cap))
        if self.status == 0:
            ctypes.memset(dst, enc[0], cap)
        return self.status


class VolcompTest(unittest.TestCase):
    def test_without_the_library_it_says_how_to_get_one(self):
        with mock.patch.dict(os.environ, {vc3d_io.VOLCOMP_LIB_ENV: ""}):
            with self.assertRaises(vc3d_io.IOFormatError) as cm:
                vc3d_audit._v3_bytes_codecs([{"name": "volcomp", "configuration": {"q": 32}}], b"\x07abc")
        self.assertIn(vc3d_io.VOLCOMP_LIB_ENV, str(cm.exception))

    def test_the_v3_chain_decodes_volcomp_through_the_library(self):
        fake = FakeLib()
        with mock.patch.object(vc3d_io, "volcomp_lib", return_value=fake):
            out = vc3d_audit._v3_bytes_codecs([{"name": "bytes"}, {"name": "volcomp", "configuration": {"q": 32}}],
                                              b"\x07abc")
        self.assertEqual(len(out), 128 ** 3)
        self.assertEqual(set(out), {7})
        self.assertEqual(fake.calls, [(4, 4, 128 ** 3)])

    def test_a_failed_decode_is_an_error_not_zeros(self):
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.volcomp_decode(b"\x01\x02", lib=FakeLib(status=2))

    def test_decode_reports_volcomp_chunks(self):
        meta = {"zarr_format": 3, "inner": [128, 128, 128], "chunks": [512, 512, 512], "itemsize": 1,
                "inner_codecs": [{"name": "volcomp", "configuration": {"q": 32}}], "codecs": []}
        with mock.patch.object(vc3d_io, "volcomp_lib", return_value=FakeLib()):
            ok, detail = vc3d_audit.decode(meta, b"\x05xyz", inner=True)
        self.assertTrue(ok, detail)

    @unittest.skipUnless(os.environ.get(vc3d_io.VOLCOMP_LIB_ENV), "KIT_VOLCOMP_LIB not set")
    def test_real_library_round_trip_lossless(self):
        lib = vc3d_io.volcomp_lib()
        lib.volcomp_lib_encode_bound.restype = ctypes.c_size_t
        cap = lib.volcomp_lib_encode_bound()
        src = bytes((i * 7 + (i >> 14)) % 251 for i in range(128 ** 3))
        dst = ctypes.create_string_buffer(cap)
        n = ctypes.c_size_t()
        lib.volcomp_lib_encode.argtypes = [ctypes.c_char_p, ctypes.c_float, ctypes.c_void_p, ctypes.c_size_t,
                                           ctypes.POINTER(ctypes.c_size_t)]
        self.assertEqual(lib.volcomp_lib_encode(src, 0.0, dst, cap, ctypes.byref(n)), 0)
        self.assertEqual(vc3d_io.volcomp_decode(dst.raw[:n.value]), src)


if __name__ == "__main__":
    unittest.main()
