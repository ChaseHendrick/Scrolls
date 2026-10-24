"""Build any segmentation network of the model zoo by name, and frozen 2D feature extractors (DINOv2, DINOv3).

The family list, licenses and the evidence for each are in kit/segzoo.py (`python -m kit segzoo list`). This
file only builds networks, so that nnU-Net trainers (segzoo_nnunet.py), probes (segzoo_probe.py) and one-off
scripts all get the same network for the same name:

  build(name, in_ch, out_ch, dims=3, **kw)   a torch.nn.Module mapping (b, in_ch, *spatial) to (b, out_ch,
                                             *spatial) logits at the input size. Names:
      mednext-s, mednext-b, mednext-m, mednext-l   MONAI MedNeXt (kernel 3; kernel=5 to change), 2D or 3D
      swinunetr, swinunetr-v2                      MONAI SwinUNETR (sides divisible by 32), 2D or 3D
      segresnet                                    MONAI SegResNet, Auto3DSeg's main algorithm, 2D or 3D
      segformer-b0 ... segformer-b5                transformers SegFormer, 2D, random init; in_ch is the
                                                   number of depth layers for 2.5D ink. Logits come out at a
                                                   quarter of the input size and are upsampled bilinearly
      ss2dunet                                     our pure-PyTorch SS2D (Mamba) U-Net, 2D (segzoo_ss2d.py)
  names()                                    every name build accepts
  FrozenFeatures(model_id, device)           a frozen Hugging Face DINOv2 or DINOv3 backbone: images (b, H, W)
                                             or (b, 3, H, W) in [0, 1] become ImageNet-normalized 3-channel input
                                             at `size` px, and features() returns the class token concatenated
                                             with the mean patch token (2 x hidden size)

Pretrained weights are never fetched by build(). FrozenFeatures downloads its model from Hugging Face on first
use; DINOv3 repositories are gated, so they need an approved account (`huggingface-cli login`). Licenses:
MONAI Apache-2.0; SegFormer code and weights NVIDIA non-commercial; DINOv3 its own license; DINOv2 Apache-2.0.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

MEDNEXT = {"mednext-s": "S", "mednext-b": "B", "mednext-m": "M", "mednext-l": "L"}
SEGFORMER = {f"segformer-b{i}": i for i in range(6)}
# SegFormer encoder sizes from the paper (Xie et al. 2021, table 1): hidden sizes, depths, decoder width
_MIT = {
    0: ([32, 64, 160, 256], [2, 2, 2, 2], 256),
    1: ([64, 128, 320, 512], [2, 2, 2, 2], 256),
    2: ([64, 128, 320, 512], [3, 4, 6, 3], 768),
    3: ([64, 128, 320, 512], [3, 4, 18, 3], 768),
    4: ([64, 128, 320, 512], [3, 8, 27, 3], 768),
    5: ([64, 128, 320, 512], [3, 6, 40, 3], 768),
}
OTHER = ("swinunetr", "swinunetr-v2", "segresnet", "ss2dunet")


def names():
    return sorted(MEDNEXT) + list(OTHER[:3]) + sorted(SEGFORMER) + ["ss2dunet"]


class _SegFormer(nn.Module):
    """transformers' SegformerForSemanticSegmentation with logits resized back to the input size."""

    def __init__(self, in_ch, out_ch, variant):
        super().__init__()
        from transformers import SegformerConfig, SegformerForSemanticSegmentation
        hidden, depths, dec = _MIT[variant]
        cfg = SegformerConfig(num_channels=in_ch, num_labels=out_ch, hidden_sizes=hidden, depths=depths,
                              decoder_hidden_size=dec)
        self.net = SegformerForSemanticSegmentation(cfg)

    def forward(self, x):
        logits = self.net(pixel_values=x).logits
        return F.interpolate(logits, size=x.shape[-2:], mode="bilinear", align_corners=False)


def build(name, in_ch, out_ch, dims=3, **kw):
    """The network called `name`; see the module docstring. Raises ValueError for an unknown name or a family
    that has no `dims`-D form."""
    if dims not in (2, 3):
        raise ValueError(f"dims must be 2 or 3, got {dims}")
    if name in MEDNEXT:
        from monai.networks.nets.mednext import create_mednext
        return create_mednext(MEDNEXT[name], spatial_dims=dims, in_channels=in_ch, out_channels=out_ch,
                              kernel_size=kw.get("kernel", 3), deep_supervision=False)
    if name in ("swinunetr", "swinunetr-v2"):
        from monai.networks.nets import SwinUNETR
        return SwinUNETR(in_channels=in_ch, out_channels=out_ch, feature_size=kw.get("feature_size", 48),
                         spatial_dims=dims, use_v2=name.endswith("v2"), use_checkpoint=kw.get("checkpoint", False))
    if name == "segresnet":
        from monai.networks.nets import SegResNet
        return SegResNet(spatial_dims=dims, in_channels=in_ch, out_channels=out_ch,
                         init_filters=kw.get("init_filters", 32), blocks_down=(1, 2, 2, 4), blocks_up=(1, 1, 1))
    if name in SEGFORMER:
        if dims != 2:
            raise ValueError("segformer is 2D only: give the depth layers as channels (2.5D)")
        return _SegFormer(in_ch, out_ch, SEGFORMER[name])
    if name == "ss2dunet":
        if dims != 2:
            raise ValueError("ss2dunet is 2D only")
        from segzoo_ss2d import SS2DUNet
        return SS2DUNet(in_ch, out_ch, widths=kw.get("widths", (32, 64, 128, 256)), blocks=kw.get("blocks", 1),
                        fast=kw.get("fast", False))
    raise ValueError(f"unknown network {name!r}; known: {', '.join(names())}")


def multiple_of(name):
    """Side lengths the network needs to divide by (1 when any size works)."""
    if name.startswith("swinunetr"):
        return 32
    if name in MEDNEXT:
        return 16
    if name == "segresnet":
        return 8
    if name in SEGFORMER:
        return 32
    if name == "ss2dunet":
        return 8
    return 1


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class FrozenFeatures:
    """A frozen DINOv2 or DINOv3 image backbone from Hugging Face, in eval mode with no gradients.

    model_id: such as "facebook/dinov2-small" (Apache-2.0, open) or "facebook/dinov3-vits16-pretrain-lvd1689m"
    (DINOv3 License, gated). size: input side in pixels, rounded to the patch size."""

    def __init__(self, model_id, device="cpu", size=224, revision=None):
        from transformers import AutoModel
        self.model_id, self.device = model_id, torch.device(device)
        self.model = AutoModel.from_pretrained(model_id, revision=revision).to(self.device).eval()
        for p in self.model.parameters():
            p.requires_grad_(False)
        patch = getattr(self.model.config, "patch_size", 16)
        self.size = max(patch, int(round(size / patch)) * patch)
        self.registers = int(getattr(self.model.config, "num_register_tokens", 0) or 0)
        self.dim = 2 * int(self.model.config.hidden_size)

    def prepare(self, images):
        """(b, H, W) or (b, 1|3, H, W) float in [0, 1] -> normalized (b, 3, size, size)."""
        x = torch.as_tensor(images, dtype=torch.float32)
        if x.dim() == 3:
            x = x[:, None]
        if x.shape[1] == 1:
            x = x.repeat(1, 3, 1, 1)
        if x.shape[1] != 3:
            raise ValueError(f"images need 1 or 3 channels, got {x.shape[1]}")
        x = F.interpolate(x, size=(self.size, self.size), mode="bilinear", align_corners=False)
        mean = torch.tensor(IMAGENET_MEAN).view(1, 3, 1, 1)
        std = torch.tensor(IMAGENET_STD).view(1, 3, 1, 1)
        return ((x - mean) / std).to(self.device)

    @torch.no_grad()
    def features(self, images, batch=32):
        """(n, 2 * hidden) float32 numpy: class token and mean patch token per image."""
        out = []
        for i in range(0, len(images), batch):
            h = self.model(pixel_values=self.prepare(images[i:i + batch])).last_hidden_state
            cls = h[:, 0]
            patches = h[:, 1 + self.registers:]
            out.append(torch.cat([cls, patches.mean(1)], dim=1).float().cpu())
        return torch.cat(out).numpy()
