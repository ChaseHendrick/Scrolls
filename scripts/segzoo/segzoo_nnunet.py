"""nnU-Net v2 trainers that swap in the model zoo's networks, so every architecture trains on the same data.

nnU-Net v2 has no MedNeXt, Swin UNETR, SegResNet, SegFormer or Mamba trainer of its own (nnunetv2 2.8.1 ships
ResEnc and Primus). Each class below changes only the network and, where the architecture's paper used one, the
optimizer; data loading, augmentation, loss (including nnU-Net's ignore label), sliding-window inference and the
plans stay nnU-Net's, so a comparison against the ResEnc baseline has one change per arm:

  trainer                         network (segzoo_nets.build name)   dims   optimizer, initial learning rate
  nnUNetTrainer_SZMedNeXtS|B|M|L  mednext-s|b|m|l (kernel 3)         2D/3D  AdamW 1e-3, weight decay 1e-4
  nnUNetTrainer_SZSwinUNETR       swinunetr                          2D/3D  AdamW 1e-4, weight decay 1e-5
  nnUNetTrainer_SZSwinUNETRv2     swinunetr-v2                       2D/3D  AdamW 1e-4, weight decay 1e-5
  nnUNetTrainer_SZSegResNet       segresnet (Auto3DSeg's default)    2D/3D  nnU-Net's SGD 1e-2
  nnUNetTrainer_SZSegFormerB2     segformer-b2 (random init)         2D     AdamW 6e-5, weight decay 1e-2
  nnUNetTrainer_SZSS2D            ss2dunet (pure-PyTorch SS2D)       2D     AdamW 1e-4, weight decay 5e-2

All use nnU-Net's polynomial schedule and turn deep supervision off (the zoo's networks have one output).
The optimizer choices are ours, following each paper's optimizer family (Interpretation); a preregistered
comparison names them. Primus V2 needs nothing from here: `nnUNetv2_train ... -tr nnUNet_PrimusV2M_Trainer`.

To let `nnUNetv2_train` find these classes, put a shim module in nnU-Net's trainer folder once per environment:

  python scripts/segzoo/segzoo_nnunet.py shim            # writes nnunetv2/training/nnUNetTrainer/segzoo_shim.py
  nnUNetv2_train DATASET 3d_fullres 0 -tr nnUNetTrainer_SZMedNeXtB

The shim only adds this folder to sys.path and imports the classes. `python scripts/segzoo/segzoo_nnunet.py list` prints the table above.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import torch  # noqa: E402
from nnunetv2.training.lr_scheduler.polylr import PolyLRScheduler  # noqa: E402
from nnunetv2.training.nnUNetTrainer.nnUNetTrainer import nnUNetTrainer  # noqa: E402

import segzoo_nets  # noqa: E402

SHIM_NAME = "segzoo_shim.py"


class _SZTrainer(nnUNetTrainer):
    """Base: network from segzoo_nets, deep supervision off, optional AdamW."""

    NET = None
    NET_KW = {}
    DIMS = (2, 3)
    OPTIMIZER = "sgd"
    LR = 1e-2
    WEIGHT_DECAY = 3e-5

    def __init__(self, plans, configuration, fold, dataset_json, device=torch.device("cuda")):
        super().__init__(plans, configuration, fold, dataset_json, device)
        self.enable_deep_supervision = False
        self.initial_lr = self.LR
        self.weight_decay = self.WEIGHT_DECAY

    @classmethod
    def build_network_architecture(cls, plans_manager, configuration_manager, num_input_channels,
                                   num_output_channels, enable_deep_supervision=True):
        patch = list(configuration_manager.patch_size)
        dims = len(patch)
        if dims not in cls.DIMS:
            raise RuntimeError(f"{cls.__name__} builds {cls.NET}, which has no {dims}D form; use a "
                               f"{' or '.join(f'{d}D' for d in cls.DIMS)} configuration")
        m = segzoo_nets.multiple_of(cls.NET)
        if any(p % m for p in patch):
            raise RuntimeError(f"{cls.NET} needs every patch side divisible by {m}; the plans give {patch}")
        return segzoo_nets.build(cls.NET, num_input_channels, num_output_channels, dims=dims, **cls.NET_KW)

    def set_deep_supervision_enabled(self, enabled):
        pass

    def configure_optimizers(self):
        if self.OPTIMIZER == "adamw":
            optimizer = torch.optim.AdamW(self.network.parameters(), self.initial_lr, weight_decay=self.weight_decay)
        else:
            optimizer = torch.optim.SGD(self.network.parameters(), self.initial_lr, weight_decay=self.weight_decay,
                                        momentum=0.99, nesterov=True)
        return optimizer, PolyLRScheduler(optimizer, self.initial_lr, self.num_epochs)


def _make(name, net, dims=(2, 3), optimizer="sgd", lr=1e-2, wd=3e-5, **net_kw):
    return type(name, (_SZTrainer,), {"NET": net, "NET_KW": net_kw, "DIMS": dims, "OPTIMIZER": optimizer,
                                      "LR": lr, "WEIGHT_DECAY": wd, "__module__": __name__})


nnUNetTrainer_SZMedNeXtS = _make("nnUNetTrainer_SZMedNeXtS", "mednext-s", optimizer="adamw", lr=1e-3, wd=1e-4)
nnUNetTrainer_SZMedNeXtB = _make("nnUNetTrainer_SZMedNeXtB", "mednext-b", optimizer="adamw", lr=1e-3, wd=1e-4)
nnUNetTrainer_SZMedNeXtM = _make("nnUNetTrainer_SZMedNeXtM", "mednext-m", optimizer="adamw", lr=1e-3, wd=1e-4)
nnUNetTrainer_SZMedNeXtL = _make("nnUNetTrainer_SZMedNeXtL", "mednext-l", optimizer="adamw", lr=1e-3, wd=1e-4)
nnUNetTrainer_SZSwinUNETR = _make("nnUNetTrainer_SZSwinUNETR", "swinunetr", optimizer="adamw", lr=1e-4, wd=1e-5)
nnUNetTrainer_SZSwinUNETRv2 = _make("nnUNetTrainer_SZSwinUNETRv2", "swinunetr-v2", optimizer="adamw", lr=1e-4,
                                    wd=1e-5)
nnUNetTrainer_SZSegResNet = _make("nnUNetTrainer_SZSegResNet", "segresnet")
nnUNetTrainer_SZSegFormerB2 = _make("nnUNetTrainer_SZSegFormerB2", "segformer-b2", dims=(2,), optimizer="adamw",
                                    lr=6e-5, wd=1e-2)
nnUNetTrainer_SZSS2D = _make("nnUNetTrainer_SZSS2D", "ss2dunet", dims=(2,), optimizer="adamw", lr=1e-4, wd=5e-2)

TRAINERS = {c.__name__: c for c in (
    nnUNetTrainer_SZMedNeXtS, nnUNetTrainer_SZMedNeXtB, nnUNetTrainer_SZMedNeXtM, nnUNetTrainer_SZMedNeXtL,
    nnUNetTrainer_SZSwinUNETR, nnUNetTrainer_SZSwinUNETRv2, nnUNetTrainer_SZSegResNet, nnUNetTrainer_SZSegFormerB2,
    nnUNetTrainer_SZSS2D)}


def shim_text(folder=HERE):
    names = ", ".join(sorted(TRAINERS))
    return ("# Written by scripts/segzoo/segzoo_nnunet.py shim: lets nnUNetv2_train find the model zoo's trainers.\n"
            "import sys\n"
            f"_SEGZOO = {str(folder)!r}\n"
            "if _SEGZOO not in sys.path:\n"
            "    sys.path.insert(0, _SEGZOO)\n"
            f"from segzoo_nnunet import {names}  # noqa: E402,F401\n")


def trainer_folder():
    import nnunetv2
    return Path(nnunetv2.__path__[0]) / "training" / "nnUNetTrainer"


def write_shim(target=None):
    """Write the shim into nnU-Net's trainer folder (or `target`, a folder); returns its path."""
    folder = Path(target) if target else trainer_folder()
    path = folder / SHIM_NAME
    path.write_text(shim_text())
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="nnU-Net v2 trainers for the model zoo's networks")
    p.add_argument("action", choices=["list", "shim"], help="list the trainers, or write the shim into nnU-Net")
    p.add_argument("--target", default=None, help="shim: folder to write into (default nnU-Net's trainer folder)")
    a = p.parse_args(argv)
    if a.action == "list":
        for name, c in TRAINERS.items():
            dims = "/".join(f"{d}D" for d in c.DIMS)
            print(f"{name:<30} {c.NET:<14} {dims:<6} {c.OPTIMIZER} lr {c.LR:g} wd {c.WEIGHT_DECAY:g}")
        return 0
    try:
        path = write_shim(a.target)
    except OSError as e:
        print(f"could not write the shim: {e}", file=sys.stderr)
        return 2
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
