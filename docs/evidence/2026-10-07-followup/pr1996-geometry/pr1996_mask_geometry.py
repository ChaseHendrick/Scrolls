"""Exact PR1996 mask logic on cached public control meshes, no readers."""
import os
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
from pathlib import Path
import hashlib, importlib.util, json, sys, time, resource
import numpy as np
sys.path.insert(0,'/workspace/Scrolls')
from kit.surfacefix import _mesh
from kit._surface_geometry import quad_mask, bilinear

OUT=Path('/workspace/scrolls-env/pr1996-geometry-interaction')
SOURCE=Path('/workspace/scrolls-env/pr1996-review/grow_track_graph.py')
INPUT=Path('/workspace/scrolls-env/geometry-validation')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def freeze():
    OUT.mkdir(exist_ok=True)
    p=OUT/'rule.json'
    if p.exists():raise RuntimeError('No frozen rule overwrite')
    files=[SOURCE,Path(__file__),Path('/workspace/Scrolls/kit/_surface_geometry.py')]
    for name in ['w00','ag896']:
        files.extend(sorted((INPUT/(name+'.tifxyz')).iterdir()))
    rule={'schema':1,'scope':'Public PHerc0841 cached mesh resampling/mask behavior; not original track-graph growth, flattening benchmark, ink or targets',
          'pr_head':'d651f04d2f5c73fc5ba46c5f859392391cc59b43','factors':[2,4],'modes':['erode','support'],
          'input_grid_spacing':'Publishednative grids have scale0.05 (~20vox), so these are40/80voxel coarsening trials, notParis4 spacing5/10 reproductions',
          'voxel_um':9.366,'source_hashes':{str(f):sha(f) for f in files},
          'measurements':['retainedquadcount','all-fine-support violations','representedvalidworkingcell fraction','failedcoarsequadJacobian certificate','same-UV3Dposition error versus originalworkingvertices'],
          'controls':'Fullvalid plane and missingfinevertex phantom; code support mustneverretainquad withhole underfootprint; forward/reverse/shuffle notapplicable because noinkreader',
          'resources':{'threads':1,'max_peak_rss_bytes':2*1024**3,'network_bytes':0},
          'interpretation':'Support checksoccupancy only; Jacobiannonfold, bilinear interpolation fidelity and ink quality remain separate gates. No physicalarea/CPU/flattenclaim.'}
    p.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',sha(p))

def measure(ggt,grid,factor,mode):
    valid=grid[...,0]>=0
    coarse=ggt.resample_grid(grid,factor)
    keep=None if mode=='erode' else ggt.support_coarse_mask(coarse,valid,factor)
    out=ggt.finalize_coarse_grid(coarse,keep)
    cm=out[...,0]>=0
    quads=cm[:-1,:-1]&cm[1:,:-1]&cm[:-1,1:]&cm[1:,1:]
    supported_fine=valid[:-1,:-1]&valid[1:,:-1]&valid[:-1,1:]&valid[1:,1:]
    represented=np.zeros(supported_fine.shape,bool)
    errors=[];violations=0
    uv=np.stack(np.meshgrid(np.linspace(0,1,factor+1),np.linspace(0,1,factor+1),indexing='ij'),-1)
    for r,c in zip(*np.nonzero(quads)):
        y,x=r*factor,c*factor
        supported=valid[y:y+factor+1,x:x+factor+1].all()
        if not supported:violations+=1
        represented[y:y+factor,x:x+factor]=True
        corners=np.stack([out[r,c],out[r+1,c],out[r,c+1],out[r+1,c+1]])
        truth=grid[y:y+factor+1,x:x+factor+1]
        delta=np.linalg.norm(bilinear(corners,uv)-truth,axis=-1)
        errors.extend(delta[valid[y:y+factor+1,x:x+factor+1]].ravel().tolist())
    geometry=quad_mask({'xyz':out,'valid':cm})
    good_coverage=represented & supported_fine
    return {'mode':mode,'factor':factor,'coarse_shape':list(out.shape[:2]),'retainedvertices':int(cm.sum()),'retainedquads':int(quads.sum()),
            'fine_support_violations':violations,'fine_valid_cells':int(supported_fine.sum()),'represented_fine_valid_cells':int(good_coverage.sum()),
            'represented_fine_valid_cell_fraction':float(good_coverage.sum()/max(1,supported_fine.sum())),
            'retainedquads_failing_local_jacobian':int((quads&~geometry).sum()),
            'bilinear_vs_working_vertex_error_um_quantiles':(np.quantile(errors,[0,.5,.9,.99,1])*9.366).tolist() if errors else None}

def run():
    rule=json.loads((OUT/'rule.json').read_text())
    for f,h in rule['source_hashes'].items():assert sha(Path(f))==h
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    spec=importlib.util.spec_from_file_location('pr1996_grow_track',SOURCE);ggt=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ggt;spec.loader.exec_module(ggt)
    started=time.monotonic();rows=[]
    for name in ['w00','ag896']:
        mesh=_mesh(INPUT/(name+'.tifxyz'));grid=mesh['xyz'].copy();grid[~mesh['valid']]=-1
        for factor in rule['factors']:
            for mode in rule['modes']:
                row=measure(ggt,grid,factor,mode);row['mesh']=name;rows.append(row)
    rr,cc=np.indices((17,17));plane=np.stack([100+rr,100+cc,rr*0+50],-1).astype(float)
    controls=[]
    for hole in [False,True]:
        phantom=plane.copy()
        if hole:phantom[6,6]=-1
        for mode in ['erode','support']:
            row=measure(ggt,phantom,4,mode);row['phantom']='interior_hole' if hole else 'full_plane';controls.append(row)
    assert all(row['fine_support_violations']==0 for row in rows if row['mode']=='support')
    assert all(row['fine_support_violations']==0 for row in controls if row['mode']=='support')
    assert next(row for row in controls if row['mode']=='support' and row['phantom']=='full_plane')['retainedquads']>next(row for row in controls if row['mode']=='erode' and row['phantom']=='full_plane')['retainedquads']
    result={'rule_sha256':sha(OUT/'rule.json'),'rows':rows,'controls':controls,'elapsed_seconds':time.monotonic()-started,
            'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'limits':rule['scope']+'; same-UV errors are geometry discrepancy, notnormaldistance, flatten distortion orink readability.'}
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':
    if sys.argv[1:]==['--freeze']:freeze()
    else:run()
