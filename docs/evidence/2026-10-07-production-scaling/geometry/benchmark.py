"""Frozen v2 incremental benchmark against c43c41a with exact-output checks."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,hashlib,subprocess,statistics
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze():
    p=ROOT/'benchmark-rule.json'
    if p.exists():raise RuntimeError('Benchmark rule already frozen')
    initial=json.loads((ROOT/'profile-rule.json').read_text());options=initial['options'];base=Path('/workspace/scrolls-env/supervised-surfacefix')
    cases=[dict(name='actual_full_correct',mode='correct',manifest=str(base/'actual-maps-manifest.json'),options=options),
        dict(name='larger_geometry',mode='geometry',source='/workspace/scrolls-env/geometry-validation/w00.tifxyz',source_crop=initial['larger']['source_native_crop'],
             reference='/workspace/scrolls-env/geometry-validation/ag896.tifxyz',radius_um=50,voxel_um=9.366)]
    controls=[dict(name='displaced_reference_null',mode='correct',manifest=str(base/'null-manifest-axis0-shift300.json'),options=options),
              dict(name='schema1_unchanged',mode='correct',manifest='/workspace/scrolls-env/geometry-validation/actual-maps-manifest.json',options=options),
              dict(name='tangential_negative',mode='negative',manifest=str(base/'tangential-manifest.json'),options=options)]
    inputs=dict(initial['input_hashes'])
    for control in controls:
        m=Path(control['manifest']);data=json.loads(m.read_text());files=[m]
        for r in [data['baseline'],data['reference']]+data['candidates']:
            files += [m.parent/r['mesh']/f for f in ['x.tif','y.tif','z.tif','meta.json']]
            files += [m.parent/v['path'] for v in r['maps'].values()]
        inputs.update({str(f):sha(f) for f in files})
    files=[Path(__file__),ROOT/'worker.py',ROOT/'parity-rule-final.json',ROOT/'parity-result-final.json',ROOT/'geometry-regression-final-tests.log']
    for version in ['baseline','optimized']:files+=list((ROOT/version/'kit').glob('*.py'))+[ROOT/version/'tests/test_surface_geometry.py']
    rule=dict(baseline_revision='c43c41a',source_fix_amendment_sha256=sha(ROOT/'source-fix-amendment.json'),input_hashes=inputs,code_hashes={str(f):sha(f) for f in files},
        cases=cases,controls=controls,warmups_per_version_per_case=1,repeated_pairs_per_case=5,
        order=[['baseline','optimized'] if i%2==0 else ['optimized','baseline'] for i in range(5)],
        timers=['coldprocesswallallimports/I/O/fulloperation/exit','innercorrectcompleteoperationorproject','geometryonly'],peak_rss='resource.getrusagein eachcoldworker',
        exactness='Allreportfields,all5projectionarraysandalloutputfilehashes identical; negativeerror andoutputabsence identical; no tolerance/exclusions',
        acceptance='Exactness required; assessincrementalmedian/pairedvariabilityversusc43c41a; no historicaltotalspeedupclaimwithoutmatchedrerun',
        resources=dict(threads=1,quiet_window_required=True,no_network=True),frozen_before_repeated_timing=True)
    p.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',sha(p))
def run():
    rule=json.loads((ROOT/'benchmark-rule.json').read_text())
    for hashes in [rule['input_hashes'],rule['code_hashes']]:
        for p,h in hashes.items():assert sha(Path(p))==h,p
    assert sha(ROOT/'source-fix-amendment.json')==rule['source_fix_amendment_sha256']
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))});(ROOT/'worker-results').mkdir()
    rows=[];canonical={};negative=[]
    def once(case,version,label):
        stem=ROOT/'worker-results'/(case['name']+'-'+label+'-'+version);out=ROOT/'runs'/case['name']/(label+'-'+version)
        command=[sys.executable,str(ROOT/'worker.py'),version,json.dumps(case),str(out),str(stem)]
        t=time.perf_counter();subprocess.run(command,check=True,capture_output=True);wall=time.perf_counter()-t
        value=json.loads(Path(str(stem)+'.json').read_text())
        if case['mode']=='negative':
            assert value['type']=='VerifyError' and 'normal offset' in value['error'] and not value['output_exists']
            negative.append(dict(version=version,**value));return
        projection=dict(np.load(str(stem)+'.npz'));report=value['report'];hashes=value['output_hashes']
        if case['mode']=='correct':assert json.loads((out/'report.json').read_text())==report
        if case['name'] not in canonical:canonical[case['name']]=(report,projection,hashes)
        else:
            old=canonical[case['name']];assert old[0]==report and old[2]==hashes,(case['name'],label,version,'report/output differs')
            assert old[1].keys()==projection.keys() and all(np.array_equal(projection[k],v) for k,v in old[1].items()),(case['name'],label,version,'projection differs')
        row=dict(case=case['name'],version=version,label=label,process_wall_seconds=wall,full_seconds=value['full_seconds'],geometry_seconds=value['geometry_seconds'],
            peak_rss_bytes=value['peak_rss_bytes'],all_exact=True,output_hashes=hashes)
        rows.append(row);print(json.dumps(row),flush=True)
    for case in rule['cases']:
        for version in ['baseline','optimized']:once(case,version,'warmup')
        for i,pair in enumerate(rule['order']):
            for version in pair:once(case,version,'repeat'+str(i))
    for control in rule['controls']:
        for version in ['baseline','optimized']:once(control,version,'paritycontrol')
    assert negative[0]['error']==negative[1]['error']
    stages=['process_wall_seconds','full_seconds','geometry_seconds','peak_rss_bytes']
    medians={c['name']:{v:{s:statistics.median(r[s] for r in rows if r['case']==c['name'] and r['version']==v and r['label']!='warmup') for s in stages} for v in ['baseline','optimized']} for c in rule['cases']}
    ratios={n:{s:d['baseline'][s]/d['optimized'][s] if d['optimized'][s]>0 else None for s in stages} for n,d in medians.items()}
    result=dict(rule_sha256=sha(ROOT/'benchmark-rule.json'),baseline_revision=rule['baseline_revision'],rows=rows,medians=medians,speedups=ratios,negative_controls=negative,all_exact=True)
    (ROOT/'benchmark-result.json').write_text(json.dumps(result,indent=2)+'\n');print('SUMMARY',json.dumps(dict(medians=medians,speedups=ratios,all_exact=True)))
if __name__=='__main__':freeze() if sys.argv[1:]==['--freeze'] else run()
