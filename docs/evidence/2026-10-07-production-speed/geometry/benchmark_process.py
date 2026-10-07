"""Pre-timing amendment: process wall and inner complete-operation timings."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,hashlib,subprocess,statistics
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze():
    p=ROOT/'process-amendment.json'
    if p.exists():raise RuntimeError('Amendment already frozen')
    amendment=dict(reason='Parent requests cold complete-process wall time in addition to correct()/geometry timers; original rule retained unchanged',
        original_rule_sha256=sha(ROOT/'benchmark-rule.json'),harness_hashes={str(p):sha(p) for p in [Path(__file__),ROOT/'worker.py']},
        order_cases_options_endpoint_exactness='Unchanged from original rule:2cases,warmup+5alternatingpairs,1nullpair,tangentialnegative;1.5xschema2target;exactallreports/projections/outputhashes',
        timers=['parentprocesswallincludingPythonstartup/allimports/fulloperation/I/O/exit','innercorrectfulloperation','innergeometry'],
        resource='oneCPUaffinity inheritedbyallworkers; nootherheavyjobsduringfinaltiming',frozen_before_any_repeated_timing=True)
    p.write_text(json.dumps(amendment,indent=2)+'\n');print('FROZEN AMENDMENT',sha(p))
def run():
    amendment=json.loads((ROOT/'process-amendment.json').read_text());rule=json.loads((ROOT/'benchmark-rule.json').read_text())
    assert sha(ROOT/'benchmark-rule.json')==amendment['original_rule_sha256']
    for hashes in [amendment['harness_hashes'],rule['input_hashes'],rule['code_hashes']]:
        for p,h in hashes.items():assert sha(Path(p))==h,p
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    (ROOT/'worker-results').mkdir();rows=[];canonical={};negative=[]
    def once(case,version,label,negative_case=False):
        stem=ROOT/'worker-results'/(case['name']+'-'+label+'-'+version)
        out=ROOT/'process-runs'/case['name']/(label+'-'+version)
        command=[sys.executable,str(ROOT/'worker.py'),version,case['manifest'],str(out),str(stem),json.dumps(case['options']),'1' if negative_case else '0']
        started=time.perf_counter();subprocess.run(command,check=True,capture_output=True);wall=time.perf_counter()-started
        observed=json.loads(Path(str(stem)+'.json').read_text())
        if negative_case:
            assert observed['type']=='VerifyError' and 'normal offset' in observed['error'] and not observed['output_exists']
            negative.append(dict(version=version,**observed));return
        projection=dict(np.load(str(stem)+'.npz'));report=observed['report'];hashes=observed['output_hashes']
        assert json.loads((out/'report.json').read_text())==report
        if case['name'] not in canonical:canonical[case['name']]=(report,projection,hashes)
        else:
            previous=canonical[case['name']]
            assert report==previous[0] and hashes==previous[2],(case['name'],label,version,'report/output differs')
            assert projection.keys()==previous[1].keys() and all(np.array_equal(projection[k],v) for k,v in previous[1].items()),(case['name'],label,version,'projection differs')
        row=dict(case=case['name'],version=version,label=label,process_wall_seconds=wall,full_seconds=observed['full_seconds'],geometry_seconds=observed['geometry_seconds'],all_exact=True,output_hashes=hashes)
        rows.append(row);print(json.dumps(row),flush=True)
    for case in rule['cases']:
        once(case,'baseline','warmup');once(case,'optimized','warmup')
        for i,pair in enumerate(rule['order']):
            for version in pair:once(case,version,'repeat'+str(i))
    for version in ['baseline','optimized']:once(rule['control_cases'][0],version,'paritycontrol')
    for version in ['baseline','optimized']:once(rule['control_cases'][1],version,'paritycontrol',True)
    assert negative[0]['error']==negative[1]['error']
    stages=['process_wall_seconds','full_seconds','geometry_seconds']
    medians={case['name']:{version:{stage:statistics.median(r[stage] for r in rows if r['case']==case['name'] and r['version']==version and r['label']!='warmup') for stage in stages} for version in ['baseline','optimized']} for case in rule['cases']}
    ratios={name:{stage:data['baseline'][stage]/data['optimized'][stage] if data['optimized'][stage]>0 else None for stage in stages} for name,data in medians.items()}
    result=dict(amendment_sha256=sha(ROOT/'process-amendment.json'),original_rule_sha256=sha(ROOT/'benchmark-rule.json'),rows=rows,medians=medians,speedups=ratios,negative_controls=negative,all_exact=True,
        target_met=ratios['supervised_schema2']['process_wall_seconds']>=1.5)
    (ROOT/'process-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('SUMMARY',json.dumps(dict(medians=medians,speedups=ratios,all_exact=True,target_met=result['target_met'])))
if __name__=='__main__':freeze() if sys.argv[1:]==['--freeze'] else run()
