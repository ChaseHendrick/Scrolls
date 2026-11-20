"""Open data revision 2 (16 Nov 2026) in the public readers: a superseded t1 mesh and its -t2 replacement sit side
by side, and each reader must take the current one. Offline: fake bucket listings and catalog records. Each check
fails if its reader's revision filter is dropped or turned around."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import meshaudit, sheetrefs

try:
    import numpy as np
    from kit import sentinel as sn
except ImportError:  # pragma: no cover
    np = sn = None

VOL = "20250101000000"


class Listing:
    """A fake S3 ListObjectsV2 endpoint: prefix -> folder names below it."""

    def __init__(self, tree):
        self.tree = tree

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        prefix = __import__("urllib.parse").parse.unquote(url.split("prefix=")[1].split("&")[0])
        body = "".join(f"<CommonPrefixes><Prefix>{prefix}{n}/</Prefix></CommonPrefixes>"
                       for n in self.tree.get(prefix, []))
        return io.BytesIO(f"<ListBucketResult>{body}</ListBucketResult>".encode())


class SheetrefsFindMeshes(unittest.TestCase):
    def meshes(self, names):
        seg = "S/segments/20260101000000-w001_abc/"
        tree = {"S/segments/": ["20260101000000-w001_abc"], seg + "mesh/": names}
        return sheetrefs.find_meshes(opener=Listing(tree), sample="S", volume=VOL, voxel_tag="2.4um")

    def test_t1_and_t2_side_by_side_takes_t2(self):
        for names in (["m-on-%s-2.4um.tifxyz" % VOL, "m-on-%s-2.4um-t2.tifxyz" % VOL],
                      ["m-on-%s-2.4um-t2.tifxyz" % VOL, "m-on-%s-2.4um.tifxyz" % VOL]):
            found, skipped = self.meshes(names)
            self.assertEqual(len(found), 1, skipped)
            self.assertTrue(found[0]["prefix"].rstrip("/").endswith("-2.4um-t2.tifxyz"), found[0])

    def test_t1_alone_and_other_frames(self):
        found, _ = self.meshes(["m-on-%s-2.4um.tifxyz" % VOL])
        self.assertTrue(found[0]["prefix"].rstrip("/").endswith("-2.4um.tifxyz"))
        found, skipped = self.meshes(["m-on-20240101000000-8.0um.tifxyz"])
        self.assertEqual((found, len(skipped)), ([], 1))


class MeshauditSegmentEntries(unittest.TestCase):
    def test_superseded_entries_are_left_out(self):
        new = {"path": "S/seg/mesh/m-on-%s-2.4um-t2.tifxyz/" % VOL}
        seg = {"data": [
            {"type": "layers-zarr", "origins": [{"path": "S/seg/sv/old.zarr/"}],
             "properties": {"superseded_by": {"path": "S/seg/sv/new.zarr/"}}},
            {"type": "layers-zarr", "origins": [{"path": "S/seg/sv/new.zarr/"}]},
            {"type": "tifxyz-transformed", "origins": [{"path": "S/seg/mesh/m-on-%s-2.4um.tifxyz/" % VOL}],
             "properties": {"superseded_by": new}},
            {"type": "tifxyz-transformed", "origins": [new]}]}
        sv, meshes = meshaudit.segment_entries(seg)
        self.assertEqual(sv, ["S/seg/sv/new.zarr"])
        self.assertEqual(meshes, [("tifxyz-transformed", new["path"].rstrip("/"))])


@unittest.skipIf(sn is None, "needs numpy")
class SentinelPreflightRevision(unittest.TestCase):
    def test_other_frame_warning_names_the_newest_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            seg = Path(tmp, "segment")
            for name in ("1-on-%s-2.4um.tifxyz" % VOL, "1-on-%s-2.4um-t2.tifxyz" % VOL,
                         "1-on-20240101000000-8.0um.tifxyz"):
                (seg / name).mkdir(parents=True)
                (seg / name / "meta.json").write_text(json.dumps({"bbox": [[1, 1, 1], [5, 5, 5]]}))
            vol = Path(tmp, "%s-2.4um-vol.zarr" % VOL)
            vol.mkdir()
            listing = sorted(p.name for p in seg.iterdir())
            out = sn.preflight(seg / "1-on-20240101000000-8.0um.tifxyz", vol, listing=listing)
            hint = [w for w in out["warnings"] if "mesh made in volume" in w]
            self.assertEqual(len(hint), 1, out)
            self.assertTrue(hint[0].endswith("1-on-%s-2.4um-t2.tifxyz" % VOL), hint[0])


if __name__ == "__main__":
    unittest.main()
