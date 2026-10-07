"""Frozen geometry-only 50 um correspondence stress test for PR1996 masks."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,resource,importlib.util,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,'/workspace/Scrolls')
from kit.surfacefix import _mesh,_roundoff
from kit._surface_geometry import project

ROOT=Path(__file__).resolve().parent
SOURCE=Path('/workspace/scrolls-env/pr1996-review/grow_track_graph.py')
INPUT=Path('/workspace/scrolls-env/geometry-validation')
GEOMETRY=Path('/workspace/Scrolls/kit/_surface_geometry.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    p=ROOT/'correspondence-rule.json'
    if p.exists():raise RuntimeError('No frozen rule overwrite')
    rule={'schema':1,'scope':'Geometry-only small stress test, no reader/label/target inference',
          'hashes':{str(f):sha(f) for f in [SOURCE,GEOMETRY,Path(__file__),ROOT/'rule.json',ROOT/'result.json']},
          'selection':'For eachmesh sorted validnativevertex indices, select48evenlyspaced positions floor(i*(L-1)/47). No geometryerror-based selection.',
          'factors':[2,4],'modes':['erode','support'],'gap_um':50.,'voxel_um':9.366,
          'tolerance':'Existing source/nativefloat32 roundoff tolerance frompublished mesh. Actual upperdistance<=50um required unchanged.',
          'readout':'Report all48samples percondition: certifiedeligible/ambiguous/unresolved/no-match anddistancequantiles. Supported occupancy doesnotimplyeligible correction/referencecoverage. No timing orinkgainclaim.',
          'limits':'Source native20vox grid;40/80vox resampling stress, notParis4spacing5/10 orflattenCPU reproduction. Samplecoverage geometric only; mapsnotprovided.',
          'resources':{'threads':1,'max_peak_rss_bytes':2*1024**3,'network_bytes':0}}
    p.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',sha(p))

def run():
    rule=json.loads((ROOT/'correspondence-rule.json').read_text())
    for path,h in rule['hashes'].items():assert sha(Path(path))==h
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))});resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    spec=importlib.util.spec_from_file_location('pr1996_correspondence_ggt',SOURCE);ggt=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ggt;spec.loader.exec_module(ggt)
    start=time.monotonic();rows=[]
    for name in ['w00','ag896']:
        original=_mesh(INPUT/(name+'.tifxyz'));xyz=original['xyz'];valid=original['valid'];ids=np.flatnonzero(valid)
        sample_ids=ids[np.floor(np.arange(48)*(len(ids)-1)/47).astype(int)]
        source={'xyz':xyz.reshape(-1,3)[sample_ids].reshape(48,1,3),'valid':np.ones((48,1),bool)}
        grid=xyz.copy();grid[~valid]=-1
        tolerance=_roundoff(original)
        for factor in rule['factors']:
            coarse=ggt.resample_grid(grid,factor)
            for mode in rule['modes']:
                keep=None if mode=='erode' else ggt.support_coarse_mask(coarse,valid,factor)
                out=ggt.finalize_coarse_grid(coarse,keep);reference={'xyz':out,'valid':out[...,0]>=0}
                result=project(source,reference,50/9.366,tolerance)
                gap=result['distance'].reshape(-1)*9.366
                finite=gap[np.isfinite(gap)]
                row={'mesh':name,'factor':factor,'mode':mode,'source_native_indices':sample_ids.tolist(),'points':48,
                     'certified_eligible':int(result['valid'].sum()),'ambiguous':int(result['ambiguous'].sum()),'unresolved':int(result['unresolved'].sum()),
                     'no_match_or_distance_fail':int((~result['valid']&~result['ambiguous']&~result['unresolved']).sum()),
                     'finite_uppergap_um_quantiles':np.quantile(finite,[0,.5,.9,1]).tolist() if finite.size else None,
                     'tolerance_vox':tolerance}
                assert all(gap[result['valid'].reshape(-1)]<=50)
                rows.append(row);print(json.dumps(row),flush=True)
    result={'rule_sha256':sha(ROOT/'correspondence-rule.json'),'rows':rows,'elapsed_seconds':time.monotonic()-start,
            'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'limits':rule['limits']}
    (ROOT/'correspondence-result.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    if sys.argv[1:]==['--freeze']:freeze()
    else:run()
