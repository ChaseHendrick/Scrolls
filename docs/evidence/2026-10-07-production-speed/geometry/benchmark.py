"""Frozen alternating actual full-correct timing with exact result verification."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,importlib,importlib.util,json,time,hashlib,resource,statistics
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
MANIFEST=Path('/workspace/scrolls-env/supervised-surfacefix/actual-maps-manifest.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze():
    rule=ROOT/'benchmark-rule.json'
    if rule.exists():raise RuntimeError('Benchmark rule already frozen')
    initial=json.loads((ROOT/'profile-rule.json').read_text())
    cases=[dict(name='supervised_schema2',manifest=str(MANIFEST),options=initial['apply_config']),
           dict(name='earlier_schema1_control',manifest='/workspace/scrolls-env/geometry-validation/actual-maps-manifest.json',options=initial['apply_config'])]
    controls=[dict(name='schema2_displaced_reference_null',manifest=str(MANIFEST.parent/'null-manifest-axis0-shift300.json'),options=initial['apply_config']),
              dict(name='tangential_negative',manifest=str(MANIFEST.parent/'tangential-manifest.json'),options=initial['apply_config'])]
    secondary=Path(cases[1]['manifest']);data=json.loads(secondary.read_text())
    inputs=dict(initial['input_hashes'])
    input_paths=[secondary,secondary.parent/'geometry-validation-rule.json']
    old_options=json.loads((secondary.parent/'geometry-validation-rule.json').read_text())['thresholds']
    assert all(old_options[k]==v for k,v in initial['apply_config'].items())
    for record in [data['baseline'],data['reference']]+data['candidates']:
        input_paths += [secondary.parent/record['mesh']/f for f in ['x.tif','y.tif','z.tif','meta.json']]
        input_paths += [secondary.parent/value['path'] for value in record['maps'].values()]
    inputs.update({str(p):sha(p) for p in input_paths})
    for control in controls:
        manifest=Path(control['manifest']);data=json.loads(manifest.read_text());input_paths=[manifest]
        for record in [data['baseline'],data['reference']]+data['candidates']:
            input_paths += [manifest.parent/record['mesh']/f for f in ['x.tif','y.tif','z.tif','meta.json']]
            input_paths += [manifest.parent/value['path'] for value in record['maps'].values()]
        inputs.update({str(p):sha(p) for p in input_paths})
    paths=[Path(__file__),ROOT/'parity_check.py',ROOT/'parity-result.json',ROOT/'optimized-tests.log']
    for folder in ['baseline','optimized']:paths+=list((ROOT/folder/'kit').glob('*.py'))
    frozen=dict(scope='Actual32x32 supervisedPHerc0841 fullsurfacefixcorrect, includingmap/meshI/O; geometry stage separately timed; no reader/flattening timing',
        initial_profile_rule_sha256=sha(ROOT/'profile-rule.json'),input_hashes=inputs,code_hashes={str(p):sha(p) for p in paths},
        cases=cases,control_cases=controls,control_pairs_per_case=1,warmups_per_version_per_case=1,repeated_pairs_per_case=5,
        order=[['baseline','optimized'] if i%2==0 else ['optimized','baseline'] for i in range(5)],
        exactness='Compare all returned/saved report fields without exclusions, all5projection arrays includingUV/distances/abstentions, and alloutputfilehashes, everywarm/timedrun',
        acceptance='All exactness checks pass and schema2fullcorrect median speedup>=1.5x; schema1unchangedcontrolhasnobatchedgeometrycalls; nochangestoarithmeticseedties/heaporder/budget/radius/uniquenessorthresholds',
        threads=1,source_input_fixed=True)
    rule.write_text(json.dumps(frozen,indent=2)+'\n');print('FROZEN',sha(rule))
def load(folder):
    name='bench_'+folder
    spec=importlib.util.spec_from_file_location(name,ROOT/folder/'kit/__init__.py',submodule_search_locations=[str(ROOT/folder/'kit')])
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return importlib.import_module(name+'.surfacefix'),importlib.import_module(name+'._surface_geometry')
def run():
    rule=json.loads((ROOT/'benchmark-rule.json').read_text())
    for hmap in ['input_hashes','code_hashes']:
        for p,h in rule[hmap].items():assert sha(Path(p))==h,p
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    modules={folder:load(folder) for folder in ['baseline','optimized']};rows=[];canonical={}
    def once(case,folder,label):
        surface,geometry=modules[folder];original=geometry.project;capture={'seconds':0.,'projection':{}}
        def timed(*args,**kwargs):
            started=time.perf_counter();p=original(*args,**kwargs);capture['seconds']=time.perf_counter()-started
            capture['projection']={k:v.copy() for k,v in p.items()};return p
        geometry.project=timed
        out=ROOT/'runs'/case['name']/(label+'-'+folder);t=time.perf_counter()
        try:report=surface.correct(case['manifest'],out,**case['options'])
        finally:geometry.project=original
        full=time.perf_counter()-t
        hashes={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}
        saved=json.loads((out/'report.json').read_text());assert saved==report
        if case['name'] not in canonical:
            canonical[case['name']]=(report,capture['projection'],hashes)
            np.savez(ROOT/(case['name']+'-canonical-projection.npz'),**capture['projection'])
        else:
            reference=canonical[case['name']]
            assert report==reference[0],(case['name'],label,folder,'report differs')
            assert hashes==reference[2],(case['name'],label,folder,'output file hash differs')
            assert all(np.array_equal(capture['projection'][k],v) for k,v in reference[1].items()),(case['name'],label,folder,'projection differs')
        row=dict(case=case['name'],version=folder,label=label,full_seconds=full,geometry_seconds=capture['seconds'],all_exact=True,output_hashes=hashes)
        rows.append(row);print(json.dumps(row),flush=True)
    for case in rule['cases']:
        once(case,'baseline','warmup');once(case,'optimized','warmup')
        for i,pair in enumerate(rule['order']):
            for folder in pair:once(case,folder,'repeat'+str(i))
    once(rule['control_cases'][0],'baseline','paritycontrol')
    once(rule['control_cases'][0],'optimized','paritycontrol')
    negative=[]
    for folder in modules:
        out=ROOT/'runs'/('tangential-negative-'+folder);surface,_=modules[folder]
        try:surface.correct(rule['control_cases'][1]['manifest'],out,**rule['control_cases'][1]['options'])
        except Exception as exc:
            negative.append(dict(version=folder,type=type(exc).__name__,error=str(exc),output_exists=out.exists()))
        else:raise AssertionError('Tangential negative was accepted')
    assert negative[0]['type']==negative[1]['type']=='VerifyError'
    assert negative[0]['error']==negative[1]['error'] and 'normal offset' in negative[0]['error']
    assert not any(item['output_exists'] for item in negative)
    medians={case['name']:{folder:{stage:statistics.median(r[stage] for r in rows if r['case']==case['name'] and r['version']==folder and r['label']!='warmup') for stage in ['full_seconds','geometry_seconds']} for folder in modules} for case in rule['cases']}
    gains={name:{stage:1-data['optimized'][stage]/data['baseline'][stage] if data['baseline'][stage]>0 else None for stage in ['full_seconds','geometry_seconds']} for name,data in medians.items()}
    result=dict(rule_sha256=sha(ROOT/'benchmark-rule.json'),rows=rows,medians=medians,reductions=gains,negative_controls=negative,
        full_schema2_speedup=medians['supervised_schema2']['baseline']['full_seconds']/medians['supervised_schema2']['optimized']['full_seconds'],
        all_exact=True,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    (ROOT/'benchmark-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('SUMMARY',json.dumps(dict(medians=medians,reductions=gains,all_exact=True)))
if __name__=='__main__':freeze() if sys.argv[1:]==['--freeze'] else run()
