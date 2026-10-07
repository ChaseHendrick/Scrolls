from hp_common import ROOT,setup,operations
import sys,time,json,resource,os
variant,case=sys.argv[1:3];mods=setup(variant);ops=operations(mods,case)
# One complete warm pipeline per child, with process high-water memory recorded.
for fn in ops.values():fn()
result={'variant':variant,'case':case,'operation_times_s':{},'outputs':{},
 'cpu_affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None}
for name,fn in ops.items():
    start=time.perf_counter();value=fn();elapsed=time.perf_counter()-start
    result['operation_times_s'][name]=elapsed;result['outputs'][name]=value
if case=='real640':
    start=time.perf_counter();pipeline={name:fn() for name,fn in ops.items()};result['operation_times_s']['full_pipeline']=time.perf_counter()-start
    if pipeline!=result['outputs']:raise RuntimeError('Full pipeline output changed')
result['process_peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result['code_sha256']=mods[-1].sha256_file(ROOT/variant/'kit/hpscore.py')
print(json.dumps(result,sort_keys=True,allow_nan=False))
