from hp_common import setup,cases
import sys,resource,json,time
variant,case=sys.argv[1:3];setup(variant)
from kit import cli,hpscore
original_score=hpscore.score_files
operation={}
def timed_score(*a,**kw):
    start=time.perf_counter()
    result=original_score(*a,**kw)
    operation["hp_operation_s"]=time.perf_counter()-start
    return result
hpscore.score_files=timed_score
cfg=cases()[case]
args=['hpscore',cfg['prediction'],'--control',cfg['control'],'--labels',cfg['labels'],
 '--mask',cfg['mask'],'--voxel-um',str(cfg['voxel_um']),'--level',cfg['level'],
 '--crop',*map(str,cfg['crop']),'--surface-shape',*map(str,cfg['surface_shape']),
 '--inner',str(cfg['inner']),'--json']
try:code=cli.main(args)
finally:print('RSS_JSON '+json.dumps({'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**operation}),file=sys.stderr)
raise SystemExit(code)
