"""Frozen adaptive patch representation diagnostic, not a deployable mesh export."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,hashlib,resource
from pathlib import Path
import numpy as np
import tifffile
import geometry_snapshot as g
ROOT=Path(__file__).resolve().parent
INPUT=Path('/workspace/scrolls-env/geometry-validation')
UM=9.366
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def mesh(x): return {'xyz':np.asarray(x,float),'valid':(np.asarray(x)>=0).all(-1)&(np.asarray(x).sum(-1)>0)}
def load(name):
    arrays=[tifffile.imread(INPUT/(name+'.tifxyz')/(c+'.tif')) for c in 'xyz']
    x=np.stack(arrays,-1).astype(float)
    ulp=max(float(np.spacing(np.asarray(np.max(np.abs(x[...,i])),dtype=a.dtype))) for i,a in enumerate(arrays))
    return mesh(x),max(.001,2*np.sqrt(3)*ulp)
def corners(x): return x[[0,2,0,2],[0,0,2,2]]
UV=np.stack(np.meshgrid(np.linspace(0,1,3),np.linspace(0,1,3),indexing='ij'),-1)
def metrics(x):
    fine=mesh(x); coarse=mesh(x[::2,::2]); supported=bool(g.quad_mask(fine).all())
    regular=bool(g.quad_mask(coarse).all())
    error=float(np.max(np.linalg.norm(x-g.bilinear(corners(x),UV),axis=-1))*UM)
    return supported,regular,error
def freeze():
    p=ROOT/'rule.json'
    if p.exists():raise RuntimeError('Frozen rule already exists')
    paths=[Path(__file__),ROOT/'geometry_snapshot.py']
    for n in ['w00','ag896']:
        paths += [INPUT/(n+'.tifxyz')/(c+'.tif') for c in 'xyz']+[INPUT/(n+'.tifxyz')/'meta.json']
    rule=dict(schema=1,scope='Same-sheet PHerc0841 w00/ag896 cross-trace/query geometry diagnostic; no independent sheet, reader, ink, flattening or exported topology claim',
        input_hashes={str(p):sha(p) for p in paths},native_voxel_um=UM,
        patch='Disjoint 2x2 fine cells/3x3 native vertices, starts even row/col; incomplete boundary strips retain native representation',
        selection='All four fine quads and coarse quad pass frozen Jacobian certificate; all nine corners valid; maximum same-UV corner discrepancy <=25um',
        certificate='Coarse-minus-fine is bilinear on each fine cell; norm bounded by max of its four vertex discrepancies by convexity',
        max_error_um=25,correspondence_limit_um=50,minimum_primitive_reduction=.20,minimum_local_correspondence_retention=.95,
        query='40 fresh seeded complete fine patches per trace; UV=(.37,.41) coarse coordinates; 0,+40,-40um along native local normal. Same source points for native/adaptive/uniform2/random-count-matched masks. No prior48 vertex query overlap.',
        query_seed=2041508,random_mask_seed=971142,dense_seed=616895,
        dense='Up to64 selected and64 unselected complete patches per trace, independent17x17UV samples; error may not exceed maxcorner bound plus1e-7um',
        controls=['uniformtranslation plane','nonplanar bilinear exact representation','saddle zero representation error but correspondence must abstain','bowed center error exclusion','missing middle vertex exclusion'],
        failure='Primary diagnostic fails if ag896 primitive reduction<20%, or local retained correspondence<95%, any dense bound violation, or any synthetic control failure. Keep failed hypotheses. No parameter retuning.',
        limitations='ag405 XYZ not cached; w00/ag896 are same physical sheet and have been measured previously. Fresh prospective queries not an untouched-scan holdout. Primitive reduction ignores conformity/hanging-edge transitions; no manifold or runtime saving inferred.',
        resources=dict(threads=1,max_seconds=300,max_peak_rss_bytes=512*1024**2,network_bytes=0))
    p.write_text(json.dumps(rule,indent=2)+'\n')
    (ROOT/'preregistration.sha256').write_text(sha(p)+'  rule.json\n')
    print('FROZEN',sha(p))
def dense_error(x):
    uv=np.stack(np.meshgrid(np.linspace(0,1,17),np.linspace(0,1,17),indexing='ij'),-1)
    fine,_=g.sample_geometry(mesh(x),2*uv)
    return float(np.max(np.linalg.norm(fine-g.bilinear(corners(x),uv),axis=-1))*UM)
def query(x,offset,tol):
    uv=np.array([.74,.82]);fine=mesh(x);p,_=g.sample_geometry(fine,uv)
    a,b,c,d=x[0,0],x[1,0],x[0,1],x[1,1];twist=d-b-c+a
    normal=np.cross(b-a+twist*uv[1],c-a+twist*uv[0]);normal/=np.linalg.norm(normal)
    source=mesh((p+offset/UM*normal).reshape(1,1,3))
    def read(ref):
        z=g.project(source,ref,50/UM,tol)
        return dict(valid=bool(z['valid'][0,0]),ambiguous=bool(z['ambiguous'][0,0]),unresolved=bool(z['unresolved'][0,0]),upper_um=float(z['distance'][0,0]*UM) if np.isfinite(z['distance'][0,0]) else None)
    return read(fine),read(mesh(x[::2,::2]))
def controls():
    r,c=np.indices((3,3));plane=np.stack([100+20*r,100+20*c,np.zeros_like(r)+50],-1).astype(float)
    translated=plane+[1000,2000,3000]
    ca=np.array([[100,100,100],[140,100,100],[100,140,100],[140,140,110]],float)
    nonplanar=g.bilinear(ca,UV)
    saddlecorners=np.array([[-1,-1,2],[1,-1,-2],[-1,1,-2],[1,1,2]],float)+100
    saddle=g.bilinear(saddlecorners,UV)
    bad=plane.copy();bad[1,1,2]+=10
    hole=plane.copy();hole[1,1]=-1
    z=g.project(mesh(np.array([[[100,100,101]]])),mesh(saddle[::2,::2]),50/UM,.001)
    result=dict(plane=metrics(plane),translated_plane=metrics(translated),nonplanar_bilinear=metrics(nonplanar),saddle=metrics(saddle),
        saddle_projection_rejected=not bool(z['valid'][0,0]),bowed_center=metrics(bad),hole=metrics(hole))
    result['passed']=(result['plane']==result['translated_plane'] and result['plane'][2]<1e-7 and result['nonplanar_bilinear'][2]<1e-7 and
        result['nonplanar_bilinear'][1] and result['saddle'][2]<1e-7 and result['saddle_projection_rejected'] and result['bowed_center'][2]>25 and not result['hole'][0])
    return result
def run():
    rule=json.loads((ROOT/'rule.json').read_text())
    for p,h in rule['input_hashes'].items():assert sha(Path(p))==h,p
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    started=time.monotonic();results=[];control=controls()
    for name in ['w00','ag896']:
        m,tol=load(name);x=m['xyz'];count=int(g.quad_mask(m).sum());blocks=[]
        for r in range(0,x.shape[0]-2,2):
            for c in range(0,x.shape[1]-2,2):
                patch=x[r:r+3,c:c+3];support,regular,error=metrics(patch)
                if support:blocks.append((r,c,regular,error))
        accepted=np.array([bool(b[2] and b[3]<=25) for b in blocks]);eligible=np.array([i for i,b in enumerate(blocks) if b[2]])
        rng=np.random.default_rng(rule['random_mask_seed']);random=np.zeros(len(blocks),bool)
        random[rng.choice(eligible,int(accepted.sum()),replace=False)]=True
        uniform=np.array([b[2] for b in blocks]);dense=[]
        rng=np.random.default_rng(rule['dense_seed'])
        for mask in [accepted,~accepted]:
            ids=np.flatnonzero(mask)
            for i in rng.choice(ids,min(64,len(ids)),replace=False):
                r,c,_,bound=blocks[i];actual=dense_error(x[r:r+3,c:c+3])
                dense.append(dict(block_index=int(i),bound_um=bound,dense_max_um=actual,passed=actual<=bound+1e-7))
        rng=np.random.default_rng(rule['query_seed']);ids=rng.choice(len(blocks),min(40,len(blocks)),replace=False)
        queries=[]
        for i in ids:
            r,c,_,_=blocks[i]
            for offset in [0,40,-40]:
                baseline,coarse=query(x[r:r+3,c:c+3],offset,tol)
                queries.append(dict(block_index=int(i),row=r,col=c,offset_um=offset,baseline=baseline,
                    adaptive=coarse if accepted[i] else baseline,uniform2=coarse if uniform[i] else baseline,
                    count_matched_random=coarse if random[i] else baseline))
        summaries={}
        for mode in ['adaptive','uniform2','count_matched_random']:
            base=sum(q['baseline']['valid'] for q in queries);retained=sum(q['baseline']['valid'] and q[mode]['valid'] for q in queries)
            summaries[mode]=dict(native_eligible=base,retained=retained,retention=retained/base if base else None,
                total_eligible=sum(q[mode]['valid'] for q in queries),ambiguous=sum(q[mode]['ambiguous'] for q in queries),unresolved=sum(q[mode]['unresolved'] for q in queries))
        reduction=3*int(accepted.sum())/count
        row=dict(trace=name,shape=list(x.shape[:2]),native_regular_quads=count,complete_2x2_blocks=len(blocks),selected_blocks=int(accepted.sum()),
            hypothetical_primitive_reduction=reduction,no_export_or_topology_claim=True,
            corner_error_um_quantiles=np.quantile([b[3] for b in blocks],[0,.5,.9,.99,1]).tolist(),
            selected_error_um_quantiles=np.quantile([b[3] for i,b in enumerate(blocks) if accepted[i]],[0,.5,.9,1]).tolist() if accepted.any() else None,
            dense_bound_audits=dense,dense_all_pass=all(d['passed'] for d in dense),query_summaries=summaries,queries=queries,
            primary_hypothesis_passed=bool(reduction>=.20 and summaries['adaptive']['retention'] is not None and summaries['adaptive']['retention']>=.95 and all(d['passed'] for d in dense) and control['passed']))
        results.append(row);print(json.dumps({k:row[k] for k in ['trace','selected_blocks','hypothetical_primitive_reduction','query_summaries','primary_hypothesis_passed']}),flush=True)
        if time.monotonic()-started>300:raise RuntimeError('Frozen runtime budget exceeded')
    output=dict(rule_sha256=sha(ROOT/'rule.json'),controls=control,traces=results,elapsed_seconds=time.monotonic()-started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,ag405_available=False,limitations=rule['limitations'])
    (ROOT/'result.json').write_text(json.dumps(output,indent=2)+'\n')
if __name__=='__main__':
    freeze() if sys.argv[1:]==['--freeze'] else run()
