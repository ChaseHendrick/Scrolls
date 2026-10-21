"""kit/causal.py and kit/runrecord.py are shared code: byte-identical in Scrolls and Scrolls-private, like
kit/stale.py. This test pins their sha256 in both repositories, so a change lands in both or fails here. Where the
repository keeps private registries (Modal approvals, freezes, the Modal ledger), it also checks that neither
shared file names a private approval, freeze or Modal app id. With SCROLLS_PUBLIC_ROOT set to a sibling checkout,
it reports (never fails on) a difference from that checkout's copies.

Keep this file byte-identical in Scrolls and Scrolls-private.
"""

import hashlib
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ("kit/causal.py", "kit/runrecord.py")
# Update both repositories' copies of this test together with the shared files (docs/tools/causal.md, Tests).
SHARED_SHA256 = {
    "kit/causal.py": "7a28dc5803e0dbcc84dce4b99adddb0714d50971cf69d7946ae0a4e05132d887",
    "kit/runrecord.py": "0573bf584d3d28c80b50f35efc8ef14460455f60f2d30b8e77543dce308459e5",
}


def _sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


class SharedFilesTest(unittest.TestCase):
    def test_pinned_bytes(self):
        for rel in SHARED:
            with self.subTest(rel=rel):
                self.assertEqual(_sha(rel), SHARED_SHA256[rel],
                                 f"{rel} changed: land the same bytes in Scrolls and Scrolls-private and update "
                                 "SHARED_SHA256 in both copies of tests/test_causal_shared.py")

    def test_no_private_ids_in_shared_code(self):
        deny = set()
        for rel, key in (("docs/compute/modal-approvals.json", "approvals"), ("docs/compute/freezes.json", "freezes")):
            path = ROOT / rel
            if path.is_file():
                deny |= {x["id"] for x in json.loads(path.read_text(encoding="utf-8")).get(key) or []
                         if isinstance(x, dict) and isinstance(x.get("id"), str) and len(x["id"]) > 3}
        ledger = ROOT / "docs/compute/modal-ledger.csv"
        if ledger.is_file():
            deny |= set(re.findall(r"ap-[A-Za-z0-9]{20,}", ledger.read_text(encoding="utf-8")))
        if not deny:
            self.skipTest("no private registries in this repository")
        for rel in SHARED:
            text = (ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(rel=rel):
                self.assertEqual(sorted(x for x in deny if x in text), [])

    def test_sibling_copy(self):
        other = os.environ.get("SCROLLS_PUBLIC_ROOT")
        if not other:
            self.skipTest("SCROLLS_PUBLIC_ROOT is not set")
        for rel in SHARED:
            path = Path(other) / rel
            if path.is_file() and path.read_bytes() != (ROOT / rel).read_bytes():
                print(f"info: {rel} differs from {path}")


if __name__ == "__main__":
    unittest.main()
