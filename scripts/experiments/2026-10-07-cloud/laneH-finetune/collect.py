"""Collect descriptive score rows and explicit completeness; emit no positive verdict."""
import argparse
import json
from pathlib import Path

MODELS = ('base', 'P90', 'P80', 'S1', 'S2')
SEGMENTS = ('0841-w00', 'w045')
EXPECTED = {f'{m}_{s}{suffix}' for m in MODELS for s in SEGMENTS for suffix in ('', '_shuf')}


def collect(directory, smoke=False):
    directory = Path(directory)
    rows, seen = [], set()
    for f in sorted((directory/'scores').glob('*.json')):
        name = f.stem
        if name not in EXPECTED:
            raise ValueError('unexpected score file: ' + name)
        shuf = name.endswith('_shuf');base = name[:-5] if shuf else name
        model, seg = base.split('_', 1)
        score = json.loads(f.read_text())
        if not isinstance(score, dict) or 'forward' not in score or 'control' not in score:
            raise ValueError('score requires forward and reverse control: ' + name)
        seen.add(name)
        rows.append({'job': 'laneH-finetune', 'segment': seg, 'window': 'crop', 'inner_px': 64,
                     'map_from': 'bare-crop', 'reader': f'ink_9um s42 {"base" if model == "base" else "ft-" + model}',
                     'input': 'depth-shuffled' if shuf else 'as stored', 'device': 'cuda', 'smoke': smoke,
                     'primary_for_arm': not shuf and ((model in ('P90', 'P80', 'S1') and seg == '0841-w00') or (model == 'S2' and seg == 'w045')),
                     'kit_auc': score})
    timing = {}
    for f in sorted((directory/'timing').glob('*.jsonl')):
        steps = {}
        for text in f.read_text().splitlines():
            if text.strip():
                e = json.loads(text);steps.setdefault(e['step'], {})[e['event']] = e['epoch_s']
        timing[f.stem] = {k: {'seconds': v['end'] - v['start'] if 'start' in v and 'end' in v else None,
                              'start_epoch_s': v.get('start')} for k, v in steps.items()}
    containers = [json.loads(p.read_text()) for p in sorted((directory/'timing').glob('container_*.json'))]
    status = 'not run' if not seen else 'complete' if seen == EXPECTED else 'partial'
    rows.insert(0, {'job': 'laneH-finetune', 'status': status, 'smoke': smoke, 'expected_score_rows': len(EXPECTED),
                    'completed_score_rows': len(seen), 'missing_score_keys': sorted(EXPECTED - seen),
                    'interpretation': 'Descriptive model scores only; no automated positive verdict or training-improvement claim.'})
    rows.append({'job': 'laneH-finetune', 'kind': 'timing', 'smoke': smoke, 'phases': timing, 'containers': containers})
    return rows


def main(argv=None):
    p = argparse.ArgumentParser();p.add_argument('directory', type=Path);p.add_argument('output', type=Path)
    p.add_argument('smoke_steps', nargs='?', default='0');a = p.parse_args(argv)
    if a.output.resolve().is_relative_to(Path(__file__).resolve().parent):
        p.error('results must stay outside the tracked job directory')
    if a.output.exists():
        p.error('refusing to overwrite historical collected output')
    a.output.write_text(json.dumps(collect(a.directory, a.smoke_steps not in ('', '0')), indent=1) + '\n')


if __name__ == '__main__':
    main()
