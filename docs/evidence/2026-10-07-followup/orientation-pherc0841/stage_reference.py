"""Stage a fixed official public surface crop to verify renderer coordinates.

No labels or reader outputs are used to select depth direction or alignment.
"""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import sys
import urllib.request

import numpy as np

ROOT = Path(__file__).resolve().parent
BASE = ('https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/'
        'PHerc0841/segments/20260220213127-w00/surface-volumes/'
        '9.366um-1.2m-113keV-volume-20250821151531.zarr/')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    rule = {
        'scope': 'Public known PHerc0841 w00 papyrus; structural raster/depth-order audit only',
        'base': BASE,
        'crop_yxyx': [2560, 3200, 0, 640],
        'source_shape_zyx': [28, 4220, 4760],
        'chunk_shape_zyx': [28, 128, 128],
        'chunk_keys': [f'0/{y}/{x}' for y in range(20, 25) for x in range(0, 5)],
        'max_bytes': 28 * 640 * 640,
        'comparison': 'Compare direct and reversed generated depth order to the fixed official public stack; report both. No label/reader selection. Require core64 Pearson r>=0.98 and core mean absolute error<=3 uint8 units for a reproduction claim. A failure is diagnostic, not permission to optimize against labels.',
        'script_sha256': sha(Path(__file__)),
        'metadata_sha256': {p.name: sha(p) for p in [ROOT / '.zattrs', ROOT / '0_.zarray']},
    }
    target = ROOT / 'rule.json'
    if target.exists():
        raise RuntimeError('Refusing to replace a frozen rule')
    target.write_text(json.dumps(rule, indent=2) + '\n')
    print('FROZEN', sha(target), flush=True)


def stage():
    rule = json.loads((ROOT / 'rule.json').read_text())
    assert sha(Path(__file__)) == rule['script_sha256']
    for name, digest in rule['metadata_sha256'].items():
        assert sha(ROOT / name) == digest
    arr = np.empty((28, 640, 640), np.uint8)

    def fetch(key):
        url = BASE + '0/' + key
        path = ROOT / 'chunks' / key
        if path.exists():
            raise RuntimeError('Refusing unreceipted reuse')
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read(28 * 128 * 128 + 1)
            etag = response.headers.get('ETag', '').strip('"')
        assert len(data) == 28 * 128 * 128
        if len(etag) == 32 and '-' not in etag:
            assert hashlib.md5(data).hexdigest() == etag
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        _, y, x = map(int, key.split('/'))
        arr[:, (y - 20) * 128:(y - 19) * 128, (x - 0) * 128:(x + 1) * 128] = np.frombuffer(data, np.uint8).reshape(28, 128, 128)
        return {'key': key, 'url': url, 'bytes': len(data), 'etag': etag,
                'sha256': hashlib.sha256(data).hexdigest()}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(fetch, rule['chunk_keys']))
    np.save(ROOT / 'official-published-crop.npy', arr)
    report = {'rule_sha256': sha(ROOT / 'rule.json'), 'chunks': receipts,
              'download_bytes': sum(r['bytes'] for r in receipts),
              'array_sha256': sha(ROOT / 'official-published-crop.npy')}
    (ROOT / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'chunks'}), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--freeze']:
        freeze()
    elif sys.argv[1:] == ['--stage']:
        stage()
    else:
        raise SystemExit('Use --freeze then --stage')
