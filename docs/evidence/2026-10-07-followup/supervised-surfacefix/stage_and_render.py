"""Bounded official CT staging/rendering for frozen supervised PHerc0841 crop."""
import argparse,concurrent.futures,hashlib,itertools,json,os,subprocess,urllib.request
from pathlib import Path
import numpy as np
import tifffile
ROOT=Path('/workspace/scrolls-env/supervised-surfacefix');OLD=Path('/workspace/scrolls-env/geometry-validation')
RUNTIME=OLD/'renderer-runtime';BINARY=RUNTIME/'usr/local/bin/vc_render_tifxyz'
BINARY_SHA='fd1d5118e8f7e38c2c482d9cd5473eb5631f82546b896f088ef85ee4fe615a6a'
URL='https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def verify_rule():
 rule=json.loads((ROOT/'rule.json').read_text())
 assert rule['stage_render_script_sha256']==sha(__file__)
 assert sha(BINARY)==BINARY_SHA
 for name,record in rule['meshes'].items():
  p=Path(record['path']);assert {f.name:sha(f) for f in p.iterdir() if f.is_file()}==record['hashes']
 return rule

def stage(rule):
 cache=ROOT/'ct-cache.zarr';cache.mkdir(exist_ok=True)
 for key in ['.zattrs','.zgroup','0/.zarray']:
  with urllib.request.urlopen(URL+'/'+key,timeout=30) as response:raw=response.read()
  p=cache/key;p.parent.mkdir(parents=True,exist_ok=True)
  if p.exists() and p.read_bytes()!=raw:raise ValueError('CT metadata changed')
  p.write_bytes(raw)
 header=json.loads((cache/'0/.zarray').read_text())
 assert header['chunks']==[128]*3 and header['dtype']=='|u1' and header['compressor'] is None and not header.get('filters')
 prior={r['key']:r for r in json.loads((OLD/'ct-cache-receipt.json').read_text())['chunks'] if 'sha256' in r}
 receipt=ROOT/'ct-cache-receipt.json'
 if receipt.exists():prior.update({r['key']:r for r in json.loads(receipt.read_text())['chunks']})
 def one(key):
  name='0/'+'/'.join(map(str,key));p=cache/name;existing=prior.get(name)
  for src in [p,OLD/'ct-cache.zarr'/name]:
   if src.is_file() and existing and sha(src)==existing['sha256']:
    p.parent.mkdir(parents=True,exist_ok=True)
    if not p.exists():os.link(src,p)
    return {'key':name,'sha256':existing['sha256'],'bytes':src.stat().st_size,'reused':True}
  with urllib.request.urlopen(URL+'/'+name,timeout=60) as response:
   raw=response.read(128**3+1);etag=response.headers.get('ETag','').strip('"')
  if len(raw)!=128**3 or len(etag)!=32 or hashlib.md5(raw).hexdigest()!=etag:raise ValueError('CT integrity failure '+name)
  if p.exists():raise ValueError('Unverified cache file '+str(p))
  p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
  return {'key':name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'etag_md5':etag,'reused':False}
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(one,rule['ct_chunk_keys']))
 receipt.write_text(json.dumps({'source':URL,'rule_sha256':sha(ROOT/'rule.json'),'chunks':rows,'metadata_sha256':{k:sha(cache/k) for k in ['.zattrs','.zgroup','0/.zarray']},'bytes':sum(r['bytes'] for r in rows),'new_bytes':sum(r['bytes'] for r in rows if not r['reused'])},indent=2)+'\n')
 print('STAGED',len(rows),'chunks',flush=True)

def render(rule,name,mesh):
 mesh=mesh.resolve();xyz=np.stack([tifffile.imread(mesh/f'{c}.tif') for c in 'xyz'],-1)
 meta=json.loads((mesh/'meta.json').read_text());assert xyz.shape==(32,32,3) and np.allclose(meta['scale'],[.05,.05])
 assert np.isfinite(xyz).all() and (xyz>=0).all()
 coverage=set(map(tuple,rule['ct_chunk_keys']));lo=np.floor((xyz.min((0,1))-16)/128).astype(int)[::-1];hi=np.floor((xyz.max((0,1))+16)/128).astype(int)[::-1]
 required=set(itertools.product(*[range(a,b+1) for a,b in zip(lo,hi)]));assert required<=coverage
 cache=ROOT/'ct-cache.zarr';receipt=json.loads((ROOT/'ct-cache-receipt.json').read_text());records={r['key']:r for r in receipt['chunks']}
 for key in required:
  k='0/'+'/'.join(map(str,key));assert sha(cache/k)==records[k]['sha256'] and (cache/k).stat().st_size==128**3
 raw=ROOT/f'tif-{name}';layers=ROOT/f'layers-{name}'
 if raw.exists() or layers.exists():raise ValueError('Output exists')
 hashes={p.name:sha(p) for p in mesh.iterdir() if p.is_file()}
 command=[str(BINARY),'--volume',str(cache),'--segmentation',str(mesh),'--scale','1','--group-idx','0','--cache-gb','1','--num-slices','28','--slice-step','1','--voxel-size','9.366','--voxel-unit','micrometer','--tif-output',str(raw),'--timeout','5']
 env=os.environ.copy();env['OMP_NUM_THREADS']='1';env['LD_LIBRARY_PATH']=':'.join(str(RUNTIME/p) for p in ['usr/lib','usr/lib/x86_64-linux-gnu','lib/x86_64-linux-gnu','usr/local/lib'])
 with (ROOT/f'tif-{name}.log').open('w') as log:subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
 for i in range(28):
  a=tifffile.imread(raw/f'{i:02d}.tif');assert a.shape==(640,640) and a.dtype==np.uint8
 assert hashes=={p.name:sha(p) for p in mesh.iterdir() if p.is_file()}
 record={'rule_sha256':sha(ROOT/'rule.json'),'command':command,'binary_sha256':BINARY_SHA,'source_mesh_hashes':hashes,'output_raw_sha256':{p.name:sha(p) for p in raw.iterdir() if p.is_file()},'order':'Raw official +N retained. Canonical published -N links require frozen structural audit; no maps here.'}
 (ROOT/f'tif-{name}-receipt.json').write_text(json.dumps(record,indent=2)+'\n');print(raw,flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--stage',action='store_true');p.add_argument('--render',choices=['baseline','reference','minus1','plus1']);p.add_argument('--mesh',type=Path)
 args=p.parse_args();rule=verify_rule()
 if args.stage:stage(rule)
 if args.render:
  mesh=args.mesh or Path(rule['meshes'][args.render]['path']);render(rule,args.render,mesh)
if __name__=='__main__':main()
