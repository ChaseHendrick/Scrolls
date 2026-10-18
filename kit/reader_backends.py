"""Explicit local reader selection: Greek LineNet or installed Tesseract language packs.

There is no automatic fallback or remote inference. Tesseract never downloads a model; Greek
released names use the existing pinned-hash downloader. Tesseract emits words and
uncalibrated word confidence, in its own schema; it does not borrow the Greek reader's letter
confidence or its scroll validation gate. Every result remains model output, not a reading.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from . import __version__

BACKENDS = ("linenet", "tesseract")
ALIASES = {"greek": "grc", "ancient-greek": "grc", "latin": "lat", "english": "eng", "hebrew": "heb"}
SCRIPTS = {"grc": "Greek", "ell": "Greek", "lat": "Latin", "eng": "Latin", "heb": "Hebrew",
           "ara": "Arabic", "cop": "Coptic"}
PSMS = (3, 6, 7, 11, 13)
NOTE = "Model output, not a reading. OCR on printed text does not establish accuracy on scroll ink maps."


def languages(value):
    """Normalize explicit language aliases or a plus-separated list of Tesseract language codes."""
    if not isinstance(value, str) or not value:
        raise ValueError("language must name a language code, such as grc, lat or heb")
    result = [ALIASES.get(code, code) for code in value.split("+")]
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", code) or code == "osd" for code in result):
        raise ValueError("language must use recognition language codes; paths and osd are not languages")
    if len(set(result)) != len(result):
        raise ValueError("language codes must not repeat")
    return result


def validate_route(backend, language):
    """Validate a backend's script capability before loading weights or reading input data."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown reader backend {backend!r}; choose linenet or tesseract")
    codes = languages(language)
    if backend == "linenet" and codes != ["grc"]:
        raise ValueError("linenet supports Greek (grc) only; use tesseract with an installed language pack")
    return codes


def validate_linenet(net):
    """Refuse a checkpoint whose actual alphabet cannot support this Greek-only route."""
    if not isinstance(getattr(net, "alphabet", None), str) or not net.alphabet:
        raise ValueError("LineNet checkpoint alphabet must be a nonempty string")
    letters = [character for character in net.alphabet if character.isalpha()]
    if not letters or any(not unicodedata.name(character, "").startswith("GREEK ") for character in letters):
        raise ValueError("LineNet checkpoint alphabet is not Greek; no script relabeling or model substitution is allowed")
    return net


def _probe_linenet(net):
    """A bounded forward pass before a session replaces a working Greek network."""
    import numpy as np
    try:
        rows = net.band_rows
        if type(rows) is not int or not 1 <= rows <= 4096 or not 0 < net.letter_px <= 512:
            raise ValueError("invalid band size or letter size")
        with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
            output = np.asarray(net.log_probs(np.zeros((rows, 64), dtype=np.float32)))
        if output.ndim != 2 or not 0 < output.shape[0] <= 256 or output.shape[1] != len(net.alphabet) + 1 \
                or not np.isfinite(output).all():
            raise ValueError("invalid or non-finite logits")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, FloatingPointError, OverflowError) as exc:
        raise ValueError(f"LineNet checkpoint failed its initialization check: {exc}") from exc


def _run(argv, timeout):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Tesseract exceeded its {timeout:g} second timeout") from exc
    except OSError as exc:
        raise ValueError("Tesseract could not start; install it and check PATH") from exc
    if result.returncode:
        raise ValueError(f"Tesseract exited {result.returncode}: {result.stderr.strip()[-2000:]}")
    if any(message in result.stderr for message in ("Failed loading language", "Error opening data file",
                                                    "Failed to load any languages", "Could not initialize tesseract")):
        # Tesseract can exit zero after silently using just the valid part of a language combination.
        raise ValueError(f"Tesseract could not load every requested language pack: {result.stderr.strip()[-2000:]}")
    return result.stdout


def tesseract_info(tessdata=None):
    """Executable, version, actual data directory and installed recognition codes; no downloads."""
    executable = shutil.which("tesseract")
    if not executable:
        raise ValueError("Tesseract is not installed; install tesseract and its language packs explicitly")
    extra = [] if tessdata is None else ["--tessdata-dir", str(Path(tessdata).expanduser().resolve())]
    listing = _run([executable, *extra, "--list-langs"], 10)
    rows = listing.splitlines()
    match = re.search(r'List of available languages in "([^"]+)"', listing)
    if not match:
        raise ValueError("Tesseract did not report its data directory; give --tessdata explicitly")
    directory = Path(match.group(1)).resolve()
    codes = sorted(row.strip() for row in rows[1:] if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", row.strip())
                   and row.strip() != "osd")
    version_lines = _run([executable, "--version"], 10).splitlines()
    if not version_lines or not version_lines[0].strip():
        raise ValueError("Tesseract did not report its version")
    version = version_lines[0]
    return {"executable": executable, "version": version, "directory": directory, "languages": codes}


def capabilities(tessdata=None):
    """JSON-compatible local capabilities; absence is reported, never replaced with another model."""
    result = {"linenet": {"languages": ["grc"], "scripts": ["Greek"], "weights": "linenet-v1 .npz",
                          "output": "letter hypotheses with the existing Greek controls"}}
    try:
        info = tesseract_info(tessdata)
        result["tesseract"] = {"available": True, "version": info["version"],
                               "languages": [{"code": code, "script": SCRIPTS.get(code, "not cataloged")}
                                             for code in info["languages"]],
                               "output": "word hypotheses; confidence is not calibrated"}
    except ValueError as exc:
        result["tesseract"] = {"available": False, "reason": str(exc), "languages": []}
    return result


def parse_tsv(text, shape, min_confidence=50):
    """Recognized words, preserving Tesseract's raw 0..100 confidence and input pixel boxes."""
    rows = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num"}
    if not required <= set(rows.fieldnames or []):
        raise ValueError("Tesseract returned malformed TSV")
    words = []
    for row in rows:
        if any(row.get(key) is None for key in required):
            raise ValueError("Tesseract returned malformed TSV")
        if row["level"] != "5" or not row["text"].strip():
            continue
        try:
            confidence = float(row["conf"])
            x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            line = [int(row[key]) for key in ("block_num", "par_num", "line_num")]
        except (ValueError, TypeError) as exc:
            raise ValueError("Tesseract returned malformed word coordinates or confidence") from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 100 or min(x, y, w, h) < 0 \
                or w == 0 or h == 0 or y + h > shape[0] or x + w > shape[1]:
            raise ValueError("Tesseract returned invalid word coordinates or confidence")
        words.append({"text": row["text"], "confidence": confidence, "kept": confidence >= min_confidence,
                      "box": [y, y + h, x, x + w], "line": line})
    return words


def _word_text(words):
    lines = {}
    for word in words:
        if word["kept"]:
            lines.setdefault(tuple(word["line"]), []).append(word["text"])
    return "\n".join(" ".join(words) for words in lines.values())


def _image(image, polarity):
    import numpy as np
    a = np.asarray(image)
    if a.ndim != 2 or not a.size or a.dtype.kind not in "uif" or not np.isfinite(a).all():
        raise ValueError("OCR image must be a nonempty finite 2D numeric array")
    if polarity not in ("bright", "dark"):
        raise ValueError("Tesseract needs explicit bright or dark polarity; auto is a LineNet option")
    lo, hi = float(a.min()), float(a.max())
    a = np.zeros(a.shape, dtype=np.uint8) if hi == lo else np.rint((a.astype(float) - lo) * (255 / (hi - lo))).astype(np.uint8)
    return 255 - a if polarity == "bright" else a


def read_tesseract(image, *, language="lat", tessdata=None, psm=3, timeout=60, min_confidence=50,
                   polarity="dark", seed=0, control=None):
    """Run a local OCR model and fixed blank/tile-shuffle controls. Always returns unverified model output."""
    import numpy as np
    from PIL import Image
    codes = validate_route("tesseract", language)
    if type(psm) is not int or psm not in PSMS:
        raise ValueError("OCR psm must be one of 3, 6, 7, 11 or 13")
    if not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise ValueError("OCR timeout must be positive and at most 600 seconds per invocation")
    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 100:
        raise ValueError("OCR min confidence must be from 0 to 100")
    if type(seed) is not int or seed < 0:
        raise ValueError("OCR seed must be a nonnegative integer")
    a = _image(image, polarity)
    c = None if control is None else _image(control, polarity)
    if c is not None and c.shape != a.shape:
        raise ValueError("OCR control image must have the same shape as the input")
    info = tesseract_info(tessdata)
    missing = sorted(set(codes) - set(info["languages"]))
    if missing:
        raise ValueError(f"Tesseract language packs not installed: {', '.join(missing)}; "
                         f"installed: {', '.join(info['languages']) or '(none)'}; install explicitly, or use --tessdata")
    packs = []
    for code in codes:
        path = info["directory"] / f"{code}.traineddata"
        packs.append({"language": code, "script": SCRIPTS.get(code, "not cataloged"), "file": path.name,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "license": "not inferred from local file; check the pack source before redistribution"})
    # Permute short horizontal tiles in each row; preserve contrast and ink count, destroy glyph shapes.
    shuffled = a.copy()
    rng = np.random.default_rng(seed)
    for row in shuffled:
        width = len(row) // 4 * 4
        tiles = row[:width].reshape(-1, 4)
        row[:width] = tiles[rng.permutation(len(tiles))].reshape(-1)
    with tempfile.TemporaryDirectory(prefix="scrolls-ocr-") as tmp:
        def recognize(array, name):
            path = Path(tmp) / f"{name}.png"
            Image.fromarray(array).save(path)
            tsv = _run([info["executable"], str(path), "stdout", "--tessdata-dir", str(info["directory"]),
                        "-l", "+".join(codes), "--psm", str(psm), "--dpi", "300",
                        "-c", "tessedit_create_tsv=1"], timeout)
            words = parse_tsv(tsv, array.shape, min_confidence)
            text = _word_text(words)
            return {"text": text, "words": words, "characters_kept": sum(ch.isalpha() for ch in text)}
        primary = recognize(a, "image")
        controls = {"blank": recognize(np.full_like(a, 255), "blank"),
                    "tile_shuffle": recognize(shuffled, "shuffle")}
        if c is not None:
            controls["control_map"] = recognize(c, "control")
    return {"schema": "scrolls-ocr-v1", "reader": {"name": "scrolls-workbench", "version": __version__},
            "backend": {"id": "tesseract", "version": info["version"], "languages": codes,
                        "code_license": "Apache-2.0", "code_source": "https://github.com/tesseract-ocr/tesseract"},
            "models": packs, "input_shape": list(a.shape), "input_sha256": hashlib.sha256(a.tobytes()).hexdigest(),
            "note": NOTE, "status": "unverified_model_output",
            **primary, "controls": controls,
            "above_controls": primary["characters_kept"] > max(c["characters_kept"] for c in controls.values()),
            "options": {"psm": psm, "timeout_per_invocation_s": timeout, "min_confidence": min_confidence,
                        "polarity": polarity, "seed": seed},
            "confidence_note": "Tesseract word confidence on a 0..100 scale; not a calibrated probability. "
                               "Passing these controls does not establish a correct transcription."}


def read(image, *, backend="linenet", language="grc", weights=None, **options):
    """Explicit reusable backend switch. Never substitutes a model or silently drops an option."""
    codes = validate_route(backend, language)
    if backend == "tesseract":
        if weights is not None:
            raise ValueError("Tesseract uses local language packs, not LineNet weights; give tessdata instead")
        return read_tesseract(image, language="+".join(codes), **options)
    if weights is None:
        raise ValueError("the LineNet Python API needs explicit weights")
    from . import letterread
    net = validate_linenet(letterread.load_weights(weights))
    result = letterread.read(image, net, **options)
    result["backend"] = {"id": "linenet", "languages": codes, "scripts": ["Greek"]}
    return result


class ReaderSession:
    """Keep a selection across calls; activate a replacement only after its local model validates.

    Greek networks stay loaded in memory. Tesseract still starts a local process per invocation;
    the session retains and checks its chosen pack identities, not a persistent OCR server.
    """

    def __init__(self, **selection):
        self._active = None
        self.switch(**selection)

    @property
    def selection(self):
        """A detached JSON-compatible selection snapshot, with no local directory paths."""
        return json.loads(json.dumps(self._active["selection"]))

    def switch(self, *, backend="linenet", language="grc", weights=None, weight_profile=None,
               lines_given=False, tessdata=None):
        """Validate and activate a complete replacement. Failure leaves the old state untouched."""
        codes = validate_route(backend, language)
        proposed = {"backend": backend, "language": "+".join(codes)}
        selection = {"backend": backend, "languages": codes}
        if backend == "linenet":
            if tessdata is not None:
                raise ValueError("LineNet sessions do not use tessdata")
            from . import letterread, letterweights
            if weights is not None:
                spec = letterweights.select_weights(weights, weight_profile, lines_given=lines_given)
                profile = None
            else:
                profile = letterweights.profile_info(weight_profile, lines_given=lines_given)
                spec = profile["weights"]
            net = validate_linenet(letterread.load_weights(spec))
            _probe_linenet(net)
            proposed["net"] = net
            selection.update(weights=letterread.weights_info(net), weight_profile=profile)
        else:
            if weights is not None or weight_profile is not None:
                raise ValueError("Tesseract sessions use language packs, not Greek weights or profiles")
            import numpy as np
            # Initialize the actual replacement model on a blank before touching active state.
            # Merely listing a corrupt .traineddata file would not establish that it loads.
            info = tesseract_info(tessdata)
            directory = info["directory"]
            probe = read_tesseract(np.full((64, 128), 255, dtype=np.uint8), language="+".join(codes),
                                   tessdata=directory, psm=3, timeout=30)
            proposed["tessdata"] = directory
            selection.update(models=probe["models"], engine=probe["backend"]["version"])
        proposed["selection"] = selection
        self._active = proposed
        return self.selection

    def read(self, image, **options):
        """Read with the current selection; model switches are explicit and never inferred from text."""
        if any(key in options for key in ("backend", "language", "weights", "weight_profile", "tessdata")):
            raise ValueError("change a ReaderSession model with switch(), not read() options")
        active = self._active  # one consistent selection even if the caller switches after this point
        if active["backend"] == "linenet":
            result = read(image, backend="linenet", language=active["language"], weights=active["net"], **options)
        else:
            for model in active["selection"]["models"]:
                path = active["tessdata"] / model["file"]
                if hashlib.sha256(path.read_bytes()).hexdigest() != model["sha256"]:
                    raise ValueError("a selected Tesseract pack changed; call switch() to validate the replacement")
            result = read(image, backend="tesseract", language=active["language"], tessdata=active["tessdata"], **options)
            if result["models"] != active["selection"]["models"] or result["backend"]["version"] != active["selection"]["engine"]:
                raise ValueError("the selected Tesseract model or engine changed during the read")
            for model in active["selection"]["models"]:
                if hashlib.sha256((active["tessdata"] / model["file"]).read_bytes()).hexdigest() != model["sha256"]:
                    raise ValueError("the selected Tesseract model or engine changed during the read")
        result["selection"] = json.loads(json.dumps(active["selection"]))
        return result


def run_cli(args):
    """Tesseract branch of letterread; word output has a separate schema and no fabricated glyph boxes."""
    from . import letterread
    unsupported = [name.replace("_", "-") for name in
                   ("weights", "weight_profile", "letter_px", "letter_mm", "um_per_px", "lines", "lm",
                    "p_min", "csv", "page_xml", "overlay") if getattr(args, name, None) is not None]
    defaults = {"deskew": 6.0, "columns": "auto", "nulls": 4, "min_letters": 10, "lm_weight": .5,
                "beam": 32, "no_orientation": False, "overlay_max_side": 4000}
    unsupported += [name.replace("_", "-") for name, value in defaults.items() if getattr(args, name) != value]
    if unsupported:
        raise ValueError("Tesseract does not support these LineNet options: " + ", ".join("--" + x for x in unsupported))
    if not math.isfinite(args.max_mpx) or args.max_mpx <= 0:
        raise ValueError("OCR max-mpx must be positive and finite")
    if args.out and not Path(args.out).resolve().parent.is_dir():
        raise ValueError("OCR output folder does not exist")
    shape = letterread.image_shape(args.image, args.key)
    window = letterread._window(args.crop, shape, "image") if args.crop else (0, shape[0], 0, shape[1])
    if (window[1] - window[0]) * (window[3] - window[2]) > args.max_mpx * 1e6:
        raise ValueError("OCR image exceeds max-mpx; give a smaller crop (no implicit resampling)")
    image = letterread.load_image(args.image, args.key, args.crop)
    control = None
    if args.control:
        if letterread.image_shape(args.control, args.key) != shape:
            raise ValueError("OCR control image must have the same shape as the input")
        control = letterread.load_image(args.control, args.key, args.crop)
    image = letterread.orient(image, args.rotate, args.mirror)
    if control is not None:
        control = letterread.orient(control, args.rotate, args.mirror)
    result = read(image, backend="tesseract", language=args.language, tessdata=args.tessdata,
                  psm=args.ocr_psm, timeout=args.ocr_timeout, min_confidence=args.ocr_min_confidence,
                  polarity=args.polarity, seed=args.seed, control=control)
    # Map the word boxes back through the explicit view transformation and crop to file pixels.
    input_window_shape = (window[1] - window[0], window[3] - window[2])
    for part in [result, *result["controls"].values()]:
        for word in part["words"]:
            y0, y1, x0, x1 = letterread.view_box_to_input(word["box"], args.rotate, args.mirror, input_window_shape)
            word["box"] = [y0 + window[0], y1 + window[0], x0 + window[2], x1 + window[2]]
    result["source"] = {"file": Path(args.image).name, "key": args.key}
    result["image_shape"] = list(shape)
    result["options"].update(crop=list(window), rotate=args.rotate, mirror=args.mirror,
                              box_frame="whole input image after EXIF orientation", max_mpx=args.max_mpx)
    if args.control:
        result["controls"]["control_map"]["source"] = Path(args.control).name
    output = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
    print(output if args.json else NOTE + "\n" + (result["text"] or "(no words above the confidence floor)") +
          f"\ncontrol characters: { {name: c['characters_kept'] for name, c in result['controls'].items()} }")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tessdata", help="local directory of Tesseract .traineddata packs")
    parser.add_argument("--json", action="store_true", help="print machine-readable capabilities")
    args = parser.parse_args(argv)
    result = capabilities(args.tessdata)
    print(json.dumps(result, indent=1) if args.json else "\n".join(f"{key}: {value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
