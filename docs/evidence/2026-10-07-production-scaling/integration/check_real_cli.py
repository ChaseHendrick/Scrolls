#!/usr/bin/env python3
"""Fresh subprocess CLI equivalence on frozen real papyrus inputs. Run only after root GO."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE_COMMIT = 'c43c41a59ac3793b9a653fa236165f6f6b9d47a4'
WORK = Path('/workspace/scrolls-env/production-speed-v2')
DATA = Path('/workspace/scrolls-env/supervised-surfacefix')
MANIFEST = DATA / 'actual-maps-manifest.json'
LABELS = Path('/workspace/scrolls-env/geometry-validation/labels-w00')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tree_hashes(path):
    return {str(p.relative_to(path)): digest(p) for p in sorted(path.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def source_hashes(repo):
    return {str(p.relative_to(repo)): digest(p) for p in sorted((repo / 'kit').rglob('*.py'))}


def baseline_expected(repo):
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE_COMMIT, '--', 'kit'], cwd=repo, text=True).splitlines()
    return {p: hashlib.sha256(subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{p}'], cwd=repo)).hexdigest() for p in paths if p.endswith('.py')}


def input_hashes():
    manifest = json.loads(MANIFEST.read_text())
    files = {MANIFEST}
    for item in [manifest['baseline'], manifest['reference'], *manifest['candidates']]:
        mesh = MANIFEST.parent / item['mesh']
        files.update(mesh / name for name in ('meta.json', 'x.tif', 'y.tif', 'z.tif'))
        files.update(MANIFEST.parent / m['path'] for m in item['maps'].values())
    for name in ('inklabels.zarr', 'supervision.zarr'):
        files.update(p for p in (LABELS / name).rglob('*') if p.is_file())
    return {str(p.resolve()): digest(p) for p in sorted(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-approved', action='store_true', help='Required explicit execution gate after root approves geometry and benchmark schedule.')
    parser.add_argument('--candidate', type=Path, default=Path('/workspace/Scrolls'))
    parser.add_argument('--baseline', type=Path, default=WORK / 'scoring-baseline')
    parser.add_argument('--python', type=Path, default=Path('/workspace/Scrolls/.venv/bin/python'))
    parser.add_argument('--output', type=Path, default=WORK / 'integration' / 'actual-cli-results')
    args = parser.parse_args()
    if not args.execute_approved:
        parser.error('Prepared only: execution requires root GO and --execute-approved.')
    candidate = args.candidate.resolve()
    baseline = args.baseline.resolve()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite existing output: {output}')
    if source_hashes(baseline) != baseline_expected(candidate):
        raise RuntimeError('Baseline export is not the exact c43c41a kit source.')
    sources_before = {'baseline': source_hashes(baseline), 'candidate': source_hashes(candidate)}
    inputs_before = input_hashes()
    output.mkdir(parents=True)
    (output / 'input-freeze.json').write_text(json.dumps(inputs_before, indent=2) + '\n')
    (output / 'source-freeze.json').write_text(json.dumps(sources_before, indent=2) + '\n')
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.update({k: '1' for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    affinity = min(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    def one_cpu():
        if affinity is not None:
            os.sched_setaffinity(0, {affinity})
    hp = ['hpscore', str(DATA / 'reader-baseline' / 'forward_s42.tif'),
          '--control', str(DATA / 'reader-baseline' / 'reverse_s42.tif'),
          '--labels', str(LABELS / 'inklabels.zarr'), '--mask', str(LABELS / 'supervision.zarr'),
          '--voxel-um', '9.366', '--level', '2', '--crop', '2720', '3360', '2720', '3360',
          '--surface-shape', '4220', '4760', '--inner', '64']
    rows = []
    records = {}
    for variant, repo in (('baseline', baseline), ('candidate', candidate)):
        folder = output / variant
        folder.mkdir()
        tasks = [('surfacefix', ['surfacefix', 'apply', str(MANIFEST), str(folder / 'surfacefix-output'), '--json']),
                 ('hpscore-json', hp + ['--json']), ('hpscore-text', hp)]
        records[variant] = {}
        for name, cli_args in tasks:
            command = [str(args.python), '-m', 'kit', *cli_args]
            run = subprocess.run(command, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 preexec_fn=one_cpu if affinity is not None else None, timeout=600)
            (folder / f'{name}.stdout').write_bytes(run.stdout)
            (folder / f'{name}.stderr').write_bytes(run.stderr)
            expected = 1 if name == 'surfacefix' else 0
            row = {'variant': variant, 'name': name, 'cwd': str(repo), 'command': command,
                   'exit_code': run.returncode, 'expected_exit_code': expected,
                   'stdout_sha256': hashlib.sha256(run.stdout).hexdigest(),
                   'stderr_sha256': hashlib.sha256(run.stderr).hexdigest()}
            rows.append(row)
            if run.returncode != expected:
                raise RuntimeError(f'{variant}/{name}: unexpected exit {run.returncode}, stderr={run.stderr.decode(errors="replace")}')
            records[variant][name] = {'exit_code': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr}
            if name == 'surfacefix':
                report = json.loads(run.stdout)
                if report['status'] != 'no_corrections' or report['accepted_regions'] != 0 or report['flagged_regions'] != 16:
                    raise RuntimeError(f'{variant}: changed frozen abstention result')
                row['status'] = report['status']
                row['accepted_regions'] = report['accepted_regions']
                row['flagged_regions'] = report['flagged_regions']
                row['files_sha256'] = tree_hashes(folder / 'surfacefix-output')
                records[variant][name]['files_sha256'] = row['files_sha256']
                if run.stdout != (folder / 'surfacefix-output' / 'report.json').read_bytes():
                    raise RuntimeError('Surfacefix stdout does not exactly equal written report.json')
    sources_after = {'baseline': source_hashes(baseline), 'candidate': source_hashes(candidate)}
    inputs_after = input_hashes()
    if sources_after != sources_before or inputs_after != inputs_before:
        raise RuntimeError('Source or fixed input changed during equivalence run.')
    exact = records['baseline'] == records['candidate']
    receipt = {'baseline_commit': BASE_COMMIT, 'rows': rows, 'all_files_stdout_stderr_exit_exact': exact,
               'inputs_unchanged': True, 'sources_unchanged': True, 'cpu_affinity': affinity,
               'expected_abstention_exit_1': 'Surfacefix wrote the unchanged mesh and report with no_corrections; this is expected and is not a CLI crash.'}
    (output / 'equivalence.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not exact:
        raise RuntimeError('Fresh baseline/candidate CLI results differ; inspect archived bytes and hashes.')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
