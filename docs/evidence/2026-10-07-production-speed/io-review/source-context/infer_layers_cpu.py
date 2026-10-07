"""Adapt numbered renderer TIFF layers to the official villa CPU ink reader.

No model or inference algorithm is implemented here. All normalization, tiling,
blending, and prediction call the pinned official villa implementation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys

ROOT = Path('/workspace/scrolls-env')
VILLA = ROOT / 'inference-villa'
SOURCE_REVISION = 'e0bbb8b40a2db58b1d71864f286eb85717e59e64'
MODEL_REVISION = '7109667e2607db1b90c37c8b09cb876ea7fe7bb1'
CHECKPOINT_SHA256 = 'e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab'
CHECKPOINT = ROOT / 'checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth'
READERS = {
    'ink9um-seed42': {'path': CHECKPOINT, 'sha256': CHECKPOINT_SHA256,
        'revision': MODEL_REVISION, 'source': 'https://huggingface.co/scrollprize/ink_9um'},
    'd9v2': {'path': ROOT / 'checkpoints/d9v2/d9v2_ft-012000.pth',
        'sha256': '50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966',
        'revision': 'v1.0', 'source': 'https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search/releases/tag/v1.0'},
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layers-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--reader', choices=tuple(READERS), required=True)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--shuffle-seed', type=int, default=20261007)
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args()
    reader = READERS[args.reader]
    args.checkpoint = args.checkpoint or reader['path']
    if args.threads < 1:
        parser.error('--threads must be positive')
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError('Use an empty output directory to prevent mixing old and new controls.')
    if not args.checkpoint.is_file():
        raise FileNotFoundError('Official pinned checkpoint is missing: ' + str(args.checkpoint))
    if digest(args.checkpoint) != reader['sha256']:
        raise ValueError('Checkpoint SHA-256 does not match the pinned published reader artifact.')
    revision = subprocess.check_output(['git', '-C', str(VILLA), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != SOURCE_REVISION:
        raise ValueError('Official villa source revision changed: ' + revision)
    sys.path.insert(0, str(VILLA / 'vesuvius/src'))
    import numpy as np
    import tifffile
    import torch
    import zarr
    from vesuvius.ink_detection.inference import infer
    from vesuvius.ink_detection.models.checkpoint import select_inference_weights, load_model_state
    from vesuvius.ink_detection.models.model import make_model
    from vesuvius.ink_detection.config import InkConfig
    from vesuvius.ink_detection.inference.inference_runtime import TargetModel
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if torch.version.cuda is not None:
        raise RuntimeError('This adapter requires the installed CPU-only torch build.')
    files = list(args.layers_dir.glob('*.tif')) + list(args.layers_dir.glob('*.tiff'))
    def layer_index(path):
        match = re.search(r'(\d+)$', path.stem)
        if not match:
            raise ValueError('Layer filenames must end with an integer index: ' + path.name)
        return int(match.group(1))
    files.sort(key=layer_index)
    numbers = [layer_index(p) for p in files]
    if not files or len(set(numbers)) != len(numbers) or numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise ValueError('Require unique consecutively numbered renderer TIFF layers.')
    stack = np.stack([tifffile.imread(p) for p in files])
    if stack.ndim != 3 or stack.dtype != np.uint8:
        raise ValueError('Require renderer uint8 TIFF layers yielding shape Z,Y,X.')
    if stack.max() == 0:
        raise ValueError('Rendered layers are all zero; refusing a vacuous inference run.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inference_args = infer.parse_args([
        str(args.output_dir / 'selected_layers.zarr'), str(args.checkpoint),
        str(args.output_dir / 'forward_s42.tif'), '--stride', '42', '--blend-mode', 'hann',
        '--batch-size', '1', '--num-workers', '0', '--no-compile', '--amp-dtype', 'default',
    ])
    payload = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
    state_name, state = select_inference_weights(payload, source=args.checkpoint)
    config = InkConfig.from_mapping(payload['config'])
    if config.data.mode != 'flat' or config.model.crop_size[1] != config.model.crop_size[2]:
        raise ValueError('Require a flat checkpoint with square spatial patches.')
    base_model = make_model(config)
    load_model_state(base_model, state)  # Strict official state loading, including DDP key handling.
    configured = infer.ConfiguredModel(
        model=TargetModel(base_model, input_pad_depth_to=config.model.input_pad_depth_to).eval(),
        patch_size=config.model.crop_size[1], input_depth=config.model.crop_size[0],
        preprocessing=infer.flat_preprocessing_from_config(config.data.normalization), amp_dtype=None)
    indices = infer.select_layer_indices(len(files), layer_start=None, layer_end=None,
                                         output_depth=configured.input_depth, direction='forward')
    if len(indices) != configured.input_depth:
        raise ValueError('Renderer exported fewer layers than the checkpoint input depth.')
    selected = np.ascontiguousarray(stack[indices])
    order = np.random.default_rng(args.shuffle_seed).permutation(len(indices))
    if np.array_equal(order, np.arange(len(indices))) or np.array_equal(order, np.arange(len(indices))[::-1]):
        raise ValueError('Shuffle must differ from both ordered and reversed controls.')
    sources = {}
    for name, data in [('selected', selected), ('shuffled', np.ascontiguousarray(selected[order]))]:
        path = args.output_dir / (name + '_layers.zarr')
        zarr.open_group(str(path), mode='w', zarr_format=2).create_array('0', data=data,
            chunks=(data.shape[0], min(128, data.shape[1]), min(128, data.shape[2])))
        sources[name] = path
    # The reverse and shuffled controls use exactly the selected forward voxels.
    manifest = {
        'status': 'prepared', 'device': 'cpu', 'torch': torch.__version__,
        'villa_revision': revision, 'reader': args.reader, 'reader_source': reader['source'], 'checkpoint_revision': reader['revision'],
        'checkpoint_sha256': reader['sha256'], 'checkpoint_state': state_name,
        'exported_layer_count': len(files), 'input_shape': list(selected.shape),
        'selected_source_layers': [numbers[i] for i in indices],
        'reverse_source_layers': [numbers[i] for i in indices[::-1]],
        'shuffle_source_layers': [numbers[indices[i]] for i in order],
        'shuffle_seed': args.shuffle_seed, 'stride': 42, 'batch_size': 1,
        'blend_mode': 'hann', 'amp': 'disabled', 'mirror_tta': False,
        'preprocessing': configured.preprocessing,
        'layer_sha256': {p.name: digest(p) for p in files},
        'outputs': {}, 'note': 'Model output on rendered layers, not a reading or correction verdict.'
    }
    record = args.output_dir / 'inference_manifest.json'
    record.write_text(json.dumps(manifest, indent=2) + '\n')
    with torch.inference_mode():
        for name, input_path, direction in [
            ('forward', sources['selected'], 'forward'),
            ('reverse', sources['selected'], 'reverse'),
            ('shuffle', sources['shuffled'], 'forward'),
        ]:
            output = args.output_dir / (name + '_s42.tif')
            infer.infer_single_zarr(args=inference_args, input_zarr=input_path,
                configured_model=configured, device=torch.device('cpu'), output_tiff=output,
                layer_direction=direction)
            prediction = tifffile.imread(output)
            if prediction.shape != selected.shape[1:] or prediction.dtype != np.uint8:
                raise ValueError('Unexpected prediction shape/type for ' + name)
            manifest['outputs'][name] = {'path': str(output), 'sha256': digest(output),
                'shape': list(prediction.shape), 'min': int(prediction.min()), 'max': int(prediction.max())}
            record.write_text(json.dumps(manifest, indent=2) + '\n')
    manifest['status'] = 'inference_completed_scoring_pending'
    record.write_text(json.dumps(manifest, indent=2) + '\n')
    print(record)


if __name__ == '__main__':
    main()
