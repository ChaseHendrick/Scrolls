"""Frozen post-pilot boundary and cross-recipe transportability diagnostics."""
from pathlib import Path
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import json,resource,sys,time
import numpy as np
from physics_filter_pilot import OUT,ROOT,arrays,centered,prepare_grid,fit_transfer,predict,summary
from register_ct_pilot import digest,load_patch

RULE=OUT/'supplement-rule.json'

def freeze():
    if RULE.exists():raise RuntimeError('Refusing frozen addendum overwrite')
    rule={'schema':1,'scope':'Post-pilot robustness diagnostics fixed after main result; no independent discovery claim',
          'script_sha256':digest(Path(__file__).read_bytes()),'main_rule_sha256':digest((OUT/'rule.json').read_bytes()),
          'main_result_sha256':digest((OUT/'result.json').read_bytes()),
          'registration_result_sha256':digest((ROOT/'registration-pilot-result.json').read_bytes()),
          'boundary':'Same cube0 coefficients and means; reflect-pad heldback pag0 cube by32 and64vox, apply exactly32samephysical-frequencybins without refitting; crop center96 for score',
          'boundary_gate':{'max_correlation_drop':.002,'max_normalized_rms_increase':.02},
          'transportability':'Use original128cubes already selected by geometry; extract pag50 target128 at prereported local structural shift+1z oncube0 and-1z oncube1. Report raw original→pag50, reuse frozenpag0→pag50operator, and newly trained original→pag50operator oncube0 testedcube1.',
          'transportability_limit':'Local shift audits only; global original→phase translation gate failed. No mesh/render/label inference permitted from these diagnostics.',
          'global_and_all_mean_offset_fits':'Onlycube0; cube1 mean/std allowed onlyas descriptive metrics, neverfitpredictor',
          'fixed_prediction_gate':{'maximum_normalized_rms':.15,'minimum_correlation':.95},
          'resources':{'threads':1,'max_peak_rss_bytes':2*1024**3,'network_bytes':0}}
    RULE.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',digest(RULE.read_bytes()))

def run():
    rule=json.loads(RULE.read_text());main=json.loads((OUT/'result.json').read_text());mrule=json.loads((OUT/'rule.json').read_text())
    for path,key in [(Path(__file__),'script_sha256'),(OUT/'rule.json','main_rule_sha256'),(OUT/'result.json','main_result_sha256'),(ROOT/'registration-pilot-result.json','registration_result_sha256')]:
        assert digest(path.read_bytes())==rule[key]
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    started=time.monotonic();raw=arrays(mrule)
    a=[centered(x) for x in raw['pag0']];b=[centered(x) for x in raw['pag50']]
    radius,bins,window=prepare_grid()
    response,gain,off,am,bm=fit_transfer(a[0],b[0],bins,window)
    assert np.max(np.abs(response-main['radial_transfer']))<1e-12
    boundary=[]
    for pad in [32,64]:
        ap=np.pad(a[1],pad,mode='reflect');pradius,pbins,pwindow=prepare_grid(len(ap))
        pred=predict(ap,response,pbins,am,bm);stats=summary(pred,b[1])
        stats.update(reflection_pad_vox=pad,correlation_drop=main['primary']['correlation']-stats['correlation'],normalized_rms_increase=stats['normalized_rms']-main['primary']['normalized_rms'])
        stats['pass']=stats['correlation_drop']<=.002 and stats['normalized_rms_increase']<=.02
        boundary.append(stats)
        del ap,pradius,pbins,pwindow,pred
    source=json.loads((ROOT/'registration-rule.json').read_text())
    original=[load_patch(next(r for r in source['requests'] if r['volume']=='original' and r['patch']==p)).astype(np.float32) for p in range(2)]
    shifted=[]
    for p,shift in enumerate([1,-1]):
        s=raw['pag50'][p];shifted.append(s[32+shift:160+shift,32:160,32:160].astype(np.float32))
    transport={'local_original_to_pag50_shift_zyx':[[1,0,0],[-1,0,0]],'unaltered_original_vs_pag50':summary(original[1],shifted[1]),
               'reuse_pag0_to_pag50_response':summary(predict(original[1],response,bins,am,bm),shifted[1])}
    rr,gg,oo,aa,bb=fit_transfer(original[0],shifted[0],bins,window)
    transport['new_original_to_pag50_response']=summary(predict(original[1],rr,bins,aa,bb),shifted[1])
    transport['new_original_to_pag50_affine_baseline']=summary(gg*original[1]+oo,shifted[1])
    transport['new_radial_response']=rr.tolist()
    for key in ['reuse_pag0_to_pag50_response','new_original_to_pag50_response']:
        row=transport[key];row['meets_main_prediction_gate']=row['normalized_rms']<=.15 and row['correlation']>=.95
    result={'supplement_rule_sha256':digest(RULE.read_bytes()),'boundary':boundary,'boundary_all_pass':all(r['pass'] for r in boundary),'transportability':transport,
            'limits':rule['transportability_limit'],'elapsed_seconds':time.monotonic()-started,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
    (OUT/'supplement-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--freeze']:freeze()
    else:run()
