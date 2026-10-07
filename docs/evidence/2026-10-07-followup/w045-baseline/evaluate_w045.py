"""Evaluate the frozen w045 reconstruction readout, with a baseline-only mode."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, '/workspace/Scrolls')
import numpy as np
import tifffile
from kit import auc, hpscore

ROOT = Path('/workspace/scrolls-env/phase-reconstruction')
DIRECTIONS = ('forward', 'reverse', 'shuffle')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bootstrap_weights(mask, block_px=107, draws=1000, seed=20261007):
    y, x = np.nonzero(mask)
    keys = (y // block_px) * (mask.shape[1] // block_px + 1) + x // block_px
    blocks, inverse = np.unique(keys, return_inverse=True)
    if len(blocks) < 2:
        raise ValueError('Insufficient spatial blocks for bootstrap.')
    rng = np.random.default_rng(seed)
    weights = np.stack([np.bincount(rng.integers(0, len(blocks), len(blocks)),
        minlength=len(blocks)) for _ in range(draws)]).astype(np.float64)
    return y, x, blocks, inverse, weights


def auc_bootstrap(a, ink, y, x, inverse, weights):
    lab, scores = ink[y, x], a[y, x]
    hi = np.zeros((weights.shape[1], 256))
    hb = np.zeros_like(hi)
    np.add.at(hi, (inverse[lab], scores[lab]), 1)
    np.add.at(hb, (inverse[~lab], scores[~lab]), 1)
    with np.errstate(divide='ignore', invalid='ignore'):
        point = float(auc._auc_hist(np, hi.sum(0), hb.sum(0)))
        draws = auc._auc_hist(np, weights @ hi, weights @ hb)
    return point, draws


def correlation_moments(a, b, inverse, count):
    return np.stack([np.bincount(inverse, weights=v, minlength=count) for v in
        (np.ones_like(a), a, b, a*a, b*b, a*b)], axis=1)


def correlation_from_moments(m):
    n, a, b, aa, bb, ab = np.moveaxis(m, -1, 0)
    with np.errstate(divide='ignore', invalid='ignore'):
        return (n*ab-a*b) / np.sqrt(np.maximum(n*aa-a*a, 0)*np.maximum(n*bb-b*b, 0))


def interval(draws):
    keep = np.isfinite(draws)
    return {'finite_draws': int(keep.sum()), 'finite_fraction': float(keep.mean()),
        'ci95': [float(v) for v in np.percentile(draws[keep], [2.5,97.5])] if keep.any() else None}


def simultaneous(contrasts):
    """One common95% max centered-bootstrap deviation band for a frozen family."""
    if not contrasts:
        return {}
    labels = list(contrasts)
    points = np.array([contrasts[k][0] for k in labels])
    draws = np.stack([contrasts[k][1] for k in labels], axis=1)
    keep = np.isfinite(draws).all(axis=1) & np.isfinite(points).all()
    usable = float(keep.mean())
    radius = float(np.percentile(np.max(np.abs(draws[keep]-points), axis=1),95)) if usable >= .99 else None
    return {k: {'difference': float(points[i]) if np.isfinite(points[i]) else None,
        'simultaneous_ci95': [float(points[i]-radius), float(points[i]+radius)] if radius is not None else None,
        'finite_fraction': usable, 'family_size': len(labels)} for i,k in enumerate(labels)}


def load_maps(folder, reference_settings=None):
    p = folder / 'inference_manifest.json'
    m = json.loads(p.read_text())
    assert m['status'] == 'inference_completed_scoring_pending'
    assert m['reader'] == 'd9v2' and m['stride'] == 42
    assert m['input_shape'] == [17,640,640]
    settings = {k:m[k] for k in ('villa_revision','checkpoint_sha256','selected_source_layers',
        'shuffle_seed','stride','batch_size','blend_mode','amp','mirror_tta','preprocessing')}
    if reference_settings is not None:
        assert settings == reference_settings, 'Reader settings changed between recipes.'
    assert m['reverse_source_layers'] == m['selected_source_layers'][::-1]
    assert sorted(m['shuffle_source_layers']) == sorted(m['selected_source_layers'])
    arrays = {}
    for d in DIRECTIONS:
        out = Path(m['outputs'][d]['path'])
        assert sha(out) == m['outputs'][d]['sha256']
        a = tifffile.imread(out)
        assert a.shape == (640,640) and a.dtype == np.uint8
        arrays[d] = a
    return arrays, settings, {'manifest_sha256':sha(p),'maps':{d:m['outputs'][d]['sha256'] for d in DIRECTIONS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--pag0',type=Path)
    parser.add_argument('--pag50',type=Path)
    parser.add_argument('--candidate-gate-receipt',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Preserve existing result; use a new output path.')
    freeze = json.loads((ROOT/'w045-ink-evaluation-freeze.json').read_text())
    assert sha(freeze['rule']) == freeze['rule_sha256']
    for path,expected in freeze['inputs_sha256'].items():
        assert sha(path) == expected,path
    assert sha('/workspace/Scrolls/kit/auc.py') == freeze['kit_auc_sha256']
    assert sha('/workspace/Scrolls/kit/hpscore.py') == freeze['kit_hpscore_sha256']
    orientation_path = ROOT/'published-render-check/orientation-result.json'
    orientation = json.loads(orientation_path.read_text())
    assert orientation['official_raw_reversed_negative_normal']['passes_frozen_reproduction_bar'] is True
    assert orientation['official_raw_positive_normal']['passes_frozen_reproduction_bar'] is False
    recipes = {'original':args.original}
    registration_proof = None
    if args.pag0 is not None or args.pag50 is not None:
        if args.pag0 is None or args.pag50 is None or args.candidate_gate_receipt is None:
            raise ValueError('Both fixed phase recipes and a verified independent registration receipt are required.')
        gate = json.loads(args.candidate_gate_receipt.read_text())
        assert gate['registration_pass'] is True and gate['independent_review_pass'] is True
        assert gate['ink_rule_sha256'] == freeze['rule_sha256']
        assert gate['verified_artifacts_sha256'], 'Actual registration artifacts are required.'
        for path,expected in gate['verified_artifacts_sha256'].items():
            assert sha(path) == expected,path
        registration_proof = {'receipt_sha256':sha(args.candidate_gate_receipt),'artifacts':gate['verified_artifacts_sha256']}
        recipes.update(pag0=args.pag0,pag50=args.pag50)
    all_maps,proofs,settings = {},{},None
    for name,folder in recipes.items():
        arrays,current,proof = load_maps(folder,settings)
        settings = current
        proofs[name] = proof
        all_maps.update({name+'/'+d:a for d,a in arrays.items()})
    ink = np.load(ROOT/'w045-crop-ink.npy')
    supervised = np.load(ROOT/'w045-crop-supervision.npy')
    mask = auc._edge_mask(np,supervised,64)
    y,x,blocks,inverse,weights = bootstrap_weights(mask)
    common = mask & np.logical_and.reduce([a>0 for a in all_maps.values()])
    gf,sigma = hpscore._gaussian(),48/9.362
    kh = hpscore.high_pass(np,gf,np.where(common,ink,0).astype(float),common,sigma)
    hp_core = common & (gf(common.astype(float),2*sigma)>.999)
    hy,hx = np.nonzero(hp_core)
    hp_keys = (hy//107)*(mask.shape[1]//107+1)+hx//107
    hp_inverse = np.searchsorted(blocks,hp_keys)
    rows,auc_stats,hp_stats = {},{},{}
    for key,a in all_maps.items():
        point,draws = auc_bootstrap(a,ink,y,x,inverse,weights)
        auc_stats[key] = (point,draws)
        masked = np.where(common,a,0).astype(np.uint8)
        hp = hpscore.score_array(masked,ink,common,9.362)
        ph = hpscore.high_pass(np,gf,masked.astype(float),common,sigma)
        moments = correlation_moments(ph[hy,hx],kh[hy,hx],hp_inverse,len(blocks))
        hp_point = float(correlation_from_moments(moments.sum(0)))
        hp_draws = correlation_from_moments(weights@moments)
        hp_stats[key] = (hp_point,hp_draws)
        if hp['hp_r'] is not None:
            assert abs(hp_point-hp['hp_r']) <= .00005001
        rows[key] = {'auc':auc.score_array(a,ink,supervised,keep_zero=True,inner=64),
            'auc_bootstrap':interval(draws),'hp':hp,'hp_bootstrap':interval(hp_draws),
            'zero_fraction_primary':float((mask&(a==0)).sum()/mask.sum())}
    contrasts = {}
    for metric,stats in [('auc',auc_stats),('hp',hp_stats)]:
        depth = {}
        for name in recipes:
            for d in ('reverse','shuffle'):
                f,c = stats[name+'/forward'],stats[name+'/'+d]
                depth[name+'/forward-minus-'+d] = (f[0]-c[0],f[1]-c[1])
        phase = {}
        for name in ('pag0','pag50'):
            if name in recipes:
                a,b = stats[name+'/forward'],stats['original/forward']
                phase[name+'-original'] = (a[0]-b[0],a[1]-b[1])
        contrasts[metric] = {'depth_controls':simultaneous(depth),'phase_vs_original':simultaneous(phase)}
    spatial = {}
    eligible = {}
    for half,condition in [('upper',np.indices(mask.shape)[0]<320),('lower',np.indices(mask.shape)[0]>=320)]:
        m = mask&condition
        sy,sx = np.nonzero(m)
        count = len(np.unique((sy//107)*(mask.shape[1]//107+1)+sx//107))
        eligible[half] = (int((m&ink).sum())>=1000 and int((m&~ink).sum())>=1000 and count>=8)
        spatial[half] = {'eligible':eligible[half],'blocks':count,'metrics':{key:auc.score_array(a,ink,m,keep_zero=True) for key,a in all_maps.items()}}
    verdicts = {}
    for name in ('pag0','pag50'):
        if name not in recipes:
            continue
        a = contrasts['auc']['phase_vs_original'][name+'-original']
        coverage_ok = all(abs(rows[name+'/'+d]['zero_fraction_primary']-rows['original/'+d]['zero_fraction_primary'])<=.01 for d in DIRECTIONS)
        split_ok = all(eligible.values()) and all(spatial[h]['metrics'][name+'/forward']['auc']>spatial[h]['metrics']['original/forward']['auc'] for h in spatial)
        controls_ok = all(contrasts['auc']['depth_controls'][name+'/forward-minus-'+d]['simultaneous_ci95'] is not None and contrasts['auc']['depth_controls'][name+'/forward-minus-'+d]['simultaneous_ci95'][0]>0 for d in ('reverse','shuffle'))
        pixel_ok = coverage_ok and split_ok and controls_ok and a['difference']>=.01 and a['simultaneous_ci95'] is not None and a['simultaneous_ci95'][0]>0
        h = contrasts['hp']['phase_vs_original'][name+'-original']
        null = rows[name+'/forward']['hp']['null_max_abs']
        hp_controls = all(contrasts['hp']['depth_controls'][name+'/forward-minus-'+d]['simultaneous_ci95'] is not None and contrasts['hp']['depth_controls'][name+'/forward-minus-'+d]['simultaneous_ci95'][0]>0 for d in ('reverse','shuffle'))
        detail_ok = pixel_ok and h['simultaneous_ci95'] is not None and h['simultaneous_ci95'][0]>0 and null is not None and rows[name+'/forward']['hp']['hp_r']>null and hp_controls
        verdicts[name] = {'pixel_ranking_improvement_on_fixed_crop':bool(pixel_ok),'ink_detail_improvement_on_fixed_crop':bool(detail_ok),'coverage_ok':coverage_ok,'both_spatial_halves_improve':split_ok,'both_matched_auc_controls_pass':controls_ok}
    result = {'status':'full_fixed_recipe_readout' if len(recipes)==3 else 'original_baseline_only_phase_gate_pending',
        'scope':'One fixed held-out w045 crop; recipe effects only, no global generalization or legibility claim.',
        'rule_sha256':freeze['rule_sha256'],'evaluator_sha256':sha(__file__),
        'orientation_result_sha256':sha(orientation_path),'registration_proof':registration_proof,
        'input_sha256':freeze['inputs_sha256'],'inference_proofs':proofs,'reader_settings':settings,
        'primary_pixels':int(mask.sum()),'bootstrap_blocks':len(blocks),'bootstrap_draws':1000,
        'common_hp_pixels_before_erosion':int(common.sum()),'common_hp_core_pixels':int(hp_core.sum()),
        'rows':rows,'paired_simultaneous_contrasts':contrasts,'fixed_spatial_halves':spatial,'verdicts':verdicts}
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    verification = {'result_sha256':sha(args.out),'evaluator_sha256':sha(__file__),
        'rule_sha256':freeze['rule_sha256'],'all_frozen_input_and_map_hashes_verified':True}
    args.out.with_suffix('.verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'result_sha256':sha(args.out),'verdicts':verdicts}))


if __name__ == '__main__':
    main()
