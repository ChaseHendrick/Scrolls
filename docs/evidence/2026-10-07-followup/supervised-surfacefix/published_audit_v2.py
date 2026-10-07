"""Frozen CT-only published raster/depth audit, with no label/model access."""
import argparse,concurrent.futures,hashlib,itertools,json,os,urllib.request
from pathlib import Path
import numpy as np
import tifffile
ROOT=Path('/workspace/scrolls-env/supervised-surfacefix');sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
BASE='https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/'
SEGMENTS={'baseline':'20260220213127-w00','reference':'20260220214732-auto_grown_20260220144552896'}

def freeze():
 source=json.loads((ROOT/'rule.json').read_text());parts={}
 for name,seg in SEGMENTS.items():
  header_path=ROOT/f'published-{name}-0-.zarray.json';header=json.loads(header_path.read_text())
  assert header['chunks']==[28,128,128] and header['dtype']=='|u1' and header['compressor'] is None and not header.get('filters')
  crop=source['meshes'][name]['source_canvas_crop_yxyx'];y0,y1,x0,x1=crop
  keys=['0/'+str(y)+'/'+str(x) for y,x in itertools.product(range(y0//128,(y1-1)//128+1),range(x0//128,(x1-1)//128+1))]
  parts[name]={'base':BASE+seg+'/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/','crop_yxyx':crop,'header_sha256':sha(header_path),'header_path':str(header_path),'keys':keys}
 rule={'schema':1,'scope':'Structural published raster/depth verification only, before model maps','experiment_rule_sha256':sha(ROOT/'rule.json'),'script_sha256':sha(__file__),'parts':parts,'inner_px':64,'min_correlation':.98,'max_mae_uint8':3,'both_orders_reported':True,'no_translation_or_resizing':True}
 p=ROOT/'published-audit-rule-v2.json'
 if p.exists():raise ValueError('Frozen rule exists')
 p.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',sha(p),flush=True)

def run():
 rule=json.loads((ROOT/'published-audit-rule-v2.json').read_text());assert rule['script_sha256']==sha(__file__) and rule['experiment_rule_sha256']==sha(ROOT/'rule.json')
 results={}
 for name,part in rule['parts'].items():
  assert sha(part['header_path'])==part['header_sha256'];header=json.loads(Path(part['header_path']).read_text())
  crop=part['crop_yxyx'];y0,y1,x0,x1=crop;stack=np.empty((28,640,640),np.uint8);cache=ROOT/f'published-{name}-chunks';cache.mkdir(exist_ok=True)
  def fetch(key):
   with urllib.request.urlopen(part['base']+'0/'+key,timeout=45) as response:
    raw=response.read(28*128*128+1);etag=response.headers.get('ETag','').strip('"')
   if len(raw)!=28*128*128 or len(etag)!=32 or hashlib.md5(raw).hexdigest()!=etag:raise ValueError('Published chunk integrity failure '+key)
   p=cache/key;p.parent.mkdir(parents=True,exist_ok=True)
   if p.exists() and p.read_bytes()!=raw:raise ValueError('Published chunk changed')
   p.write_bytes(raw)
   return {'key':key,'bytes':len(raw),'sha256':sha(p),'etag_md5':etag}
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:receipts=list(pool.map(fetch,part['keys']))
  for row in receipts:
   _,cy,cx=map(int,row['key'].split('/'));a=np.frombuffer((cache/row['key']).read_bytes(),np.uint8).reshape(28,128,128)
   ly,hy=max(y0,cy*128),min(y1,(cy+1)*128);lx,hx=max(x0,cx*128),min(x1,(cx+1)*128)
   stack[:,ly-y0:hy-y0,lx-x0:hx-x0]=a[:,ly-cy*128:hy-cy*128,lx-cx*128:hx-cx*128]
  np.save(ROOT/f'published-{name}-crop.npy',stack)
  raw=np.stack([tifffile.imread(ROOT/f'tif-{name}'/f'{i:02d}.tif') for i in range(28)])
  comparisons={}
  for label,a in [('raw_plus_N',raw),('reversed_minus_N',raw[::-1])]:
   x=a[:,64:-64,64:-64].astype(float).reshape(-1);y=stack[:,64:-64,64:-64].astype(float).reshape(-1)
   corr=float(np.corrcoef(x,y)[0,1]);mae=float(np.abs(x-y).mean())
   comparisons[label]={'r':corr,'mae':mae,'equal_fraction':float(np.mean(x==y)),'voxels':len(x),'passes':bool(corr>=.98 and mae<=3)}
  chosen=[k for k,v in comparisons.items() if v['passes']]
  if chosen!=['reversed_minus_N']:raise ValueError('Published order/raster failed or ambiguous: '+json.dumps(comparisons))
  layers=ROOT/f'layers-{name}'
  if layers.exists():raise ValueError('Reader layers exist')
  layers.mkdir()
  for i in range(28):os.link(ROOT/f'tif-{name}'/f'{27-i:02d}.tif',layers/f'{i:02d}.tif')
  results[name]={'comparisons':comparisons,'canonical_order':chosen[0],'published_chunks':receipts,'published_crop_sha256':sha(ROOT/f'published-{name}-crop.npy'),'raw_receipt_sha256':sha(ROOT/f'tif-{name}-receipt.json'),'canonical_layer_sha256':{p.name:sha(p) for p in layers.iterdir()}}
 output={'rule_sha256':sha(ROOT/'published-audit-rule-v2.json'),'experiment_rule_sha256':sha(ROOT/'rule.json'),'parts':results,'all_pass':True,'limits':'One fixed known-sheet crop; no ink labels or model scores used for this structural verification.'}
 (ROOT/'published-audit-result.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps({n:r['comparisons'] for n,r in results.items()}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');a=p.parse_args()
 if a.freeze:freeze()
 else:run()
