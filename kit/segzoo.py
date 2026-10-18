"""Model zoo for modern segmentation and feature models: what each family is, where it fits, and how to run it.

Chase asked on 17 October 2026 for nnU-Net, NVIDIA Auto3DSeg (MONAI), MedSAM2, DINOv3, MedNeXt, Swin UNETR,
SegFormer and SS2DNet / Mamba-based models "where needed" in the tools. This module is the one list of those
families: license of the code and of the weights, whether the weights are gated, which devices run them, the
pinned package, the place in our tools a family could beat what is there now, and the published evidence for
or against it. The torch code that builds and runs the models lives in scripts/segzoo/; this module stays
standard library, so `python -m kit segzoo list` works on any machine.

  list      every family, one line each (--json for all fields)
  show      one family in full
  env       which of the packages each family needs are installed here, with versions (no torch import)
  datalist  an nnU-Net v2 raw dataset (dataset.json, imagesTr, labelsTr) to a MONAI Auto3DSeg datalist.json
            and task.yaml, with the cases split into folds by a fixed hash, so the same cases train both

Every fact in REGISTRY carries its source and the date it was read (labels as in docs/NOVELTY.md). A family's
`release_ok` says whether its weights may ship in a released tool: the prize terms ask for "open source under a
permissive license" (https://scrollprize.org/prizes, read 17 Oct 2026), so weights for research use only, or under
a custom license, can be measured privately but not released (Interpretation).
"""

import hashlib
import json
import os
import sys
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

READ = "2026-10-17"

# Each family: id, name, kind, dims, packages (import name -> pip pin), code and weights licenses,
# gated, release_ok, devices, weights, fit (where it plugs in here), evidence, verdict, sources.
REGISTRY = [
    {
        "id": "nnunet",
        "name": "nnU-Net v2 (ResEnc M, L, XL presets)",
        "kind": "framework",
        "dims": "2D, 3D",
        "packages": {"nnunetv2": "nnunetv2==2.8.1", "dynamic_network_architectures": "dynamic-network-architectures==0.4.4"},
        "licence_code": "Apache-2.0",
        "licence_weights": "Apache-2.0 for villa's m7 (scrollprize/surface_m7_nnunet)",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA; CPU; 3D convolutions run on Apple MPS for our own 3D models although nnU-Net's docs say they do not",
        "weights": "scrollprize/surface_m7_nnunet (ResEnc L, Dataset100, 786 Kaggle cubes)",
        "fit": "The surface model every tracer reads (m7 is ResEnc L). Also the training framework for the MedNeXt, "
               "Swin UNETR, SegResNet, SegFormer and SS2D trainers in scripts/segzoo/segzoo_nnunet.py, so every arm "
               "shares nnU-Net's data, augmentation and sliding-window inference",
        "evidence": "Kaggle Surface Detection 2026: almost all top 10 used ensembles of the ResEnc nnU-Net baseline "
                    "(Sourced fact, scrollprize.substack.com/p/we-are-cooking, 19 Mar 2026). nnU-Net Revisited "
                    "(arXiv:2404.09556): CNN U-Nets in the nnU-Net framework match or beat newer architectures",
        "verdict": "baseline",
        "sources": ["https://github.com/MIC-DKFZ/nnUNet", "https://pypi.org/project/nnunetv2/",
                    "https://arxiv.org/abs/2404.09556"],
    },
    {
        "id": "primus",
        "name": "Primus V2 (transformer, ships in nnunetv2 2.8.1)",
        "kind": "architecture",
        "dims": "3D",
        "packages": {"nnunetv2": "nnunetv2==2.8.1", "timm": "timm"},
        "licence_code": "Apache-2.0",
        "licence_weights": "none released for scrolls; trained here from scratch",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA (fused AdamW); CPU for tests",
        "weights": "none",
        "fit": "A surface arm that costs only a trainer flag: nnUNetv2_train ... -tr nnUNet_PrimusV2M_Trainer",
        "evidence": "Primus paper (arXiv:2503.01835, TMLR, v2 30 Apr 2026): PrimusV2 'on par with' ResEnc-L and "
                    "MedNeXt on medical data (Sourced fact). No thin-sheet result",
        "verdict": "benchmark",
        "sources": ["https://arxiv.org/abs/2503.01835"],
    },
    {
        "id": "mednext",
        "name": "MedNeXt (ConvNeXt U-Net), sizes S, B, M, L",
        "kind": "architecture",
        "dims": "2D, 3D",
        "packages": {"monai": "monai==1.6.1"},
        "licence_code": "Apache-2.0",
        "licence_weights": "no pretrained v1 weights; MedNeXt-v2 weights not in nnunetv2 2.8.1",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA; CPU; MPS not measured",
        "weights": "none; trained here from scratch",
        "fit": "The surface challenger to m7: nnUNetTrainer_SZMedNeXtB and friends train it inside nnU-Net v2 "
               "(MONAI's MedNeXt class; the official repository is nnU-Net v1 only)",
        "evidence": "nnU-Net Revisited table: MedNeXt L k3 above ResEnc L on all six medical datasets, by 0.08 to "
                    "1.35 Dice, at 1.9 times the training hours (Sourced fact; the margins are our arithmetic). "
                    "MedNeXt-v2 (arXiv:2512.17774): 88.03 against 87.62 mean Dice for ResEnc-L. Cryo-ET membranes "
                    "(arXiv:2606.10255): 0.85 against 0.86 for nnU-Net. The only family with a sourced edge over "
                    "ResEnc L; none on thin sheets",
        "verdict": "benchmark",
        "sources": ["https://github.com/MIC-DKFZ/MedNeXt", "https://arxiv.org/abs/2303.09975",
                    "https://arxiv.org/abs/2512.17774", "https://arxiv.org/abs/2404.09556"],
    },
    {
        "id": "swinunetr",
        "name": "Swin UNETR and Swin UNETR V2 (MONAI)",
        "kind": "architecture",
        "dims": "2D, 3D",
        "packages": {"monai": "monai==1.6.1"},
        "licence_code": "Apache-2.0",
        "licence_weights": "self-supervised model_swinvit.pt: no license stated",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA; CPU; input sides must divide by 32",
        "weights": "optional MONAI self-supervised CT weights (model_swinvit.pt)",
        "fit": "A surface arm by trainer flag (nnUNetTrainer_SZSwinUNETR, _SZSwinUNETRv2); a control more than a "
               "contender",
        "evidence": "nnU-Net Revisited: SwinUNETR below ResEnc M on all six datasets (Sourced fact). Cryo-ET "
                    "membranes 0.81 against 0.86 for nnU-Net (Sourced fact, arXiv:2606.10255)",
        "verdict": "control",
        "sources": ["https://docs.monai.io/en/stable/networks.html", "https://arxiv.org/abs/2404.09556"],
    },
    {
        "id": "auto3dseg",
        "name": "NVIDIA MONAI Auto3DSeg (SegResNet, DiNTS, SwinUNETR, SegResNet2D)",
        "kind": "framework",
        "dims": "2D, 3D",
        "packages": {"monai": "monai==1.6.1"},
        "licence_code": "Apache-2.0",
        "licence_weights": "templates downloaded at run time from Project-MONAI/research-contributions",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA (one GPU, 8 GB or more); CPU fallback; no MPS path",
        "weights": "none; trained here",
        "fit": "A second opinion on any nnU-Net raw dataset: `python -m kit segzoo datalist` writes its datalist "
               "and task.yaml from the same cases and folds, and SegResNet alone runs inside nnU-Net as "
               "nnUNetTrainer_SZSegResNet",
        "evidence": "nnU-Net Revisited: every Auto3DSeg algorithm below the original nnU-Net on all six datasets "
                    "(Sourced fact). Kaggle Surface Detection 2026 deck: 'MONAI, DINOv3, 2D methods all lost' "
                    "(Community report)",
        "verdict": "control",
        "sources": ["https://github.com/Project-MONAI/tutorials/tree/main/auto3dseg",
                    "https://arxiv.org/abs/2404.09556"],
    },
    {
        "id": "segformer",
        "name": "SegFormer (Mix Transformer encoder, MLP decoder)",
        "kind": "architecture",
        "dims": "2D",
        "packages": {"transformers": "transformers>=4.56"},
        "licence_code": "NVIDIA Source Code License (non-commercial: research or evaluation only)",
        "licence_weights": "nvidia/mit-b0 to mit-b5: license other (NVIDIA, non-commercial)",
        "gated": False,
        "release_ok": False,
        "devices": "CUDA; CPU; MPS",
        "weights": "nvidia/mit-b0 ... nvidia/mit-b5 (ImageNet); random init needs no weights",
        "fit": "A 2.5D ink head with depth layers as channels, the decoder of the Kaggle 2023 ink winner; "
               "nnUNetTrainer_SZSegFormer for 2D configurations. Research only: its license blocks a released tool",
        "evidence": "Kaggle Ink Detection 2023, 1st place: 3D encoders flattened over depth, then SegFormer b3/b5 "
                    "(Community report, github.com/ainatersol/Vesuvius-InkDetection). None against ink_9um or v8in",
        "verdict": "private benchmark",
        "sources": ["https://github.com/NVlabs/SegFormer", "https://huggingface.co/nvidia/mit-b0",
                    "https://github.com/ainatersol/Vesuvius-InkDetection"],
    },
    {
        "id": "dinov3",
        "name": "DINOv3 (ViT S/B/L/H/7B with patch 16, ConvNeXt T/S/B/L; LVD-1689M and SAT-493M)",
        "kind": "features",
        "dims": "2D",
        "packages": {"transformers": "transformers>=4.56"},
        "licence_code": "DINOv3 License (custom, non-transferable; Meta may change it)",
        "licence_weights": "DINOv3 License; Hugging Face access approved by hand (gated: manual)",
        "gated": True,
        "release_ok": False,
        "devices": "CUDA; CPU; MPS",
        "weights": "facebook/dinov3-vits16-pretrain-lvd1689m (21M), -vitb16- (86M), -convnext-tiny- (29M), ...",
        "fit": "Frozen features with a small head for single letters, triage windows and per-slice ink "
               "(scripts/segzoo/segzoo_probe.py). Private only, and only after Chase has DINOv3 access on Hugging Face",
        "evidence": "Kaggle Surface Detection 2026: DINOv3 and MedDINOv3 lost (Community report). Frozen dinovol "
                    "(the organizers' 3D DINO) failed both preregistered tests here (Model output)",
        "verdict": "private probe",
        "sources": ["https://github.com/facebookresearch/dinov3", "https://huggingface.co/facebook"],
    },
    {
        "id": "dinov2",
        "name": "DINOv2 (ViT S/B/L/G with patch 14), the ungated fallback",
        "kind": "features",
        "dims": "2D",
        "packages": {"transformers": "transformers>=4.56"},
        "licence_code": "Apache-2.0",
        "licence_weights": "Apache-2.0",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA; CPU; MPS",
        "weights": "facebook/dinov2-small (22M), facebook/dinov2-base (86M), ...",
        "fit": "The same probe as DINOv3 with weights anyone can download, so its results can be public",
        "evidence": "Youssef Nader fine-tuned DINOv2 on crackle labels (Sourced fact, scrollprize.substack.com, "
                    "12 Mar 2025). Frozen DINOv2-S failed the Paris 4 blank-papyrus anomaly test here (Model output)",
        "verdict": "probe",
        "sources": ["https://huggingface.co/facebook/dinov2-small"],
    },
    {
        "id": "medsam2",
        "name": "MedSAM2 (SAM 2.1 Hiera-T fine-tuned on 3D medical images and video)",
        "kind": "promptable",
        "dims": "3D as a slice stack",
        "packages": {"sam2": "sam2 (bowang-lab/MedSAM2 fork, from GitHub)"},
        "licence_code": "Apache-2.0",
        "licence_weights": "wanglab/MedSAM2: card says research and education use only",
        "gated": False,
        "release_ok": False,
        "devices": "CUDA (the official script calls .cuda()); SAM 2 on MPS is 'preliminary'",
        "weights": "wanglab/MedSAM2 MedSAM2_latest.pt (156 MB)",
        "fit": "Follow one sheet through a CT cube from a box or mask on one slice, slice by slice, as a "
               "checker at touching sheets (scripts/segzoo/segzoo_sam2.py). Plain SAM 2.1 (Apache-2.0) runs "
               "through the same code for anything that may be released",
        "evidence": "None on scrolls; no community use found (Interpretation). Promptable, so not compared in "
                    "automatic mode in any table read",
        "verdict": "private benchmark",
        "sources": ["https://github.com/bowang-lab/MedSAM2", "https://huggingface.co/wanglab/MedSAM2",
                    "https://arxiv.org/abs/2504.03600"],
    },
    {
        "id": "sam2",
        "name": "SAM 2.1 (Meta), the permissive base of MedSAM2",
        "kind": "promptable",
        "dims": "3D as a slice stack",
        "packages": {"sam2": "sam2==1.1.0"},
        "licence_code": "Apache-2.0",
        "licence_weights": "Apache-2.0",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA; CPU; MPS preliminary",
        "weights": "facebook/sam2.1-hiera-tiny ... -large",
        "fit": "The released-tool route for the sheet follower",
        "evidence": "None on scrolls (Interpretation)",
        "verdict": "benchmark",
        "sources": ["https://github.com/facebookresearch/sam2"],
    },
    {
        "id": "ss2d",
        "name": "SS2D: VMamba's four-direction 2D selective scan, our pure-PyTorch build (SS2DUNet)",
        "kind": "architecture",
        "dims": "2D",
        "packages": {"torch": "torch>=2.1"},
        "licence_code": "ours (repository license); method from VMamba (MIT)",
        "licence_weights": "none; trained here",
        "gated": False,
        "release_ok": True,
        "devices": "CPU, MPS and CUDA in pure PyTorch; mamba-ssm's CUDA kernel when installed",
        "weights": "none",
        "fit": "A Mamba-based 2D model that runs on the Mac: nnUNetTrainer_SZSS2D for 2D configurations "
               "(triage windows, the center finder's slices, 2.5D ink layers)",
        "evidence": "SS2DNet (arXiv:2503.01306, nnUZoo): Dice within 0.02 of nnU-Net on six datasets at 5 to 20 "
                    "times the training time (Sourced fact). U-Mamba Bot within 0.3 Dice of its no-Mamba "
                    "ablation (nnU-Net Revisited, Sourced fact)",
        "verdict": "control",
        "sources": ["https://arxiv.org/abs/2503.01306", "https://github.com/MzeroMiko/VMamba",
                    "https://github.com/AI-in-Cardiovascular-Medicine/nnUZoo"],
    },
    {
        "id": "umamba",
        "name": "U-Mamba (Bot, Enc) and Swin-UMamba, nnU-Net v2 trainers with mamba-ssm",
        "kind": "architecture",
        "dims": "2D, 3D",
        "packages": {"mamba_ssm": "mamba-ssm==2.3.2.post1", "causal_conv1d": "causal-conv1d==1.7.0"},
        "licence_code": "Apache-2.0",
        "licence_weights": "none for scrolls",
        "gated": False,
        "release_ok": True,
        "devices": "CUDA only in practice (Linux, kernels built for CUDA); not CPU or MPS",
        "weights": "none",
        "fit": "Not wired: bowang-lab's trainers pin torch 2.0.1 and CUDA 11.8, and our B300 image is torch "
               "2.14.1 with CUDA 13.2. The SS2D family covers Mamba here",
        "evidence": "nnU-Net Revisited: the Mamba layer adds nothing over its no-Mamba ablation (Sourced fact)",
        "verdict": "not now",
        "sources": ["https://github.com/bowang-lab/U-Mamba", "https://arxiv.org/abs/2404.09556"],
    },
]

IDS = [f["id"] for f in REGISTRY]
FIELDS = ("id", "name", "kind", "dims", "packages", "licence_code", "licence_weights", "gated", "release_ok",
          "devices", "weights", "fit", "evidence", "verdict", "sources")

# datalist: image file suffixes nnU-Net v2 reads, longest first so .nii.gz wins over .gz
SUFFIXES = (".nii.gz", ".nii", ".nrrd", ".mha", ".tiff", ".tif", ".png")


def family(name):
    for f in REGISTRY:
        if f["id"] == name:
            return f
    raise KeyError(f"unknown family {name!r}; known: {', '.join(IDS)}")


def installed(module):
    """Version string of the installed distribution behind an import name, '' if importable with no metadata,
    None when it is not installed. Never imports the module itself (torch takes seconds)."""
    if find_spec(module) is None:
        return None
    dist = {"sam2": "sam2", "mamba_ssm": "mamba-ssm", "causal_conv1d": "causal-conv1d",
            "dynamic_network_architectures": "dynamic-network-architectures"}.get(module, module)
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return ""


def env_report():
    """{family id: {"ready": bool, "packages": {import name: version or None}}} for this Python."""
    out = {}
    for f in REGISTRY:
        found = {m: installed(m) for m in f["packages"]}
        out[f["id"]] = {"ready": all(v is not None for v in found.values()), "packages": found}
    return out


# ------------------------------------------------------------------ datalist

def _case_id(name, channel_suffix=True):
    for s in SUFFIXES:
        if name.endswith(s):
            stem = name[: -len(s)]
            if channel_suffix:
                if len(stem) < 6 or stem[-5] != "_" or not stem[-4:].isdigit():
                    raise ValueError(f"image {name!r} lacks nnU-Net's _0000 channel suffix")
                return stem[:-5], int(stem[-4:])
            return stem, None
    raise ValueError(f"unsupported file type: {name!r}")


def fold_of(case, folds):
    """A case's fold from the sha256 of its id: fixed, independent of file order and machine."""
    if type(folds) is not int or folds < 2:
        raise ValueError("folds must be an integer of at least 2")
    return int(hashlib.sha256(case.encode()).hexdigest(), 16) % folds


def build_datalist(raw, folds=5, modality=None):
    """Read an nnU-Net v2 raw dataset folder and return (datalist dict, task dict, summary).

    Every case in imagesTr must have its label in labelsTr and every channel the dataset.json names; extra or
    missing files raise ValueError. Cases go to folds by fold_of, so Auto3DSeg and an nnU-Net run told the same
    split train on the same cases."""
    # Check even an empty dataset before iterating, and before write_datalist creates any output.
    fold_of("", folds)
    raw = Path(raw)
    meta_path = raw / "dataset.json"
    if not meta_path.is_file():
        raise ValueError(f"no dataset.json in {raw}")
    meta = json.loads(meta_path.read_text())
    if not isinstance(meta, dict):
        raise ValueError("dataset.json must contain an object")
    channels = meta.get("channel_names") or meta.get("modality")
    if not isinstance(channels, dict) or not channels:
        raise ValueError("dataset.json has no channel_names")
    n_ch = len(channels)
    if set(channels) != {str(i) for i in range(n_ch)}:
        raise ValueError("dataset.json channel_names keys must be consecutive integers starting at 0")
    ending = meta.get("file_ending")
    if ending is not None and ending not in SUFFIXES:
        raise ValueError(f"unsupported dataset file_ending {ending!r}; supported: {', '.join(SUFFIXES)}")
    label_map = meta.get("labels", {})
    if not isinstance(label_map, dict):
        raise ValueError("dataset.json labels must be an object")
    want = meta.get("numTraining")
    if want is not None and (type(want) is not int or want < 1):
        raise ValueError("dataset.json numTraining must be a positive integer")
    images, labels = raw / "imagesTr", raw / "labelsTr"
    if not images.is_dir() or not labels.is_dir():
        raise ValueError(f"{raw} needs imagesTr/ and labelsTr/")
    cases = {}
    for p in sorted(images.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        if ending and not p.name.endswith(ending):
            raise ValueError(f"{p.name} does not end with the dataset's file_ending {ending!r}")
        case, ch = _case_id(p.name)
        if ch >= n_ch:
            raise ValueError(f"{p.name}: channel {ch} but dataset.json names {n_ch}")
        chans = cases.setdefault(case, {})
        if ch in chans:
            raise ValueError(f"duplicate image for case {case!r} channel {ch}: {chans[ch]} and {p.name}")
        chans[ch] = f"imagesTr/{p.name}"
    label_files = {}
    for p in sorted(labels.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        if ending and not p.name.endswith(ending):
            raise ValueError(f"{p.name} does not end with the dataset's file_ending {ending!r}")
        case, _ = _case_id(p.name, channel_suffix=False)
        if case in label_files:
            raise ValueError(f"duplicate label for case {case!r}: {label_files[case]} and {p.name}")
        label_files[case] = f"labelsTr/{p.name}"
    missing = sorted(c for c in cases if c not in label_files)
    orphans = sorted(c for c in label_files if c not in cases)
    if missing or orphans:
        raise ValueError(f"cases without labels: {missing[:5]}; labels without images: {orphans[:5]}")
    if not cases:
        raise ValueError("imagesTr contains no training cases")
    if isinstance(want, int) and want != len(cases):
        raise ValueError(f"dataset.json says numTraining {want} but imagesTr holds {len(cases)} cases")
    training = []
    for case in sorted(cases):
        chans = cases[case]
        if sorted(chans) != list(range(n_ch)):
            raise ValueError(f"case {case}: channels {sorted(chans)}, expected 0..{n_ch - 1}")
        image = chans[0] if n_ch == 1 else [chans[i] for i in range(n_ch)]
        training.append({"image": image, "label": label_files[case], "fold": fold_of(case, folds), "case": case})
    ignore = label_map.get("ignore")
    mod = modality or ("CT" if any(str(v).upper() in ("CT", "CT_DATA") for v in channels.values()) else "MRI")
    datalist = {"training": training, "testing": []}
    task = {"name": meta.get("name", raw.name), "task": "segmentation", "modality": mod,
            "datalist": "datalist.json", "dataroot": str(raw.resolve()), "num_fold": folds}
    per_fold = [sum(1 for t in training if t["fold"] == k) for k in range(folds)]
    summary = {"cases": len(training), "channels": n_ch, "folds": per_fold, "labels": label_map,
               "ignore_label": ignore,
               "notes": [] if ignore is None else
               [f"label value {ignore} is nnU-Net's ignore label; Auto3DSeg treats every label as a class, so "
                "mask it out of the loss or relabel it before AutoRunner"]}
    return datalist, task, summary


def task_yaml(task):
    """task.yaml text in the flat key: value form AutoRunner reads (no yaml package needed)."""
    lines = []
    for k, v in task.items():
        lines.append(f"{k}: {json.dumps(v) if isinstance(v, str) else v}")
    return "\n".join(lines) + "\n"


def write_datalist(raw, out, folds=5, modality=None):
    datalist, task, summary = build_datalist(raw, folds=folds, modality=modality)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "datalist.json").write_text(json.dumps(datalist, indent=1) + "\n")
    task["datalist"] = str((out / "datalist.json").resolve())
    (out / "task.yaml").write_text(task_yaml(task))
    return summary


# ------------------------------------------------------------------ CLI

def _short(f):
    flag = "release ok" if f["release_ok"] else "research only"
    return f"{f['id']:<11} {f['verdict']:<18} {f['dims']:<20} {flag:<14} {f['name']}"


def cmd_segzoo(args):
    action = args.action
    if action == "list":
        if args.json:
            print(json.dumps(REGISTRY, indent=1))
        else:
            print(f"{'id':<11} {'verdict':<18} {'dims':<20} {'weights':<14} name")
            for f in REGISTRY:
                print(_short(f))
        return 0
    if action == "show":
        if not args.name:
            print("segzoo show needs a family id, one of: " + ", ".join(IDS), file=sys.stderr)
            return 2
        try:
            f = family(args.name)
        except KeyError as e:
            print(str(e.args[0]), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(f, indent=1))
        else:
            for k in FIELDS:
                v = f[k]
                if isinstance(v, dict):
                    v = ", ".join(f"{m} ({pin})" for m, pin in v.items())
                elif isinstance(v, list):
                    v = " ; ".join(v)
                print(f"{k}: {v}")
        return 0
    if action == "env":
        rep = env_report()
        if args.json:
            print(json.dumps({"python": sys.version.split()[0], "families": rep}, indent=1))
        else:
            for fid, r in rep.items():
                pk = ", ".join(f"{m} {v if v else ('missing' if v is None else '?')}" for m, v in r["packages"].items())
                print(f"{fid:<11} {'ready' if r['ready'] else 'missing':<8} {pk}")
        return 0
    if action == "datalist":
        raw = args.name
        if not raw or not args.out:
            print("segzoo datalist needs RAW (an nnU-Net raw dataset folder) and --out DIR", file=sys.stderr)
            return 2
        try:
            summary = write_datalist(raw, args.out, folds=args.folds, modality=args.modality)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            print(f"segzoo datalist: {e}", file=sys.stderr)
            return 2
        print(json.dumps(summary, indent=1) if args.json else
              f"wrote {os.path.join(args.out, 'datalist.json')} and task.yaml: {summary['cases']} cases, "
              f"folds {summary['folds']}" + "".join(f"\nnote: {n}" for n in summary["notes"]))
        return 0
    print(f"unknown segzoo action {action!r}", file=sys.stderr)
    return 2


def build_parser(p):
    p.add_argument("action", choices=["list", "show", "env", "datalist"], help="what to do")
    p.add_argument("name", nargs="?", default=None, help="show: a family id; datalist: the nnU-Net raw folder")
    p.add_argument("--out", default=None, help="datalist: folder for datalist.json and task.yaml")
    p.add_argument("--folds", type=int, default=5, help="datalist: number of folds (default 5)")
    p.add_argument("--modality", default=None, choices=["CT", "MRI"],
                   help="datalist: Auto3DSeg modality (default CT when dataset.json names a CT channel, else MRI)")
    p.add_argument("--json", action="store_true", help="print JSON")
    return p


def main(argv=None):
    import argparse
    p = build_parser(argparse.ArgumentParser(prog="python -m kit segzoo", description=__doc__.splitlines()[0]))
    return cmd_segzoo(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
