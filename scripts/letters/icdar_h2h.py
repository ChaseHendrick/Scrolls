#!/usr/bin/env python3
"""Fresh letter and line test on the ICDAR 2023 Iliad papyrus photographs (model-free build).

The ICDAR 2023 Competition on Detection and Recognition of Greek Letters on Papyri (Zenodo record 13825619,
doi 10.5281/zenodo.13825619, CC BY-NC 4.0; photographs under their holders' licences as the COCO file lists them)
ships expert letter boxes for 152 training photographs (108 texts) and, in 2c.Answers, for its 37 test
photographs (34 texts). No reader in this repository has been scored on either part: letters-v2-real trained on
the training photographs, letters-v2-ccby and its fine-tunes used no ICDAR data, and Hell-Char ConvNeXt-V2 (R1)
trained on Hell-Char only. The test texts share no Trismegistos number with Hell-Char's 144 papyri and no text
folder with the ICDAR training part (checked by `build`, recorded in build.json).

`build` reads only the boxes, their labels and the photographs' pixels. It runs no reader. It writes, under WORK:

  test/letters.json   one record per scored box: id, unit (text folder), image, bbox, letter (24 capitals)
  test/lines.json     lines grouped from the boxes by the fixed rule in `group_lines`, each with its reference
                      string and whether it passes the Iliad check (`iliad_check`)
  test/crops/*.png    the gray box crop (scored letters) and the gray line strip (lines), as stored
  dev/...             the same for the training part, for choices made before the test is read
  build.json          counts, the overlap check, sha256 of every manifest and of the zip

The rule, the arms and the decision rule are in docs/prereg/2026-10-24-letter-reader-icdar-h2h.md.

  python scripts/letters/icdar_h2h.py build --zip ICDAR.zip --hellchar hellchar.csv --iliad iliad.xml --work W
"""
import argparse
import hashlib
import io
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ZIP_SHA = "f86b7aaf0697e82042a0d042d8626cfbd4d13ea9644cede5bc57edf2b7af3e97"
ZIP_MD5 = "115645f6864bb922d60309687fcfaa56"
ROOT = "ICDAR2023_Competition_on_Detection_and_Recognition_of_Greek_Letters_on_Papyri_Dataset/"
TRAIN_JSON = ROOT + "2a.Training/HomerCompTraining.json"
TRAIN_IMG = ROOT + "2a.Training/"          # + file_name without "./"
ANSWERS_JSON = ROOT + "2c.Answers/AnswersToTesting.json"
TEST_IMG = ROOT + "2b.Testing/images/"     # + img_url after "images/homer2/"

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
MIN_LINE = 5            # letters in a scored line
LINE_PAD_Y = 0.15       # line strip padding, times the image's median box height
LINE_PAD_X = 0.25
ILIAD_MAX_ERR = 0.20    # a line passes the Iliad check at edit distance <= this share of its length
ANCHOR = 5
INK_T = 5.0             # ink_gate: paired t of box ink against half-line-shifted copies


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def to_capital(ch):
    """One ICDAR category name to one of the 24 capitals, or None ('.', '?', anything else)."""
    s = unicodedata.normalize("NFD", ch)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = s.replace("Ϲ", "Σ").replace("ϲ".upper(), "Σ")
    return s if len(s) == 1 and s in ALPHABET else None


def norm_text(s):
    """Greek text to scriptio continua over the 24 capitals (accents, breathings, spaces and marks dropped)."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper().replace("Ϲ", "Σ")
    return "".join(c for c in s if c in ALPHABET)


def iliad_stream(xml_path):
    """The Iliad (Perseus tlg0012.tlg001, perseus-grc2) as one string of capitals, verse after verse."""
    t = Path(xml_path).read_text(encoding="utf-8")
    body = t.split("<body>", 1)[-1]
    body = re.sub(r"<note.*?</note>", " ", body, flags=re.S)
    lines = re.findall(r"<l\b[^>]*>(.*?)</l>", body, flags=re.S)
    return "".join(norm_text(re.sub(r"<[^>]+>", " ", x)) for x in lines)


class IliadIndex:
    def __init__(self, stream, k=ANCHOR):
        self.s, self.k = stream, k
        self.idx = defaultdict(list)
        for i in range(len(stream) - k + 1):
            self.idx[stream[i:i + k]].append(i)

    def best(self, q, max_hits=200):
        """Smallest edit distance of q to any substring of the stream near an exact k-gram anchor, and where."""
        n, k = len(q), self.k
        starts = set()
        for off in range(0, max(1, n - k + 1)):
            hits = self.idx.get(q[off:off + k], ())
            if len(hits) > max_hits:
                continue
            for p in hits:
                starts.add(p - off)
        best = (n, None)
        for st in sorted(starts):
            a, b = max(0, st - 3), min(len(self.s), st + n + 3)
            d = semiglobal(q, self.s[a:b])
            if d < best[0]:
                best = (d, a)
        return best


def semiglobal(q, t):
    """Edit distance of all of q to its best-matching substring of t (free start and end in t)."""
    prev = np.zeros(len(t) + 1, int)
    for i, c in enumerate(q, 1):
        cur = np.empty_like(prev)
        cur[0] = i
        for j, d in enumerate(t, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (c != d))
        prev = cur
    return int(prev.min())


def group_lines(boxes):
    """Lines from one image's boxes, by a rule fixed before any read.

    Two boxes link when their vertical extents overlap by at least half the smaller height, their centres are
    within half the image's median box height of each other vertically, and the horizontal gap between them is
    at most one median height. A line is a connected component, read left to right by box centre. A component
    in which two boxes overlap horizontally by more than half the narrower width (stacked letters: two lines
    joined) is marked ambiguous and not scored. Returns [(ordered box indices, ambiguous)]."""
    n = len(boxes)
    if n == 0:
        return []
    H = float(np.median([b[3] for b in boxes]))
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for i in range(n):
        xi, yi, wi, hi = boxes[i]
        for j in range(i + 1, n):
            xj, yj, wj, hj = boxes[j]
            ov = min(yi + hi, yj + hj) - max(yi, yj)
            if ov < 0.5 * min(hi, hj):
                continue
            if abs((yi + hi / 2) - (yj + hj / 2)) > 0.5 * H:
                continue
            gap = max(xi, xj) - min(xi + wi, xj + wj)
            if gap > 1.0 * H:
                continue
            par[find(i)] = find(j)
    comp = defaultdict(list)
    for i in range(n):
        comp[find(i)].append(i)
    out = []
    for members in comp.values():
        members.sort(key=lambda i: (boxes[i][0] + boxes[i][2] / 2, i))
        amb = False
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                p, q = boxes[members[a]], boxes[members[b]]
                hov = min(p[0] + p[2], q[0] + q[2]) - max(p[0], q[0])
                if hov > 0.5 * min(p[2], q[2]):
                    amb = True
                    break
            if amb:
                break
        out.append((members, amb))
    out.sort(key=lambda m: (min(boxes[i][1] for i in m[0]), min(boxes[i][0] for i in m[0])))
    return out


def ink_gate(g, bx):
    """Do the boxes sit on ink? Paired over boxes: mean gray of each box minus the mean of the same box moved
    up and down by half the image's median box height (the gaps between lines are bare papyrus). The pairing
    passes when ink is darker by a paired t of at least INK_T. Model-free; no label is used."""
    Hh, Ww = g.shape
    H = float(np.median([b[3] for b in bx]))
    d = []
    for x, y, w, h in bx:
        x0, y0, x1, y1 = clip_box(x, y, x + w, y + h, Ww, Hh)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        inside = g[y0:y1, x0:x1].mean()
        out = []
        for dy in (-0.5 * H, 0.5 * H):
            a0, b0, a1, b1 = clip_box(x, y + dy, x + w, y + dy + h, Ww, Hh)
            if a1 - a0 >= 2 and b1 - b0 >= 2:
                out.append(g[b0:b1, a0:a1].mean())
        if out:
            d.append(float(np.mean(out) - inside))
    d = np.array(d)
    t = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0
    return {"boxes": int(len(d)), "mean_darker": round(float(d.mean()), 3) if len(d) else None,
            "t": round(t, 2), "pass": t >= INK_T}


def gray_of(img_bytes):
    """Gray pixels in the stored orientation (the boxes refer to it; EXIF rotation is not applied)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None          # some photographs are over 50 Mpx
    return np.asarray(Image.open(io.BytesIO(img_bytes)).convert("L"))


def clip_box(x0, y0, x1, y1, W, H):
    return max(0, int(round(x0))), max(0, int(round(y0))), min(W, int(round(x1))), min(H, int(round(y1)))


def save_png(arr, path):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(arr, np.uint8), mode="L").save(path, optimize=False, compress_level=6)


def collect(coco, part):
    """[(image record, [annotations])] with one annotation per seg_id (the documented doubles share one)."""
    cats = {c["id"]: c["name"] for c in coco["categories"]}
    by_img = defaultdict(list)
    seen = set()
    dropped = Counter()
    for a in sorted(coco["annotations"], key=lambda a: a["id"]):
        if a.get("seg_id") in seen:
            dropped["double"] += 1
            continue
        seen.add(a.get("seg_id"))
        L = to_capital(cats.get(a["category_id"], ""))
        if L is None:
            dropped["not_a_letter:" + cats.get(a["category_id"], "?")] += 1
            continue
        x, y, w, h = a["bbox"]
        if w < 4 or h < 4:
            dropped["under_4px"] += 1
            continue
        by_img[a["image_id"]].append(dict(a, letter=L))
    imgs = {i["id"]: i for i in coco["images"]}
    if part == "test":
        # 2c.Answers numbers its annotations' image_id in another scheme than its "images" list (3, 35, 38, ...
        # against 3, 4, 6, ...; checked 24 October 2026). Its 37 annotation image ids, ascending, follow the
        # 37 entries of "images" in list order: every group's box extents then fit its photograph (36 of 37
        # inside, one 9 px over the edge; the boxes are clipped), and `ink_gate` checks each pairing on pixels.
        ann_ids = sorted(by_img)
        order = [i["id"] for i in coco["images"]]
        if len(ann_ids) != len(order):
            raise SystemExit(f"answers: {len(ann_ids)} annotation image ids, {len(order)} images")
        return [(imgs[im], by_img[g]) for g, im in zip(ann_ids, order)], dropped
    return [(imgs[k], by_img[k]) for k in sorted(by_img)], dropped


def image_member(rec, part):
    if part == "test":
        rel = rec["img_url"].split("images/homer2/", 1)[1]
        return TEST_IMG + rel, rel.split("/")[0]
    rel = rec["file_name"].lstrip("./")
    return TRAIN_IMG + rel, rel.split("/")[2]


def build_part(zf, coco, part, out, iliad, dropped_note):
    groups, dropped = collect(coco, part)
    letters, lines, gates = [], [], []
    names = set(zf.namelist())
    for rec, anns in groups:
        member, unit = image_member(rec, part)
        if member not in names:
            dropped["photograph_not_in_zip"] += 1
            dropped["letters_on_absent_photographs"] += len(anns)
            gates.append({"image": rec["id"], "unit": unit, "absent": True})
            continue
        try:
            g = gray_of(zf.read(member))
        except OSError:                       # two training photographs are truncated JPEG files
            dropped["photograph_unreadable"] += 1
            dropped["letters_on_unreadable_photographs"] += len(anns)
            gates.append({"image": rec["id"], "unit": unit, "unreadable": True})
            continue
        Hh, Ww = g.shape
        if (Ww, Hh) != (rec["width"], rec["height"]):
            dropped["size_mismatch_images"] += 1
        bx = [a["bbox"] for a in anns]
        gate = ink_gate(g, bx)
        gates.append(dict(gate, image=rec["id"], unit=unit, file=member.rsplit("/", 1)[-1]))
        if not gate["pass"]:
            dropped["photographs_failing_ink_gate"] += 1
            dropped["letters_on_failing_photographs"] += len(anns)
            continue
        for a in anns:
            x, y, w, h = a["bbox"]
            x0, y0, x1, y1 = clip_box(x, y, x + w, y + h, Ww, Hh)
            if x1 - x0 < 4 or y1 - y0 < 4:
                dropped["clipped_small"] += 1
                continue
            bid = f"{part[0]}{a['id']}"
            save_png(g[y0:y1, x0:x1], out / "crops" / f"{bid}.png")
            letters.append({"id": bid, "unit": unit, "image": rec["id"], "bbox": [x0, y0, x1, y1],
                            "letter": a["letter"]})
        Hm = float(np.median([b[3] for b in bx]))
        for k, (members, amb) in enumerate(group_lines(bx)):
            if len(members) < MIN_LINE:
                continue
            ref = "".join(anns[i]["letter"] for i in members)
            x0 = min(bx[i][0] for i in members) - LINE_PAD_X * Hm
            x1 = max(bx[i][0] + bx[i][2] for i in members) + LINE_PAD_X * Hm
            y0 = min(bx[i][1] for i in members) - LINE_PAD_Y * Hm
            y1 = max(bx[i][1] + bx[i][3] for i in members) + LINE_PAD_Y * Hm
            x0, y0, x1, y1 = clip_box(x0, y0, x1, y1, Ww, Hh)
            d, at = iliad.best(ref)
            lid = f"{part[0]}L{rec['id']}_{k:03d}"
            ok = (not amb) and d <= ILIAD_MAX_ERR * len(ref)
            if ok:
                save_png(g[y0:y1, x0:x1], out / "crops" / f"{lid}.png")
            lines.append({"id": lid, "unit": unit, "image": rec["id"], "strip": [x0, y0, x1, y1],
                          "boxes": [f"{part[0]}{anns[i]['id']}" for i in members], "ref": ref,
                          "box_height": Hm, "ambiguous": amb, "iliad_edits": d, "iliad_at": at, "scored": ok})
    write_json(out / "letters.json", letters)
    write_json(out / "lines.json", lines)
    crops = sorted((out / "crops").glob("*.png"))
    man = "".join(f"{sha256_file(p)}  {p.name}\n" for p in crops)
    (out / "crops.sha256").write_text(man)
    scored = [L for L in lines if L["scored"]]
    return {
        "photographs": len(groups), "ink_gate": gates, "units": len({L["unit"] for L in letters}), "letters": len(letters),
        "letter_counts": dict(sorted(Counter(L["letter"] for L in letters).items())),
        "dropped": dict(sorted(dropped.items())),
        "lines_candidate": len(lines), "lines_ambiguous": sum(L["ambiguous"] for L in lines),
        "lines_scored": len(scored), "line_letters_scored": sum(len(L["ref"]) for L in scored),
        "line_units": len({L["unit"] for L in scored}),
        "sha256": {"letters.json": sha256_file(out / "letters.json"), "lines.json": sha256_file(out / "lines.json"),
                   "crops.sha256": sha256_bytes(man.encode())},
    }


def cmd_build(a):
    work = Path(a.work)
    zsha = sha256_file(a.zip)
    if zsha != ZIP_SHA:
        raise SystemExit(f"{a.zip}: sha256 {zsha}, not the pinned {ZIP_SHA}")
    zf = zipfile.ZipFile(a.zip)
    train = json.loads(zf.read(TRAIN_JSON))
    test = json.loads(zf.read(ANSWERS_JSON))
    import csv
    hc_tm = {r["TM"].strip() for r in csv.DictReader(open(a.hellchar, newline="", encoding="utf-8"))}
    test_tm = {t["tm"].strip() for t in test["texts"]}
    train_txt = {i["file_name"].lstrip("./").split("/")[2] for i in train["images"]}
    test_txt = {i["img_url"].split("images/homer2/", 1)[1].split("/")[0] for i in test["images"]}
    overlap = {"test_tm_in_hellchar": sorted(test_tm & hc_tm), "test_text_in_icdar_training": sorted(test_txt & train_txt),
               "test_texts": len(test_txt), "test_tm": len(test_tm), "hellchar_tm": len(hc_tm)}
    if overlap["test_tm_in_hellchar"] or overlap["test_text_in_icdar_training"]:
        raise SystemExit(f"overlap: {overlap}")
    iliad = IliadIndex(iliad_stream(a.iliad))
    rec = {"zip_sha256": zsha, "zip_md5": ZIP_MD5, "iliad_xml_sha256": sha256_file(a.iliad),
           "iliad_letters": len(iliad.s), "hellchar_csv_sha256": sha256_file(a.hellchar), "overlap": overlap,
           "rule": {"min_line": MIN_LINE, "line_pad_y": LINE_PAD_Y, "line_pad_x": LINE_PAD_X,
                    "iliad_max_err": ILIAD_MAX_ERR, "anchor": ANCHOR}}
    rec["test"] = build_part(zf, test, "test", work / "test", iliad, None)
    if not a.skip_dev:
        rec["dev"] = build_part(zf, train, "dev", work / "dev", iliad, None)
    write_json(work / "build.json", rec)
    print(json.dumps({k: v for k, v in rec.items() if k in ("overlap",)}, ensure_ascii=False))
    for part in ("test", "dev"):
        if part in rec:
            r = rec[part]
            print(part, "ink gate failures:", [x for x in r["ink_gate"] if not x.get("pass")])
            print(part, {k: r[k] for k in ("photographs", "units", "letters", "lines_candidate", "lines_ambiguous",
                                           "lines_scored", "line_letters_scored", "line_units")})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="model-free build of the test and dev sets")
    b.add_argument("--zip", required=True)
    b.add_argument("--hellchar", required=True, help="hellchar.csv at Hell-Char commit aeef8466")
    b.add_argument("--iliad", required=True, help="Perseus tlg0012.tlg001.perseus-grc2.xml")
    b.add_argument("--work", required=True)
    b.add_argument("--skip-dev", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "build":
        cmd_build(a)


if __name__ == "__main__":
    main()
