"""Bind unrun-job caches to source/input bytes; never adopt old unbound outputs."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from kit.provenance import fingerprint


def bind(path, sources, settings, create=False):
    record = {'schema': 1, 'settings': settings,
              'inputs': [fingerprint(source) for source in sources]}
    # Fingerprints contain path and bytes, not volatile mtimes.
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != record:
            raise ValueError('cached inputs/settings changed; choose a fresh output tree')
    elif create:
        path.write_text(json.dumps(record, indent=2) + '\n')
    else:
        raise ValueError('cache has no binding receipt; choose a fresh output tree')
    return record


def create_crop(source, destination, box, kind, seed=20261007, verify_only=False):
    """Atomically create a crop or verify its complete source/recipe/output binding."""
    destination = Path(destination)
    receipt = Path(str(destination) + '.binding.json')
    if kind not in ('stored', 'shuffled') or len(box) != 4:
        raise ValueError('require stored/shuffled kind and four crop coordinates')
    settings = {'crop': list(box), 'kind': kind, 'shuffle_seed': seed}
    if destination.exists():
        bind(receipt, [source, destination], settings)
        return
    if receipt.exists():
        raise ValueError('partial crop cache: output is missing; choose fresh OUT')
    if verify_only:
        raise ValueError('crop cache is missing; complete prepare before GPU execution')
    import numpy as np
    import zarr
    volume = zarr.open(source, mode='r')['0']
    y0, y1, x0, x1 = box
    if len(volume.shape) != 3 or not (0 <= y0 < y1 <= volume.shape[1] and 0 <= x0 < x1 <= volume.shape[2]):
        raise ValueError('crop must lie inside the depth,height,width source')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.crop-', dir=destination.parent) as temporary:
        out = Path(temporary)/'volume.zarr'
        data = np.asarray(volume[:, y0:y1, x0:x1])
        if kind == 'shuffled':
            data = data[np.random.default_rng(seed).permutation(data.shape[0])]
        zarr.open_group(out, mode='w').create_array('0', data=data, chunks=(data.shape[0], 128, 128))
        out.rename(destination)
    bind(receipt, [source, destination], settings, create=True)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('receipt', type=Path)
    p.add_argument('--input', action='append', default=[])
    p.add_argument('--setting', action='append', default=[])
    p.add_argument('--create', action='store_true')
    p.add_argument('--crop', nargs=4, type=int)
    p.add_argument('--kind', choices=('stored', 'shuffled'))
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args(argv)
    if a.crop is not None:
        if len(a.input) != 1 or a.kind is None:
            p.error('crop creation requires exactly one source input and a kind')
        create_crop(a.input[0], a.receipt, a.crop, a.kind, verify_only=a.verify_only)
        return
    if a.verify_only:
        p.error('--verify-only requires crop mode')
    settings = {}
    for text in a.setting:
        key, sep, value = text.partition('=')
        if not sep or not key or key in settings:
            p.error('settings must have distinct KEY=VALUE names')
        settings[key] = value
    bind(a.receipt, a.input, settings, a.create)


if __name__ == '__main__':
    main()
