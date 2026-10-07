import os
os.environ.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
import sys,time,json,cProfile,pstats,io
from pathlib import Path
root=Path('/workspace/scrolls-env/production-speed');sys.path.insert(0,str(root/'scoring-baseline'))
from kit import auc,hpscore,rowscore,provenance
import zarr
zarr.config.set({'async.concurrency':1,'threading.max_workers':1})
base=Path('/workspace/scrolls-env/supervised-surfacefix/reader-baseline')
forward=base/'forward_s42.tif';reverse=base/'reverse_s42.tif';labels=Path('/workspace/scrolls-env/geometry-validation/labels-w00')
kw={'prediction':forward,'labels':labels/'inklabels.zarr','mask':labels/'supervision.zarr','control':reverse,'level':'2','crop':(2720,3360,2720,3360),'surface_shape':(4220,4760),'inner':64}
freeze={'baseline_commit':__import__('subprocess').check_output(['git','-C','/workspace/Scrolls','rev-parse','HEAD'],text=True).strip(),'sources':{p:provenance.sha256_file(root/'scoring-baseline'/p) for p in ('kit/auc.py','kit/hpscore.py','kit/rowscore.py')},'inputs':[provenance.fingerprint(p) for p in (forward,reverse,labels/'inklabels.zarr',labels/'supervision.zarr')],'crop':kw['crop'],'surface_shape':kw['surface_shape'],'inner':64,'bootstrap_draws':1000,'block_px':107,'seed':20261007,'keep_zero':True,'cpu_affinity':list(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None}
(root/'scoring-input-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
operations={'auc_files':lambda:auc.score_files(**kw,keep_zero=True,bootstrap=1000,block_px=107,compare=reverse,seed=20261007),'hp_files':lambda:hpscore.score_files(**kw,voxel_um=9.366),'rows_files':lambda:rowscore.score_files([forward],9.366,reverse=[reverse])}
result={};results={}
for name,fn in operations.items():
 profiler=cProfile.Profile(); t=time.perf_counter();profiler.enable();value=fn();profiler.disable();elapsed=time.perf_counter()-t
 stream=io.StringIO();pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(18)
 result[name]={'elapsed_s':elapsed,'profile':stream.getvalue()};results[name]=value
(root/'scoring-initial-profile.json').write_text(json.dumps(result,indent=2)+'\n');(root/'scoring-baseline-results.json').write_text(json.dumps(results,indent=2)+'\n')
for k,v in result.items():print(k,v['elapsed_s']);print(v['profile'])
