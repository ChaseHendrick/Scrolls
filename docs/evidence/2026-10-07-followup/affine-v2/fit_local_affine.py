"""Fresh, bounded local 3D affine registration with independent CT audit points."""
from pathlib import Path
import concurrent.futures,hashlib,itertools,json,resource,sys,urllib.request
import numpy as np
from scipy import signal,ndimage
PARENT=Path('/workspace/scrolls-env/phase-reconstruction');ROOT=PARENT/'affine-followup';META=Path('/workspace/scrolls-env/novel-hypotheses-metadata')
sys.path.insert(0,str(PARENT));import register_ct_pilot as old
VOLS=old.VOLS;BASE=old.BASE
sha=lambda b:hashlib.sha256(b).hexdigest()

def overlaps(a,b):return all(max(x[0],y[0])<min(x[1],y[1]) for x,y in zip(a,b))
def plan():
 import tifffile
 coords=np.stack([tifffile.imread(PARENT/'w045-source.tifxyz'/f'{a}.tif')[192:224,128:160] for a in ['x','y','z']])
 lo=np.floor(coords.min((1,2))-17).astype(int);hi=np.ceil(coords.max((1,2))+17).astype(int)
 cal=[list(map(int,c)) for c in itertools.product(*zip(lo,hi))]
 fractions=np.array([[.35,.30,.17],[.65,.70,.17],[.35,.70,.83],[.65,.30,.83]])
 audits=np.rint(lo+(hi-lo)*fractions).astype(int).tolist()
 boxes=[[ [v-32,v+32] for v in c[::-1] ] for c in cal+audits]
 assert not any(overlaps(a,b) for a in boxes[:8] for b in boxes[8:])
 pilot=json.loads((PARENT/'registration-rule.json').read_text());prior=[r['bounds_zyx'] for r in pilot['requests'] if r['volume']=='original']
 assert not any(overlaps(a,b) for a in boxes[8:] for b in prior)
 req=[]
 for name,vol in VOLS.items():
  h=36 if name=='original' else 68
  header=json.loads((META/(vol+'-0-.zarray.json')).read_text())
  assert header['chunks']==[128]*3 and header['dtype']=='|u1' and header['compressor'] is None and header.get('filters') is None
  for i,xyz in enumerate(cal+audits):
   c=xyz[::-1];box=old.bounds(c,h);assert all(0<=a<b<=n for (a,b),n in zip(box,header['shape']))
   req.append({'volume':name,'point':i,'role':'calibration' if i<8 else 'audit','center_xyz':xyz,'bounds_zyx':box,'keys':old.keys(box)})
 unique={(r['volume'],tuple(k)) for r in req for k in r['keys']}
 new=[(n,k) for n,k in unique if not (PARENT/'ct-cache'/n/'0'/Path(*map(str,k))).is_file()]
 assert len(new)*128**3<=1024**3
 return {'schema':1,'scope':'PHerc0139 w045 public structural CT; no labels or reader output','volumes':VOLS,'xyz_box':[lo.tolist(),hi.tolist()],'calibration_xyz':cal,'audit_xyz':audits,'requests':req,'mapping':'homogeneous4x4 originalXYZvoxels->phaseXYZvoxels; fit q=A*p+t, column convention; NOT inverse','fit':'All8mandatory gradient NCC points; full3D affine normalized leastsquares, rank4 and condition<=10; no robust dropping or fallback model','features':'Gaussian sigma1 then3D gradient magnitude with4voxel rawhalo; rawNCC separately audited; template64,search128,padding32','peak':'Full3D quadratic fit to27neighbor NCC values; Hessian negative definite; offseteachaxis<=.5voxel; competing peak outside3voxel sphere; no integer fallback','gates':{'ncc_min':.6,'margin_min':.03,'residual_euclidean_vox_max':.5,'cal_raw_vs_gradient_euclidean_vox_max':.5,'normalized_design_condition_max':10,'affine_singular_values_range':[.95,1.05],'determinant_positive':True,'all_points_mandatory':True,'nonzero_fraction_min':.1,'std_min':2,'interior_peak':True},'controls':{'source':'Both cached actualCT original128pilotcubes; calibrationforalgorithm only','nonwrapping_shifts_zyx':[[0,0,0],[3,-4,5],[.25,-.35,.4],[-.4,.2,-.3]],'interpolation':'scipy.ndimage.shift order3 constant0; validcentraltemplate support clear of boundaries; featurehalo pipeline same','euclidean_error_vox_max':.15,'ncc_min':.99,'raw_and_gradient_required':True},'closure':'Independently locate q0 on each original audit cube; sample72cube aroundfractionalq0 withtrilinear interpolation todefinephase0template; directphase0->phase50 matchedNCC must agree with A50@inv(A0)q0 in full3DEuclidean distance<=.5vox. Recordcenters/fractionalcoords; do not test onlypredictedcenter','render_policy':{'parameter_grid':'Preserveoriginal640x640u-vpixelgrid. OfficialaffineforwardtransformandnormalA^-T; --scale1/cuberoot(abs(detA)) compensatesrenderer determinantgen_scale. Recordphysicalpixel_scale9.362*cuberoot(abs(detA)); nooutputresizing','native_crop_yx':[192,224,128,160],'voxel_um':9.362,'render_and_ink':'Only afterallindependentaudits pass andparent reviews; verifycanonicaldirectionagainstpublicsource stackbeforeinference'},'budgets':{'new_bytes_cap':1024**3,'max_RLIMIT_AS_bytes':2*1024**3,'threads':1,'planned_new_chunks':len(new),'planned_unique_chunks':len(unique)},'script_sha256':sha(Path(__file__).read_bytes()),'dependency_old_script_sha256':sha((PARENT/'register_ct_pilot.py').read_bytes()),'metadata_sha256':{n:sha((META/(v+'-0-.zarray.json')).read_bytes()) for n,v in VOLS.items()},'stop':'Anycontrol/calibration/audit/closuregate failure stopsbeforecandidate render orinference. Noalternatefitafteraudit. Failed oldtranslationpilot stays unchanged.'}

def chunk_file(name,k):
 rel=Path(name)/'0'/Path(*map(str,k));a=PARENT/'ct-cache'/rel
 return a if a.is_file() else ROOT/'ct-cache'/rel

def fetch(item):
 n,k=item;p=chunk_file(n,k);existed=p.is_file()
 if existed:raw=p.read_bytes()
 else:
  p.parent.mkdir(parents=True,exist_ok=True);url=BASE+'PHerc0139/volumes/'+VOLS[n]+'/0/'+'/'.join(map(str,k))
  with urllib.request.urlopen(url,timeout=45) as r:raw=r.read(128**3+1)
  if len(raw)!=128**3:raise ValueError('Chunk size mismatch '+url)
  p.write_bytes(raw)
 assert len(raw)==128**3
 return {'volume':n,'key':'/'.join(map(str,k)),'path':str(p),'bytes':len(raw),'sha256':sha(raw),'new_download':not existed}

def load(req):
 box=req['bounds_zyx'];a=np.empty([b-l for l,b in box],np.uint8)
 for k in req['keys']:
  c=np.frombuffer(chunk_file(req['volume'],k).read_bytes(),np.uint8).reshape(128,128,128)
  low=[max(x,v*128) for (x,y),v in zip(box,k)];high=[min(y,(v+1)*128) for (x,y),v in zip(box,k)]
  a[tuple(slice(l-x,h-x) for l,h,(x,y) in zip(low,high,box))]=c[tuple(slice(l-v*128,h-v*128) for l,h,v in zip(low,high,k))]
 return a

def trim_feature(raw,kind):
 f=old.feature(raw) if kind=='gradient' else raw.astype(np.float32)
 return f[4:-4,4:-4,4:-4]

def quadratic(score,idx):
 if np.any(idx<1) or np.any(idx>=np.array(score.shape)-1):return None,'boundary'
 off=np.array(list(itertools.product([-1,0,1],repeat=3)),float)
 z,y,x=off.T;X=np.column_stack([np.ones(27),z,y,x,.5*z*z,.5*y*y,.5*x*x,z*y,z*x,y*x])
 Y=np.array([score[tuple(idx+d.astype(int))] for d in off]);coef=np.linalg.lstsq(X,Y,rcond=None)[0]
 H=np.array([[coef[4],coef[7],coef[8]],[coef[7],coef[5],coef[9]],[coef[8],coef[9],coef[6]]])
 if not np.all(np.linalg.eigvalsh(H)<-1e-8):return None,'Hessian_not_negative_definite'
 delta=-np.linalg.solve(H,coef[1:4])
 if np.any(np.abs(delta)>.5):return None,'quadratic_offset_outside_halfvoxel'
 return delta,None

def locate(template_raw,search_raw,kind):
 t,s=trim_feature(template_raw,kind),trim_feature(search_raw,kind);t-=t.mean();energy=float((t.astype(float)**2).sum());size=t.shape[0]
 num=signal.fftconvolve(s,t[::-1,::-1,::-1],mode='valid');ss=old.local_sums(s,size);sq=old.local_sums(s*s,size)
 den=np.sqrt(np.maximum(sq-ss*ss/t.size,0)*energy);score=np.divide(num,den,out=np.full_like(den,-1),where=den>1e-8)
 idx=np.array(np.unravel_index(np.argmax(score),score.shape));grid=np.indices(score.shape);dist=sum((grid[i]-idx[i])**2 for i in range(3));other=float(score[dist>9].max());delta,reason=quadratic(score,idx)
 shift=idx-(np.array(s.shape)-np.array(t.shape))//2
 return {'integer_shift_zyx':shift.tolist(),'shift_zyx':None if delta is None else (shift+delta).tolist(),'ncc':float(score[tuple(idx)]),'margin':float(score[tuple(idx)])-other,'competing_ncc':other,'refinement_error':reason,'boundary':bool(np.any(idx==0) or np.any(idx==np.array(score.shape)-1))}

def accepted(p):return p['shift_zyx'] is not None and p['ncc']>=.6 and p['margin']>=.03 and not p['boundary']
def quality(a):return {'nonzero_fraction':float(np.mean(a>0)),'std':float(a.std()),'clip255_fraction':float(np.mean(a==255))}
def control_test():
 origreq=[r for r in json.loads((PARENT/'registration-rule.json').read_text())['requests'] if r['volume']=='original']
 rows=[]
 for req in origreq:
  base=old.load_patch(req).astype(np.float32);field=np.pad(base,4,mode='edge');t=field[32:104,32:104,32:104]
  for delta in [[0,0,0],[3,-4,5],[.25,-.35,.4],[-.4,.2,-.3]]:
   shifted=ndimage.shift(field,delta,order=3,mode='constant',cval=0,prefilter=True)
   for kind in ['gradient','raw']:
    p=locate(t,shifted,kind);err=float('inf') if p['shift_zyx'] is None else float(np.linalg.norm(np.array(p['shift_zyx'])-delta))
    rows.append({'cube':req['patch'],'kind':kind,'expected_zyx':delta,'peak':p,'error_vox':err,'pass':err<=.15 and p['ncc']>=.99})
 return rows

def affine(points,targets):
 p=np.array(points,float);q=np.array(targets,float);origin=p.mean(0);scale=np.ptp(p,axis=0)/2;X=np.column_stack([(p-origin)/scale,np.ones(len(p))]);coef,res,rank,sv=np.linalg.lstsq(X,q,rcond=None)
 M=np.eye(4);M[:3,:3]=(coef[:3]/scale[:,None]).T;M[:3,3]=coef[3]-M[:3,:3]@origin
 fit=(M[:3,:3]@p.T).T+M[:3,3]
 return {'matrix_original_xyz_to_phase_xyz':M.tolist(),'normalized_design_rank':int(rank),'normalized_design_condition':float(sv[0]/sv[-1]),'singular_values':np.linalg.svd(M[:3,:3],compute_uv=False).tolist(),'determinant':float(np.linalg.det(M[:3,:3])),'calibration_residuals_euclidean_vox':np.linalg.norm(fit-q,axis=1).tolist()}

def run(rule):
 resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
 controls=control_test();(ROOT/'algorithm-controls.json').write_text(json.dumps(controls,indent=2)+'\n')
 if not all(r['pass'] for r in controls):
  result={'status':'stopped_algorithm_controls_failed','controls':controls,'all_pass':False};(ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('STOP controls failed',flush=True);return
 todo=sorted({(r['volume'],tuple(k)) for r in rule['requests'] for k in r['keys']});receipts=[]
 # Network I/O alone is concurrent; numeric calculations remain single-threaded.
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for row in pool.map(fetch,todo):
   receipts.append(row)
   if len(receipts)%32==0:print('Chunks',len(receipts),'/',len(todo),flush=True)
 (ROOT/'input-receipt.json').write_text(json.dumps(receipts,indent=2)+'\n')
 reqmap={(r['volume'],r['point']):r for r in rule['requests']};matches=[]
 for i in range(12):
  orig=load(reqmap['original',i])
  for name in ['pag0','pag50']:
   target=load(reqmap[name,i]);peaks={kind:locate(orig,target,kind) for kind in ['gradient','raw']}
   row={'point':i,'role':'calibration' if i<8 else 'audit','volume':name,'source_xyz':reqmap['original',i]['center_xyz'],'quality_original':quality(orig),'quality_phase':quality(target),'peaks':peaks};matches.append(row);print('Match',name,i,json.dumps(peaks),flush=True)
 (ROOT/'correspondences.json').write_text(json.dumps(matches,indent=2)+'\n')
 fits={};reasons=[]
 for name in ['pag0','pag50']:
  cal=[r for r in matches if r['volume']==name and r['role']=='calibration'];targets=[]
  for row in cal:
   for kind,p in row['peaks'].items():
    if not accepted(p):reasons.append(f'{name}cal{row["point"]}{kind}failed_peak')
   for tag in ['quality_original','quality_phase']:
    if row[tag]['nonzero_fraction']<.1 or row[tag]['std']<2:reasons.append(f'{name}cal{row["point"]}{tag}failed_quality')
   g=row['peaks']['gradient']['shift_zyx'];raw=row['peaks']['raw']['shift_zyx']
   if g is not None and raw is not None and np.linalg.norm(np.array(g)-raw)>.5:reasons.append(f'{name}cal{row["point"]}raw_gradient_disagree')
   if g is not None:targets.append(np.array(row['source_xyz'])+np.array(g)[::-1])
  if len(targets)!=8:continue
  fit=affine([r['source_xyz'] for r in cal],targets);fits[name]=fit
  if fit['normalized_design_rank']!=4 or fit['normalized_design_condition']>10:reasons.append(name+'rank_condition_fail')
  if fit['determinant']<=0 or min(fit['singular_values'])<.95 or max(fit['singular_values'])>1.05:reasons.append(name+'jacobian_fail')
  if max(fit['calibration_residuals_euclidean_vox'])>.5:reasons.append(name+'calibration_residual_fail')
 audits=[]
 for row in [r for r in matches if r['role']=='audit']:
  if row['volume'] not in fits:continue
  M=np.array(fits[row['volume']]['matrix_original_xyz_to_phase_xyz']);p=np.array(row['source_xyz']);pred=M[:3,:3]@p+M[:3,3]
  for kind,pk in row['peaks'].items():
   observed=None if pk['shift_zyx'] is None else p+np.array(pk['shift_zyx'])[::-1];err=None if observed is None else float(np.linalg.norm(pred-observed))
   audit={'volume':row['volume'],'point':row['point'],'kind':kind,'predicted_xyz':pred.tolist(),'observed_xyz':None if observed is None else observed.tolist(),'residual_euclidean_vox':err,'pass':accepted(pk) and err is not None and err<=.5};audits.append(audit)
   if not audit['pass']:reasons.append(f'{row["volume"]}audit{row["point"]}{kind}_fail')
 closure=[]
 if set(fits)=={'pag0','pag50'}:
  C=np.array(fits['pag50']['matrix_original_xyz_to_phase_xyz'])@np.linalg.inv(np.array(fits['pag0']['matrix_original_xyz_to_phase_xyz']))
  for i in range(8,12):
   row=next(r for r in matches if r['volume']=='pag0' and r['point']==i);d=row['peaks']['gradient']['shift_zyx']
   if d is None:reasons.append(f'closure{i}_missing_q0');continue
   q0=np.array(row['source_xyz'])+np.array(d)[::-1];source=load(reqmap['pag0',i]);target=load(reqmap['pag50',i])
   # Exact fractional measured q0;72cube carries4voxhalo. Trilinear CT sampling.
   start=np.array(reqmap['pag0',i]['bounds_zyx'])[:,0];c=q0[::-1]-start;grid=np.indices((72,72,72),dtype=float)+c[:,None,None,None]-36
   if min(grid.min(axis=(1,2,3)))<0 or np.any(grid.max(axis=(1,2,3))>np.array(source.shape)-1):reasons.append(f'closure{i}_support_fail');continue
   template=ndimage.map_coordinates(source.astype(np.float32),grid,order=1,mode='constant',cval=np.nan,prefilter=False)
   pred=C[:3,:3]@q0+C[:3,3]
   for kind in ['gradient','raw']:
    peak=locate(template,target,kind);q50=None if peak['shift_zyx'] is None else np.array(row['source_xyz'])+np.array(peak['shift_zyx'])[::-1];err=None if q50 is None else float(np.linalg.norm(pred-q50))
    cr={'point':i,'kind':kind,'phase0_measured_fractional_xyz':q0.tolist(),'phase50_predicted_xyz':pred.tolist(),'phase50_direct_observed_xyz':None if q50 is None else q50.tolist(),'peak':peak,'residual_euclidean_vox':err,'pass':accepted(peak) and err is not None and err<=.5};closure.append(cr)
    if not cr['pass']:reasons.append(f'closure{i}{kind}_fail')
  composition=C.tolist()
 else:composition=None
 result={'status':'affine_followup_completed_no_render_or_ink','all_pass':not reasons,'reasons':reasons,'fits':fits,'audits':audits,'phase_pair_composition_xyz':composition,'phase_pair_independent_closure':closure,'rule_sha256':sha((ROOT/'rule.json').read_bytes()),'actual_new_bytes':sum(r['bytes'] for r in receipts if r['new_download']),'reused_bytes':sum(r['bytes'] for r in receipts if not r['new_download']),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'limits':'Local finite checkpoints; passing does not validate global warp or ink identity. Allfailedchecks retained; noalternatefit.'}
 (ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('FINAL',json.dumps(result),flush=True)

def manifest():
 files=[p for p in ROOT.rglob('*') if p.is_file() and p.name not in ['sha256-manifest.json'] and '/ct-cache/' not in str(p)]
 rows={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sorted(files)}
 (ROOT/'sha256-manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
 assert all(sha((ROOT/p).read_bytes())==h for p,h in rows.items());print('MANIFEST VERIFIED',len(rows),flush=True)

if __name__=='__main__':
 if sys.argv[1:]==['--freeze']:
  p=ROOT/'rule.json'
  if p.exists():raise RuntimeError('Frozen rule already exists')
  r=plan();p.write_text(json.dumps(r,indent=2)+'\n');print('FROZEN',sha(p.read_bytes()),r['budgets'])
 else:
  r=json.loads((ROOT/'rule.json').read_text());assert r['script_sha256']==sha(Path(__file__).read_bytes());assert r['dependency_old_script_sha256']==sha((PARENT/'register_ct_pilot.py').read_bytes())
  run(r);manifest()
