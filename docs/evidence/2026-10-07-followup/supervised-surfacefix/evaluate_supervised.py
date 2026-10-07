"""Frozen label audit after one immutable correction selection and eight null searches."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
import argparse,hashlib,importlib.util,json
from pathlib import Path
import sys
sys.path.insert(0,'/workspace/Scrolls')
import numpy as np
import tifffile
from kit import auc,hpscore
R=Path('/workspace/scrolls-env/supervised-surfacefix')
RULE_SHA='a897301ed8a1ffe5099c0e9ff85cdff9affcc2a956962b64f85f32a05f618f26'
MATH=Path('/workspace/scrolls-env/phase-reconstruction/evaluate_w045.py')
MATH_SHA='a95e703eb73dcfe02a97b48184cbf1ef965ef1872219a3d0774780b7b9d4e72c'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(MATH)==MATH_SHA
spec=importlib.util.spec_from_file_location('frozen_math',MATH);math=importlib.util.module_from_spec(spec);spec.loader.exec_module(math)
DIRECTIONS=('forward','reverse','shuffle')
def dump(path,record):
    with path.open('x') as f:json.dump(record,f,indent=2,allow_nan=False);f.write('\n')
def edited_support(before,after,scale,shape=(640,640)):
    changed=np.any(before!=after,axis=2)
    yy=np.floor((np.arange(shape[0])+.5)*scale[1]).astype(int)
    xx=np.floor((np.arange(shape[1])+.5)*scale[0]).astype(int)
    valid=(yy[:,None]>=0)&(xx[None,:]>=0)&(yy[:,None]<changed.shape[0]-1)&(xx[None,:]<changed.shape[1]-1)
    yr=np.clip(yy,0,changed.shape[0]-2)[:,None];xc=np.clip(xx,0,changed.shape[1]-2)[None,:]
    support=changed[yr,xc]|changed[yr+1,xc]|changed[yr,xc+1]|changed[yr+1,xc+1]
    return support&valid,int(changed.sum())
def finite(v):return float(v) if np.isfinite(v) else None
def assert_frozen_settings(settings,rule):
    expected_settings={'villa_revision':'e0bbb8b40a2db58b1d71864f286eb85717e59e64','checkpoint_sha256':rule['reader']['checkpoint_sha256'],'selected_source_layers':list(range(6,23)),'shuffle_seed':rule['reader']['shuffle_seed'],'stride':rule['reader']['stride'],'batch_size':rule['reader']['batch'],'blend_mode':'hann','amp':'disabled','mirror_tta':rule['reader']['tta'],'preprocessing':'tifxyz_robust'}
    assert rule['reader']['model']=='d9v2' and rule['reader']['central_planes']==17 and rule['reader']['precision']=='fp32'
    assert settings==expected_settings,'Reader settings differ from authoritative frozen model/precision/controls.'

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--combined',type=Path);ap.add_argument('--combined-render-proof',type=Path);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    rule_path=R/'label-evaluation-rule.json';assert sha(rule_path)==RULE_SHA;rule=json.loads(rule_path.read_text())
    for p,d in rule['input_sha256'].items():
        p=Path(p) if p.startswith('/') else Path('/workspace/Scrolls')/p
        assert sha(p)==d,p
    amendment_path=R/'schema2-code-amendment.json';amendment=json.loads(amendment_path.read_text())
    for p,d in amendment['input_sha256'].items():assert sha(p)==d,p
    actual_manifest_path=R/'actual-maps-manifest.json';manifest=json.loads(actual_manifest_path.read_text())
    assert manifest['frozen_rules'][rule_path.name]==RULE_SHA
    assert manifest['frozen_rules'][amendment_path.name]==sha(amendment_path)
    report_path=R/'actual-apply/report.json';report=json.loads(report_path.read_text())
    null_path=R/'actual-validation-with-nulls.json';nulls=json.loads(null_path.read_text())
    assert len(nulls['nulls'])==8 and nulls['normal']['accepted_regions']==report['accepted_regions']
    for mesh,r in report['input_hashes'].items():
        for item in r['maps'].values():assert sha(item['path'])==item['sha256']
    accepted=report['accepted_regions']
    if accepted and args.combined is None:raise ValueError('Accepted geometry requires actual official combined rerender and all3 matched maps before scoring.')
    if not accepted and args.combined is not None:raise ValueError('No corrections were accepted; preserve the unchanged baseline, no unnecessary combined inference.')
    recipes={n:R/('reader-'+n) for n in ('baseline','minus1','plus1')}
    if accepted:recipes['combined']=args.combined
    reference,settings,reference_proof=math.load_maps(R/'reader-reference')
    assert_frozen_settings(settings,rule)
    orchestration=json.loads((R/'reader-orchestration-freeze.json').read_text())
    expected_shuffle=np.array(list(range(6,23)))[np.random.default_rng(rule['reader']['shuffle_seed']).permutation(17)].tolist()
    for tag in ('baseline','reference','minus1','plus1'):
        m=json.loads((R/('reader-'+tag)/'inference_manifest.json').read_text())
        assert m['shuffle_source_layers']==expected_shuffle and m['checkpoint_state']=='ema_model' and m['device']=='cpu'
        assert m['layer_sha256']=={Path(p).name:d for p,d in orchestration['canonical_layers_sha256'][tag].items()}
    maps,proofs={}, {'reference':reference_proof}
    for tag,p in recipes.items():
        z,current,proof=math.load_maps(p,settings);proofs[tag]=proof;maps.update({tag+'/'+d:a for d,a in z.items()})
    source=R/'w00-crop.tifxyz';corrected=R/'actual-apply/corrected.tifxyz'
    xyz=lambda p:np.stack([tifffile.imread(p/(d+'.tif')) for d in 'xyz'],axis=2)
    before,after=xyz(source),xyz(corrected)
    support,changed=edited_support(before,after,json.loads((source/'meta.json').read_text())['scale'])
    combined_render_proof=None
    if accepted:
        if args.combined_render_proof is None:raise ValueError('Actual official combined geometry-to-layers proof is required.')
        proof=json.loads(args.combined_render_proof.read_text())
        assert Path(proof['corrected_mesh']).resolve()==corrected.resolve()
        assert proof['canonical_depth_order']=='published_minus_N_from_reversed_official_plus_N'
        assert proof['surfacefix_report_sha256']==sha(report_path)
        assert proof['implementation_amendment_sha256']==sha(amendment_path)
        assert proof['ct_cache_receipt_sha256']==sha(R/'ct-cache-receipt.json')
        assert proof['engine_sha256']==json.loads((R/'rule.json').read_text())['render']['official_binary_sha256']
        for name,d in proof['corrected_mesh_sha256'].items():assert sha(corrected/name)==d
        assert set(proof['corrected_mesh_sha256'])=={'x.tif','y.tif','z.tif','meta.json'}
        assert sha(proof['renderer_receipt'])==proof['renderer_receipt_sha256']
        cm=json.loads((args.combined/'inference_manifest.json').read_text())
        assert cm['layer_sha256']==proof['canonical_layer_sha256']
        assert cm['shuffle_source_layers']==expected_shuffle and cm['checkpoint_state']=='ema_model' and cm['device']=='cpu'
        for name,d in proof['canonical_layer_sha256'].items():assert sha(Path(proof['canonical_layers_dir'])/name)==d
        combined_render_proof={'receipt_sha256':sha(args.combined_render_proof),'proof':proof}
    assert bool(changed)==bool(accepted)
    ink=np.load(R/'source-ink.npy');sup=np.load(R/'source-supervision.npy');assert ink.shape==sup.shape==(640,640)
    mask=auc._edge_mask(np,sup,64);y,x,blocks,inverse,weights=math.bootstrap_weights(mask)
    common=mask&np.logical_and.reduce([a>0 for a in maps.values()]);gf=hpscore._gaussian();sigma=48/9.366
    kh=hpscore.high_pass(np,gf,np.where(common,ink,0).astype(float),common,sigma)
    hp_core=common&(gf(common.astype(float),2*sigma)>.999)
    def stats(a,cohort):
        sy,sx=np.nonzero(cohort);keys=(sy//107)*(mask.shape[1]//107+1)+sx//107;inv=np.searchsorted(blocks,keys)
        point,draws=math.auc_bootstrap(a,ink,sy,sx,inv,weights)
        masked=np.where(common,a,0).astype(np.uint8);ph=hpscore.high_pass(np,gf,masked.astype(float),common,sigma)
        m=hp_core&cohort;hy,hx=np.nonzero(m);hi=np.searchsorted(blocks,(hy//107)*(mask.shape[1]//107+1)+hx//107)
        moments=math.correlation_moments(ph[hy,hx],kh[hy,hx],hi,len(blocks));hp_point=math.correlation_from_moments(moments.sum(0));hp_draws=math.correlation_from_moments(weights@moments)
        null=[]
        for s in (150,300,-300):
            s=int(round(s*9.362/9.366));both=m&np.roll(m,s,0);r=hpscore._r(np,ph[both],np.roll(kh,s,0)[both])
            if r is not None:null.append(abs(r))
        hp={'hp_r':finite(hp_point),'null_max_abs':max(null) if null else None,'usable_null_shifts':len(null),'px':int(m.sum()),'same_global_smoothing_support':True}
        if np.array_equal(cohort,mask):
            expected=hpscore.score_array(masked,ink,common,9.366)
            if expected['hp_r'] is not None:assert abs(hp['hp_r']-expected['hp_r'])<=.00005001
        row={'auc':auc.score_array(a,ink,cohort,keep_zero=True),'auc_bootstrap':math.interval(draws),'hp':hp,'hp_bootstrap':math.interval(hp_draws),'zero_fraction':float((cohort&(a==0)).sum()/cohort.sum()) if cohort.any() else None}
        return row,{'auc':(point,draws),'hp':(hp_point,hp_draws)}
    rows,whole_stats={},{}
    for key,a in maps.items():rows[key],whole_stats[key]=stats(a,mask)
    candidate_contrasts={};depth_contrasts={};combined_contrasts={}
    for metric in ('auc','hp'):
        cand={};depth={}
        for name in recipes:
            for d in ('reverse','shuffle'):
                f,c=whole_stats[name+'/forward'][metric],whole_stats[name+'/'+d][metric]
                depth[name+'/forward-minus-'+d]=(f[0]-c[0],f[1]-c[1])
        for name in ('minus1','plus1'):
            a,b=whole_stats[name+'/forward'][metric],whole_stats['baseline/forward'][metric]
            cand[name+'-baseline']=(a[0]-b[0],a[1]-b[1])
        candidate_contrasts[metric]=math.simultaneous(cand);depth_contrasts[metric]=math.simultaneous(depth)
        if accepted:
            a,b=whole_stats['combined/forward'][metric],whole_stats['baseline/forward'][metric]
            combined_contrasts[metric]=math.simultaneous({'combined-baseline':(a[0]-b[0],a[1]-b[1])})['combined-baseline']
    halves={}
    for name,c in [('upper',np.indices(mask.shape)[0]<320),('lower',np.indices(mask.shape)[0]>=320)]:
        m=mask&c;ni=int((m&ink).sum());nb=int((m&~ink).sum())
        halves[name]={'eligible':ni>=1000 and nb>=1000,'ink_px':ni,'background_px':nb,'metrics':{k:auc.score_array(a,ink,m,keep_zero=True) for k,a in maps.items()}}
    edited_rows={};edited_contrasts={}
    if (mask&support).any():
        es={}
        for key,a in maps.items():edited_rows[key],es[key]=stats(a,mask&support)
        if accepted:
            for metric in ('auc','hp'):
                a,b=es['combined/forward'][metric],es['baseline/forward'][metric]
                edited_contrasts[metric]=math.simultaneous({'combined-baseline':(a[0]-b[0],a[1]-b[1])})['combined-baseline']
    success=False;detail=False;coverage_ok=None;split_ok=None;controls_ok=None
    if accepted:
        coverage_ok=all(abs(rows['combined/'+d]['zero_fraction']-rows['baseline/'+d]['zero_fraction'])<=.01 for d in DIRECTIONS)
        split_ok=all(h['eligible'] and h['metrics']['combined/forward']['auc']>h['metrics']['baseline/forward']['auc'] for h in halves.values())
        controls_ok=all(depth_contrasts['auc']['combined/forward-minus-'+d]['simultaneous_ci95'] is not None and depth_contrasts['auc']['combined/forward-minus-'+d]['simultaneous_ci95'][0]>0 for d in ('reverse','shuffle'))
        gain=combined_contrasts['auc'];success=coverage_ok and split_ok and controls_ok and gain['difference'] is not None and gain['difference']>=.01 and gain['simultaneous_ci95'] is not None and gain['simultaneous_ci95'][0]>0
        gain=combined_contrasts['hp'];hp=rows['combined/forward']['hp'];hc=all(depth_contrasts['hp']['combined/forward-minus-'+d]['simultaneous_ci95'] is not None and depth_contrasts['hp']['combined/forward-minus-'+d]['simultaneous_ci95'][0]>0 for d in ('reverse','shuffle'))
        detail=success and gain['simultaneous_ci95'] is not None and gain['simultaneous_ci95'][0]>0 and hp['null_max_abs'] is not None and hp['hp_r']>hp['null_max_abs'] and hc
    result={'status':'combined_correction_label_audit_completed' if accepted else 'no_accepted_corrections_descriptive_offset_audit_only','scope':'One label-selected public known-sheet crop. Candidate offset scores are descriptive only and never choose or retry a correction. No independent-scroll or legibility claim.','label_rule_sha256':RULE_SHA,'evaluator_sha256':sha(__file__),'frozen_math_sha256':MATH_SHA,'actual_manifest_sha256':sha(actual_manifest_path),'actual_apply_report_sha256':sha(report_path),'null_results_sha256':sha(null_path),'code_amendment_sha256':sha(amendment_path),'inference_proofs':proofs,'combined_render_proof':combined_render_proof,'primary_supervised_pixels':int(mask.sum()),'common_hp_core_pixels':int(hp_core.sum()),'bootstrap_draws':1000,'bootstrap_blocks':len(blocks),'rows':rows,'candidate_descriptive_contrasts':candidate_contrasts,'depth_controls':depth_contrasts,'fixed_spatial_halves':halves,'combined_vs_baseline':combined_contrasts,'accepted_regions':accepted,'changed_native_points':changed,'edited_support_supervised_pixels':int((mask&support).sum()),'edited_support_rows':edited_rows,'edited_support_combined_vs_baseline':edited_contrasts,'correction_success_gate':{'pixel_ranking_improvement':bool(success),'ink_detail_improvement':bool(detail),'coverage_ok':coverage_ok,'both_halves_improve':split_ok,'matched_auc_controls_pass':controls_ok},'nulls':nulls['nulls']}
    dump(args.out,result);dump(args.out.with_suffix('.verification.json'),{'result_sha256':sha(args.out),'evaluator_sha256':sha(__file__),'all_frozen_inputs_and_actual_apply_map_hashes_verified':True})
    print(json.dumps({'status':result['status'],'result_sha256':sha(args.out),'gate':result['correction_success_gate'],'forward_auc':{n:rows[n+'/forward']['auc']['auc'] for n in recipes}}))
if __name__=='__main__':main()
