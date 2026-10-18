"""Real Greek letterforms for the line reader: letter crops from papyrus photographs, turned into
ink-high glyphs that letterdata.py composes into lines and degrades like any synthetic line.

Training recipe: docs/letter-reader.md, Train your own. The prototype read synthetic letters well and drawn PHerc. 172
letters badly, so the gap is letterform realism; these crops are hands written on papyrus by scribes.

Sources (public; downloaded by hand, never committed):
- Hell-Char (Pavlopoulos et al., arXiv 2606.24984, github.com/ipavlopoulos/diachronic-greek-letterforms,
  CC BY 4.0): 13,046 single-letter crops from 144 securely dated papyri, 310 to 3 BCE, 24 letter classes
  plus 32 "Unknown". hellchar.csv has filename, letter (English name), TM (Trismegistos id), year, region.
- ICDAR 2023 Competition on Detection and Recognition of Greek Letters on Papyri (Zenodo,
  doi 10.5281/zenodo.13825619, CC BY-NC 4.0): photographs of Iliad papyri with COCO-style letter boxes
  (HomerCompTraining.json and the answers for the test images).

A glyph is the crop's ink (darker than its papyrus) scaled so that the median height of its papyrus's
plain letters is BANK_H px. Papyri, not crops, are split into train and val, so a val line never shows a
hand seen in training. Nothing here reads a Herculaneum papyrus.

  python scripts/letters/realforms.py build bank.npz --hellchar REPO/data/hellchar [--icdar DIR [--icdar-optional]]
  python scripts/letters/realforms.py stats bank.npz
  python scripts/letters/realforms.py preview bank.npz out.png [--n 12]
"""
import argparse
import csv
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import letterdata as L  # noqa: E402

ALPHABET = L.ALPHABET
NAMES = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau "
         "upsilon phi chi psi omega").split()
BANK_H = 48                 # px: median plain-letter height of each papyrus after scaling (H_PX * SS)
PLAIN = set("ΑΒΓΔΕΗΙΚΛΜΝΠϹΤΩ")   # letters that sit between the top and base lines in a bookhand
VAL_MOD = 10                # papyri whose id hashes to 0 mod VAL_MOD are val


def letter_of(name):
    """A category name (English 'Sigma', Greek 'σ', 'ς', 'Ϲ', accented forms) to an ALPHABET letter or None."""
    s = str(name).strip()
    if s.lower() in NAMES:
        return ALPHABET[NAMES.index(s.lower())]
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    if len(s) != 1:
        return None
    if s in "σςϲΣϹ":
        return "Ϲ"
    u = s.upper()
    return u if u in ALPHABET else None


def is_val(papyrus):
    """Hell-Char papyri hashing to 0 mod VAL_MOD. ICDAR photographs carry no manuscript id, so several of
    one manuscript could fall on both sides of a split: they all train, and val lines stay on Hell-Char's
    held-out papyri (the same 21 as the CPU check)."""
    p = str(papyrus)
    return not p.startswith("icdar:") and int(hashlib.sha1(p.encode()).hexdigest(), 16) % VAL_MOD == 0


def ink_from_photo(img):
    """Gray or RGB uint8 crop of dark ink on lighter papyrus -> float32 ink in [0, 1], or None if flat."""
    g = np.asarray(img, dtype=np.float32)
    if g.ndim == 3:
        g = g[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    g = g / 255.0
    bg, lo = np.percentile(g, [80, 2])
    if bg - lo < 0.08:
        return None
    t = np.clip(((bg - g) / (bg - lo) - 0.3) / 0.55, 0, 1)   # papyrus texture below 0.3 of the range goes
    return (t * t * (3 - 2 * t)).astype(np.float32)           # to 0, the ink core to 1 (smoothstep)


def hellchar_items(root):
    """(papyrus id, letter, PIL image) for every crop of a known letter under a Hell-Char data folder."""
    from PIL import Image
    root = Path(root)
    csvs = sorted(root.glob("*.csv"))
    csvf = next((c for c in csvs if c.name == "hellchar.csv"), csvs[0] if csvs else None)
    if csvf is None:
        raise SystemExit(f"no CSV in {root}")
    clip = root / "cliplets"
    with open(csvf, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ch = letter_of(r.get("letter", ""))
            p = clip / r.get("filename", "")
            if ch is None or not p.is_file():
                continue
            with Image.open(p) as im:
                yield "hellchar:" + str(r.get("TM", "?")), ch, im.convert("L")


def icdar_items(root, errors=None, counts=None):
    """(papyrus id, letter, PIL image) for every COCO letter box in JSON files under root.

    A photograph is found by its file_name path (folders included) or, when that basename is unique under
    root, by name alone; its size must match the record's width and height, read as stored or after the
    EXIF rotation. Boxes are clipped to the photograph. With an errors list, a JSON file whose layout the
    reader cannot walk, a photograph that will not open or does not fit its record and a box that will not
    parse are each skipped and described there, so one bad part does not cost the rest; without it, the
    first such error is raised. counts, if given, gathers what was passed over quietly."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None          # whole papyrus photographs can exceed Pillow's default guard
    root = Path(root)
    counts = {} if counts is None else counts

    def skip(what, exc):
        if errors is None:
            raise exc
        errors.append(f"{what}: {exc!r}")

    def note(key):
        counts[key] = counts.get(key, 0) + 1

    by_name = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff") and not p.name.startswith("._"):
            by_name.setdefault(p.name.lower(), []).append(p)

    def find(file_name):
        parts = [q.lower() for q in Path(str(file_name).replace("\\", "/")).parts if q not in (".", "/")]
        cands = by_name.get(parts[-1], []) if parts else []
        exact = [c for c in cands if [q.lower() for q in c.relative_to(root).parts][-len(parts):] == parts]
        return exact[0] if len(exact) == 1 else (cands[0] if len(cands) == 1 else None)

    seen = set()
    for js in sorted(root.rglob("*.json")):
        try:
            d = json.loads(js.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            note("json_unreadable")
            continue
        if not isinstance(d, dict) or not d.get("annotations") or not d.get("images"):
            continue
        try:
            cats = {c["id"]: letter_of(c.get("name", "")) for c in d.get("categories", [])}
            by_img = {}
            for a in d["annotations"]:
                by_img.setdefault(a.get("image_id"), []).append(a)
            pages = [(str(im.get("file_name", "")), im.get("id"), im.get("width"), im.get("height"))
                     for im in d["images"]]
        except Exception as exc:          # a layout this reader does not know
            skip(js.name, exc)
            continue
        for file_name, iid, want_w, want_h in pages:
            name = Path(file_name).name
            try:
                if iid not in by_img:
                    continue
                path = find(file_name)
                if path is None:
                    note("photographs_not_found")
                    continue
                if path in seen:
                    continue
                seen.add(path)
                with Image.open(path) as raw:
                    page = raw
                    if want_w and want_h and raw.size != (int(want_w), int(want_h)):
                        page = ImageOps.exif_transpose(raw)
                        if page.size != (int(want_w), int(want_h)):
                            raise ValueError(f"size {raw.size} does not match the record's {(want_w, want_h)}")
                    page = page.convert("L")
            except Exception as exc:      # an unhashable id, an unreadable photograph, a size mismatch
                skip(name or js.name, exc)
                continue
            pap = "icdar:" + path.relative_to(root).with_suffix("").as_posix()
            for a in by_img[iid]:
                try:
                    ch = cats.get(a.get("category_id"))
                    x, y, w, h = (float(v) for v in a.get("bbox", (0, 0, 0, 0)))
                    box = (max(0, int(x)), max(0, int(y)), min(page.width, int(x + w)), min(page.height, int(y + h)))
                except Exception as exc:
                    skip(f"{name} box {a.get('id') if isinstance(a, dict) else a!r}", exc)
                    continue
                if ch is None:
                    note("boxes_not_a_letter")
                    continue
                if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                    note("boxes_too_small")
                    continue
                yield pap, ch, page.crop(box)


def collect(hellchar=None, icdar=None, icdar_optional=False):
    """Items from both sources and notes on ICDAR. With icdar_optional, an ICDAR source that fails as a
    whole (an unexpected layout, say) is dropped and its error recorded, so Hell-Char alone still builds."""
    items = list(hellchar_items(hellchar)) if hellchar else []
    notes = {}
    if icdar:
        errors, counts = ([] if icdar_optional else None), {}
        try:
            extra = list(icdar_items(icdar, errors, counts))
        except Exception as exc:
            if not icdar_optional:
                raise
            extra, notes["icdar_error"] = [], repr(exc)
        if errors:
            notes["icdar_skipped"] = len(errors)
            notes["icdar_skipped_first"] = errors[:10]
        if counts:
            notes["icdar_passed_over"] = counts
        if not extra and "icdar_error" not in notes:
            notes["icdar_error"] = "no ICDAR letter boxes found"
        items += extra
    return items, notes


def build(items, out, bank_h=BANK_H, notes=None):
    """Scale each papyrus's crops to a common letter height and write the bank (npz); returns stats
    (notes, such as why ICDAR was left out, are added to them)."""
    from PIL import Image
    raw = {}
    for pap, ch, im in items:
        raw.setdefault(pap, []).append((ch, np.asarray(im, dtype=np.uint8)))
    glyphs, shapes, cls, paps, split = [], [], [], [], []
    names = sorted(raw)
    dropped = {"flat": 0, "size": 0, "texture": 0}
    for pi, pap in enumerate(names):
        crops = raw[pap]
        plain = [a.shape[0] for ch, a in crops if ch in PLAIN]
        ref = float(np.median(plain if len(plain) >= 5 else [a.shape[0] for _, a in crops]))
        f = bank_h / max(ref, 1.0)
        for ch, a in crops:
            h, w = max(1, int(round(a.shape[0] * f))), max(1, int(round(a.shape[1] * f)))
            if not (0.2 * bank_h <= h <= 2.5 * bank_h and 0.05 * bank_h <= w <= 3.0 * bank_h):
                dropped["size"] += 1
                continue
            ink = ink_from_photo(np.asarray(Image.fromarray(a).resize((w, h), Image.BILINEAR)))
            if ink is None:
                dropped["flat"] += 1
                continue
            if np.median(ink) > 0.04:            # papyrus texture leaked over most of the crop
                dropped["texture"] += 1
                continue
            glyphs.append((ink * 255).round().astype(np.uint8))
            shapes.append((h, w))
            cls.append(ALPHABET.index(ch))
            paps.append(pi)
            split.append(1 if is_val(pap) else 0)
    if not glyphs:
        raise SystemExit("no usable crops")
    cls, split = np.array(cls, np.int8), np.array(split, np.uint8)
    stats = {"bank_h": bank_h, "glyphs": len(glyphs), "papyri": len(names),
             "val_papyri": sum(is_val(p) for p in names), "val_glyphs": int(split.sum()), "dropped": dropped,
             "sources": sorted({p.split(":")[0] for p in names}),
             "per_source": {src: sum(names[k].split(":")[0] == src for k in paps)
                            for src in sorted({p.split(":")[0] for p in names})},
             "per_letter": {ALPHABET[k]: int((cls == k).sum()) for k in range(len(ALPHABET))}, **(notes or {})}
    np.savez_compressed(out, flat=np.concatenate([g.reshape(-1) for g in glyphs]),
                        shapes=np.array(shapes, np.int32), cls=cls, pap=np.array(paps, np.int32), split=split,
                        papyri=np.array(json.dumps(names)), stats=np.array(json.dumps(stats, ensure_ascii=False)))
    return stats


class Bank:
    """Glyphs of one split, drawn by letter and (optionally) by papyrus, for letterdata.render_line."""

    def __init__(self, path, split="train"):
        z = np.load(path)
        keep = z["split"] == (1 if split == "val" else 0)
        shapes, flat = z["shapes"], z["flat"]
        offs = np.concatenate([[0], np.cumsum(shapes[:, 0] * shapes[:, 1])])
        self.glyphs = [flat[offs[i]:offs[i + 1]].reshape(shapes[i]) for i in np.nonzero(keep)[0]]
        self.cls, self.pap = z["cls"][keep].astype(int), z["pap"][keep].astype(int)
        self.papyri = json.loads(str(z["papyri"]))
        self.stats = json.loads(str(z["stats"]))
        self.split = split
        self.by_cls = {k: np.nonzero(self.cls == k)[0] for k in range(len(ALPHABET))}
        self.by_pap_cls = {}
        for i, (p, k) in enumerate(zip(self.pap, self.cls)):
            self.by_pap_cls.setdefault((p, k), []).append(i)
        self.pap_ids, counts = np.unique(self.pap, return_counts=True)
        self.pap_p = counts / counts.sum()
        missing = [ALPHABET[k] for k, v in self.by_cls.items() if not len(v)]
        if missing:
            raise ValueError(f"bank split {split} has no {''.join(missing)}")

    def __len__(self):
        return len(self.glyphs)

    def pick_papyrus(self, rng):
        return int(rng.choice(self.pap_ids, p=self.pap_p))

    def glyph(self, ch, h, rng, style):
        """(uint8 image, x0, x1, base row) like letterdata.render_font_glyph, from a real crop."""
        from PIL import Image
        k = ALPHABET.index(ch)
        same = self.by_pap_cls.get((style.get("papyrus", -1), k))
        idx = same if same else self.by_cls[k]
        g = self.glyphs[int(idx[rng.integers(len(idx))])]
        f = h / BANK_H * (1 + rng.normal(0, style.get("height_cv", 0.05)))
        gh = max(2, int(round(g.shape[0] * f)))
        gw = max(1, int(round(g.shape[1] * f * style.get("width", 1.0) * (1 + rng.normal(0, 0.04)))))
        a = np.asarray(Image.fromarray(g).resize((gw, gh), Image.BILINEAR), dtype=np.uint8)
        pad = int(0.6 * h)
        base = int(pad + 1.35 * h)
        if ch == "Ρ":
            top = base - h                       # descender: hangs from the top line
        elif ch in "ΦΨ":
            top = base - 0.5 * h - gh / 2        # rises above and falls below
        elif ch == "Ο":
            top = base - 0.55 * h - gh / 2       # often small and high
        else:
            top = base - gh                      # sits on the base line
        top = int(round(top + rng.normal(0, 0.03) * h))
        H = int(1.9 * h + 2 * pad)
        if top < 0:
            base, top = base - top, 0
        canvas = np.zeros((max(H, top + gh), gw), np.uint8)
        canvas[top:top + gh] = a
        return canvas, 0, gw, base


def preview(bank, out, n=12, seed=0):
    """A PNG of n map-look and n mask-look lines from the bank alone, for a person to look at."""
    from PIL import Image
    rng = np.random.default_rng(seed)
    L.use_bank(bank, 1.0)
    rows = []
    for dom in ("map", "mask"):
        for _ in range(n):
            img, _, _ = L.make_sample(rng, domain=dom, p_blank=0.0)
            rows.append(img)
    W = max(r.shape[1] for r in rows)
    sheet = np.ones((sum(r.shape[0] + 2 for r in rows), W), np.float32)
    y = 0
    for r in rows:
        sheet[y:y + r.shape[0], :r.shape[1]] = r
        y += r.shape[0] + 2
    Image.fromarray((sheet * 255).astype(np.uint8)).save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("--hellchar", help="Hell-Char data folder (hellchar.csv and cliplets/)")
    b.add_argument("--icdar", help="extracted ICDAR 2023 Greek letters dataset (COCO JSON and images)")
    b.add_argument("--icdar-optional", action="store_true",
                   help="skip unreadable ICDAR photographs and boxes, and drop ICDAR if it fails as a whole")
    s = sub.add_parser("stats")
    s.add_argument("bank")
    p = sub.add_parser("preview")
    p.add_argument("bank")
    p.add_argument("out")
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--split", default="train", choices=["train", "val"])
    a = ap.parse_args(argv)
    if a.cmd == "build":
        if not (a.hellchar or a.icdar):
            ap.error("give --hellchar and/or --icdar")
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)   # before the long build, not after

        items, notes = collect(a.hellchar, a.icdar, a.icdar_optional)
        print(json.dumps(build(items, a.out, notes=notes), ensure_ascii=False, indent=1))
    elif a.cmd == "stats":
        z = np.load(a.bank)
        print(json.dumps(json.loads(str(z["stats"])), ensure_ascii=False, indent=1))
    else:
        preview(Bank(a.bank, a.split), a.out, a.n)


if __name__ == "__main__":
    try:   # Greek prints in a pipe and on a Windows console (kit is not needed for anything else here)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from kit.letterread import utf8_console
        utf8_console()
    except ImportError:
        pass
    main()
