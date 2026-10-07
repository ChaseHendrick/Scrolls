"""Bounded public labelled-control CT-only registration feasibility pilot."""
from pathlib import Path
import concurrent.futures, hashlib, json, urllib.request, itertools, resource
import numpy as np
from scipy import signal, ndimage

ROOT=Path('/workspace/scrolls-env/phase-reconstruction')
META=Path('/workspace/scrolls-env/novel-hypotheses-metadata')
BASE='https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/'
VOLS={
'original':'20250728140407-9.362um-1.2m-113keV-masked.zarr',
'pag0':'20251107132835-9.362um-1.2m-113keV-pag0-masked.zarr',
'pag50':'20251107135911-9.362um-1.2m-113keV-pag50-masked.zarr'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def bounds(c,h):return [(v-h,v+h) for v in c]
def keys(box):return list(itertools.product(*[range(a//128,(b-1)//128+1) for a,b in box]))
def construct_rule():
 import tifffile
 coords=np.stack([tifffile.imread(ROOT/'w045-source.tifxyz'/f'{ax}.tif')[192:224,128:160] for ax in ['z','y','x']])
 lo=coords.min(axis=(1,2));hi=coords.max(axis=(1,2))
 centers=[np.rint(lo+(hi-lo)*f).astype(int).tolist() for f in [1/3,2/3]]
 requests=[]
 for name in VOLS:
  headers=json.loads((META/(VOLS[name]+'-0-.zarray.json')).read_text())
  assert headers['chunks']==[128,128,128] and headers['dtype']=='|u1' and headers['compressor'] is None and headers.get('filters') is None and headers['dimension_separator']=='/'
  half=64 if name=='original' else 96
  for i,c in enumerate(centers):
   box=bounds(c,half)
   assert all(0<=a<b<=s for (a,b),s in zip(box,headers['shape']))
   requests.append({'volume':name,'patch':i,'center_zyx':c,'bounds_zyx':box,'chunk_keys_zyx':keys(box)})
 unique={(r['volume'],tuple(k)) for r in requests for k in r['chunk_keys_zyx']}
 assert len(unique)<=128
 return {'schema':1,'scope':'Public PHerc0139 w045 structural CT only; no model/label selection; no targets',
 'volumes':VOLS,'voxel_um':9.362,'centers_from_geometry':'rounded min+(max-min)*[1/3,2/3] from native y192:224,x128:160; XYZ converted to ZYX explicitly',
 'requests':requests,'unique_chunks':len(unique),'max_chunks':128,'max_bytes':128*128**3,'max_peak_rss_bytes':2*1024**3,
 'search_radius_vox':32,'template_size':128,'search_size':192,
 'selection':'Primary gradient-magnitude NCC after Gaussian sigma1; first cube fits translation, second cube independently locates heldback peak; raw NCC diagnostic only',
 'gate':{'minimum_peak_ncc':.6,'minimum_peak_minus_competing_peak':.03,'competing_peak_exclusion_radius_vox':3,'maximum_heldback_residual_vox':.5,'reject_search_boundary_peak':True,'minimum_nonzero_fraction':.1,'minimum_raw_std':2},
 'controls':{'self_template_size':96,'self_search_size':128,'self_shift_zyx':[3,-4,5],'minimum_ncc':.99,'maximum_shift_error_vox':0},
 'readout':'Report all recipes/cubes/control peaks; pass only if both phase recipes have unique interior peaks, heldback residual <=0.5vox and controls pass. Local translation feasibility only, not global registration or ink recovery. No model inference unless root reviews this result.',
 'script_sha256':digest(Path(__file__).read_bytes()),
 'metadata_sha256':{n:digest((META/(v+'-0-.zarray.json')).read_bytes()) for n,v in VOLS.items()}}

def get_chunk(item):
 name,k=item;p=ROOT/'ct-cache'/name/'0'/Path(*map(str,k));p.parent.mkdir(parents=True,exist_ok=True)
 url=BASE+'PHerc0139/volumes/'+VOLS[name]+'/0/'+'/'.join(map(str,k))
 if p.exists():raw=p.read_bytes()
 else:
  with urllib.request.urlopen(url,timeout=45) as r:raw=r.read(128**3+1)
  if len(raw)!=128**3:raise ValueError('Unexpected chunk byte count '+url)
  p.write_bytes(raw)
 if len(raw)!=128**3:raise ValueError('Invalid cached chunk '+str(p))
 return {'volume':name,'key':'/'.join(map(str,k)),'bytes':len(raw),'sha256':digest(raw),'url':url}

def load_patch(req):
 box=req['bounds_zyx'];arr=np.empty([b-a for a,b in box],dtype=np.uint8)
 for k in req['chunk_keys_zyx']:
  raw=(ROOT/'ct-cache'/req['volume']/'0'/Path(*map(str,k))).read_bytes();ch=np.frombuffer(raw,np.uint8).reshape(128,128,128)
  a=[max(lo,v*128) for (lo,hi),v in zip(box,k)];b=[min(hi,(v+1)*128) for (lo,hi),v in zip(box,k)]
  arr[tuple(slice(x-lo,y-lo) for x,y,(lo,hi) in zip(a,b,box))]=ch[tuple(slice(x-v*128,y-v*128) for x,y,v in zip(a,b,k))]
 return arr

def local_sums(arr,n):
 a=np.pad(arr,[(1,0)]*3).astype(np.float64)
 for axis in range(3):a=a.cumsum(axis=axis)
 return a[n:,n:,n:]-a[:-n,n:,n:]-a[n:,:-n,n:]-a[n:,n:,:-n]+a[:-n,:-n,n:]+a[:-n,n:,:-n]+a[n:,:-n,:-n]-a[:-n,:-n,:-n]

def feature(a):
 s=ndimage.gaussian_filter(a.astype(np.float32),sigma=1)
 grad=np.gradient(s)
 return np.sqrt(sum(g*g for g in grad))

def peak(template,search,method='gradient'):
 if method=='gradient':t,s=feature(template),feature(search)
 else:t,s=template.astype(np.float32),search.astype(np.float32)
 t=t-t.mean();te=float(np.square(t.astype(np.float64)).sum());n=t.size;side=t.shape[0]
 numerator=signal.fftconvolve(s,t[::-1,::-1,::-1],mode='valid')
 totals=local_sums(s,side);sq=local_sums(s*s,side)
 denom=np.sqrt(np.maximum(sq-totals*totals/n,0)*te)
 score=np.divide(numerator,denom,out=np.full_like(denom,-1),where=denom>1e-8)
 idx=np.array(np.unravel_index(np.argmax(score),score.shape));radius=(np.asarray(s.shape)-np.asarray(t.shape))//2
 grid=np.indices(score.shape);dist=sum((grid[i]-idx[i])**2 for i in range(3));second=float(np.max(score[dist>3**2]))
 shift=(idx-radius).tolist();p=float(score[tuple(idx)])
 return {'shift_zyx_vox':shift,'ncc':p,'competing_peak_ncc':second,'peak_margin':p-second,'boundary':bool(np.any(idx==0) or np.any(idx==np.asarray(score.shape)-1))}

def run(rule):
 resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
 chunks=sorted({(r['volume'],tuple(k)) for r in rule['requests'] for k in r['chunk_keys_zyx']})
 receipts=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for row in pool.map(get_chunk,chunks):
   receipts.append(row)
   if len(receipts)%16==0:print('Fetched',len(receipts),'/',len(chunks),'chunks',flush=True)
 (ROOT/'ct-cache-receipt.json').write_text(json.dumps(receipts,indent=2)+'\n')
 originals={r['patch']:load_patch(r) for r in rule['requests'] if r['volume']=='original'}
 controls=[]
 for i,o in originals.items():
  t=o[16:112,16:112,16:112]
  for label,s,expected in [('self',o,[0,0,0]),('known_shift',np.roll(o,[3,-4,5],axis=(0,1,2)),[3,-4,5])]:
   r=peak(t,s);r.update(patch=i,control=label,expected_zyx_vox=expected)
   r['pass']=r['ncc']>=.99 and r['shift_zyx_vox']==expected
   controls.append(r)
 rows=[]
 for req in rule['requests']:
  if req['volume']=='original':continue
  o=originals[req['patch']];s=load_patch(req)
  quality={'source_nonzero_fraction':float(np.mean(o>0)),'source_std':float(o.std()),'search_nonzero_fraction':float(np.mean(s>0)),'search_std':float(s.std()),'source_clipped255_fraction':float(np.mean(o==255)),'search_clipped255_fraction':float(np.mean(s==255))}
  row={'volume':req['volume'],'patch':req['patch'],'quality':quality,'gradient':peak(o,s),'raw':peak(o,s,'raw')};rows.append(row)
  print('Registration',json.dumps(row),flush=True)
 verdict={}
 for name in ['pag0','pag50']:
  rr=[r for r in rows if r['volume']==name];rr.sort(key=lambda r:r['patch'])
  delta=(np.array(rr[1]['gradient']['shift_zyx_vox'])-np.array(rr[0]['gradient']['shift_zyx_vox'])).tolist()
  reasons=[]
  for r in rr:
   g=r['gradient'];q=r['quality']
   if g['ncc']<.6:reasons.append(f"patch{r['patch']}: low primary NCC")
   if g['peak_margin']<.03:reasons.append(f"patch{r['patch']}: ambiguous primary peak")
   if g['boundary']:reasons.append(f"patch{r['patch']}: search boundary peak")
   if min(q['source_nonzero_fraction'],q['search_nonzero_fraction'])<.1 or min(q['source_std'],q['search_std'])<2:reasons.append(f"patch{r['patch']}: weak structural coverage")
  if max(abs(x) for x in delta)>.5:reasons.append('heldback residual exceeds0.5voxel')
  if not all(c['pass'] for c in controls):reasons.append('algorithm control failed')
  verdict[name]={'pass':not reasons,'fit_shift_zyx_vox':rr[0]['gradient']['shift_zyx_vox'],'heldback_residual_zyx_vox':delta,'reasons':reasons}
 result={'scope':rule['scope'],'status':'registration_feasibility_complete_no_ink_inference','rule_sha256':digest((ROOT/'registration-rule.json').read_bytes()),'rows':rows,'controls':controls,'verdict':verdict,'all_pass':all(x['pass'] for x in verdict.values()),'actual_chunks':len(receipts),'actual_download_bytes':sum(r['bytes'] for r in receipts),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'limits':'Two local structural cubes only; does not prove global registration, ink identity or geometry correction quality.'}
 (ROOT/'registration-pilot-result.json').write_text(json.dumps(result,indent=2)+'\n');print('FINAL',json.dumps(result),flush=True)

if __name__=='__main__':
 import sys
 if sys.argv[1:]==['--freeze']:
  rule=construct_rule();p=ROOT/'registration-rule.json'
  if p.exists():raise RuntimeError('Refusing to overwrite frozen rule')
  p.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',digest(p.read_bytes()),'chunks',rule['unique_chunks'])
 else:
  rule=json.loads((ROOT/'registration-rule.json').read_text())
  if rule['script_sha256']!=digest(Path(__file__).read_bytes()):raise RuntimeError('Script changed after freeze')
  run(rule)
