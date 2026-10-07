"""Screen one optional CPU convolution layout using the unchanged official reader.

Only --execute starts inference. This is a warm-operation screening benchmark,
not a full-canvas validation or a fresh CLI benchmark. No labels are loaded.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import resource
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path('/workspace/scrolls-env')
HERE = Path(__file__).resolve().parent
PLAN = HERE / 'experiment-plan.json'
PLAN_SHA256 = '04af40c0a3727338e7888425b4fe3ac14b64e67c4d1a8f322366c33e4bdd7196'
VILLA = ROOT / 'inference-villa'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        parser.error('Static plan only. Run with --execute only after root GO and CPU reservation.')
    if sha(PLAN) != PLAN_SHA256:
        raise ValueError('Frozen plan changed')
    plan = json.loads(PLAN.read_text())
    if args.output_dir.exists():
        raise ValueError('Choose a new output directory; never overwrite evidence')
    checkpoint = Path(plan['frozen_model']['checkpoint_path'])
    if sha(checkpoint) != plan['frozen_model']['checkpoint_sha256']:
        raise ValueError('Pinned checkpoint changed')
    revision = subprocess.check_output(['git', '-C', str(VILLA), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != plan['frozen_model']['villa_revision']:
        raise ValueError('Official source revision changed')
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '2' if name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS') else '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    args.output_dir.mkdir(parents=True)
    result = {'status': 'started', 'plan_sha256': PLAN_SHA256, 'harness_sha256': sha(__file__),
              'rows': [], 'comparisons': [], 'all_exact': None,
              'peak_rss_scope': 'whole shared worker, both models loaded; not variant-specific memory savings'}
    record = args.output_dir / 'result.json'
    write(record, result)

    def budget_exhausted(signum, frame):
        raise TimeoutError('Frozen 175 CPU-second process budget exhausted')

    signal.signal(signal.SIGXCPU, budget_exhausted)
    current_cpu = int(time.process_time())
    resource.setrlimit(resource.RLIMIT_CPU, (current_cpu + 175, current_cpu + 180))
    try:
        sys.path.insert(0, str(VILLA / 'vesuvius/src'))
        import numpy as np
        import tifffile
        import torch
        import zarr
        from vesuvius.ink_detection.inference import infer
        from vesuvius.ink_detection.inference.inference_runtime import TargetModel
        from vesuvius.ink_detection.models.checkpoint import select_inference_weights, load_model_state
        from vesuvius.ink_detection.models.model import make_model
        from vesuvius.ink_detection.config import InkConfig
        if torch.version.cuda is not None:
            raise ValueError('CPU-only torch required')
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        payload = torch.load(checkpoint, map_location='cpu', weights_only=True)
        state_name, state = select_inference_weights(payload, source=checkpoint)
        if state_name != plan['frozen_model']['weights']:
            raise ValueError('Checkpoint weight selection changed')
        config = InkConfig.from_mapping(payload['config'])
        if tuple(config.model.crop_size) != (17, 128, 128):
            raise ValueError('Unexpected model patch/depth')
        baseline = make_model(config)
        load_model_state(baseline, state)
        baseline = TargetModel(baseline, input_pad_depth_to=config.model.input_pad_depth_to).eval()
        candidate = copy.deepcopy(baseline)
        torch.nn.utils.convert_conv2d_weight_memory_format(candidate, torch.channels_last)
        for name, tensor in baseline.state_dict().items():
            if not torch.equal(tensor, candidate.state_dict()[name]):
                raise ValueError('Logical checkpoint values changed: ' + name)
        preprocessing = infer.flat_preprocessing_from_config(config.data.normalization)
        configurations = {name: infer.ConfiguredModel(model=model, patch_size=128, input_depth=17,
                              preprocessing=preprocessing, amp_dtype=None)
                          for name, model in [('baseline', baseline), ('candidate', candidate)]}
        result.update(torch=torch.__version__, device='cpu', checkpoint_sha256=sha(checkpoint),
                      villa_revision=revision, preprocessing=preprocessing,
                      conv2d_count=sum(isinstance(m, torch.nn.Conv2d) for m in candidate.modules()),
                      candidate_channels_last_conv2d_count=sum(isinstance(m, torch.nn.Conv2d) and
                          m.weight.is_contiguous(memory_format=torch.channels_last) for m in candidate.modules()))
        source = zarr.open_group(plan['input']['source'], mode='r')['0']
        y0, y1, x0, x1 = plan['input']['crop_yx']
        data = np.ascontiguousarray(source[:, y0:y1, x0:x1])
        if tuple(data.shape) != (17, 192, 192) or data.dtype != np.uint8 or not data.any():
            raise ValueError('Invalid fixed public input crop')
        result['input_array_sha256'] = hashlib.sha256(data.tobytes()).hexdigest()
        sources = {}
        order = np.random.default_rng(20261007).permutation(17)
        for name, values in [('selected', data), ('shuffled', np.ascontiguousarray(data[order]))]:
            path = args.output_dir / (name + '.zarr')
            zarr.open_group(str(path), mode='w', zarr_format=2).create_array('0', data=values,
                                                                          chunks=(17, 128, 128))
            sources[name] = path
        reader = infer.FlatPatchReader(input_path=sources['selected'], resolution='0', depth_axis_first=True,
                 height=192, width=192, layer_indices=np.arange(17), output_depth=17, preprocessing=preprocessing)
        blocks = infer.iter_blocks((192, 192), 128, 42)
        if len(blocks) != 9:
            raise ValueError('Official scheduler changed')
        dataset = infer.FlatBlockDataset(reader=reader, blocks=blocks, patch_size=128, preprocessing=preprocessing)
        image, metadata = dataset[0]
        if not metadata[4]:
            raise ValueError('Fixed warmup tile has no actual CT')
        with torch.inference_mode():
            for configured in configurations.values():
                configured.model(image.unsqueeze(0))
        directions = [('forward', sources['selected'], 'forward'),
                      ('reverse', sources['selected'], 'reverse'),
                      ('shuffle', sources['shuffled'], 'forward')]
        for pair, sequence in enumerate([('baseline', 'candidate'), ('candidate', 'baseline'),
                                         ('baseline', 'candidate')]):
            pair_outputs = {}
            for variant in sequence:
                folder = args.output_dir / f'pair-{pair}-{variant}'
                folder.mkdir()
                outputs = {}
                start, cpu_start = time.perf_counter(), time.process_time()
                for name, input_path, direction in directions:
                    output = folder / (name + '.tif')
                    official_args = infer.parse_args([str(input_path), str(checkpoint), str(output),
                        '--stride', '42', '--blend-mode', 'hann', '--batch-size', '1',
                        '--num-workers', '0', '--no-compile', '--amp-dtype', 'default'])
                    infer.infer_single_zarr(args=official_args, input_zarr=input_path,
                        configured_model=configurations[variant], device=torch.device('cpu'),
                        output_tiff=output, layer_direction=direction)
                    outputs[name] = str(output)
                elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu_start
                pair_outputs[variant] = outputs
                result['rows'].append({'pair': pair, 'variant': variant, 'wall_seconds': elapsed,
                     'cpu_seconds': cpu, 'worker_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                     'outputs': {name: {'path': path, 'sha256': sha(path)} for name, path in outputs.items()}})
                write(record, result)
            comparison = {'pair': pair, 'controls': {}}
            for name, _, _ in directions:
                first = tifffile.imread(pair_outputs['baseline'][name])
                second = tifffile.imread(pair_outputs['candidate'][name])
                if first.shape != (192, 192) or second.shape != first.shape or first.dtype != np.uint8 or second.dtype != np.uint8:
                    raise ValueError('Unexpected official map shape/dtype')
                delta = np.abs(first.astype(np.int16) - second.astype(np.int16))
                comparison['controls'][name] = {'array_exact': bool(np.array_equal(first, second)),
                    'tiff_exact': sha(pair_outputs['baseline'][name]) == sha(pair_outputs['candidate'][name]),
                    'different_pixels': int(np.count_nonzero(delta)), 'maximum_uint8_difference': int(delta.max())}
            result['comparisons'].append(comparison)
            write(record, result)
        basetimes = [x['wall_seconds'] for x in result['rows'] if x['variant'] == 'baseline']
        candtimes = [x['wall_seconds'] for x in result['rows'] if x['variant'] == 'candidate']
        paired_ratios = [a / b for a, b in zip(basetimes, candtimes)]
        result.update(status='completed', all_exact=all(c['array_exact'] and c['tiff_exact']
              for row in result['comparisons'] for c in row['controls'].values()),
              baseline_median_seconds=statistics.median(basetimes), candidate_median_seconds=statistics.median(candtimes),
              ratio_of_medians=statistics.median(basetimes) / statistics.median(candtimes), paired_ratios=paired_ratios)
        result['screen_passed'] = result['all_exact'] and result['ratio_of_medians'] >= 1.2 and min(paired_ratios) > 1
    except Exception as exc:
        result.update(status='incomplete_or_failed', error=type(exc).__name__ + ': ' + str(exc))
        write(record, result)
        raise
    finally:
        result.update(worker_cpu_seconds=time.process_time(),
                      worker_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        write(record, result)
    print(record)


if __name__ == '__main__':
    main()
