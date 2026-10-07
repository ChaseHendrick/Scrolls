from hp_common import ROOT,setup,cases,operations
import time,json,cProfile,pstats,io,resource,hashlib
mods=setup('scoring-baseline');prov=mods[-1]
freeze={'baseline_commit':'c43c41a59ac3793b9a653fa236165f6f6b9d47a4','cases':cases(),
 'sources':{p:prov.sha256_file(ROOT/'scoring-baseline'/p) for p in ('kit/auc.py','kit/hpscore.py','kit/rowscore.py')},
 'inputs':[prov.fingerprint(path) for path in sorted({cfg[k] for cfg in cases().values() for k in ('prediction','control','labels','mask')})]}
(ROOT/'hp-input-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
profiles={};values={}
for case in cases():
    ops=operations(mods,case)
    for fn in ops.values():fn()
    profiles[case]={};values[case]={}
    for name,fn in ops.items():
        p=cProfile.Profile();start=time.perf_counter();p.enable();val=fn();p.disable();elapsed=time.perf_counter()-start
        s=io.StringIO();pstats.Stats(p,stream=s).sort_stats('cumulative').print_stats(15)
        profiles[case][name]={'elapsed_s':elapsed,'profile':s.getvalue()};values[case][name]=val
        print(case,name,elapsed,flush=True)
profiles['process_peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
(ROOT/'hp-baseline-profile.json').write_text(json.dumps(profiles,indent=2)+'\n')
(ROOT/'hp-baseline-results.json').write_text(json.dumps(values,indent=2)+'\n')
