"""Edited-support mapping checks, using only synthetic native corner edits."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import importlib.util,hashlib,json
import numpy as np
p=Path('/workspace/scrolls-env/supervised-surfacefix/evaluate_supervised.py');spec=importlib.util.spec_from_file_location('evaluation',p);e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
a=np.zeros((32,32,3),np.float32);b=a.copy();b[8,12,2]=1
support,n=e.edited_support(a,b,[.05,.05]);expected=np.zeros((640,640),bool);expected[140:180,220:260]=True
assert n==1;np.testing.assert_array_equal(support,expected)
support,n=e.edited_support(a,a,[.05,.05]);assert n==0 and not support.any()
b=a.copy();b[0,0,0]=1;b[31,31,1]=1;support,n=e.edited_support(a,b,[.05,.05]);expected[:]=False;expected[:20,:20]=True;expected[600:620,600:620]=True
assert n==2;np.testing.assert_array_equal(support,expected)
b=a.copy();b[8,12,2]=1;support,n=e.edited_support(a,b,[.1,.05],(640,320));expected=np.zeros((640,320),bool);expected[140:180,110:130]=True
assert n==1;np.testing.assert_array_equal(support,expected)
# A degenerate edited cohort is explicit, rather than an apparently passing score.
mask=np.ones((20,20),bool);ink=np.zeros(mask.shape,bool);pred=np.zeros(mask.shape,np.uint8)
y,x,blocks,inv,w=e.math.bootstrap_weights(mask,10,100,8)
point,draws=e.math.auc_bootstrap(pred,ink,y,x,inv,w);assert not np.isfinite(point);assert e.math.interval(draws)['ci95'] is None
rule=json.loads((p.parent/'label-evaluation-rule.json').read_text())
manifest=json.loads((p.parent/'reader-reference/inference_manifest.json').read_text())
keys=('villa_revision','checkpoint_sha256','selected_source_layers','shuffle_seed','stride','batch_size','blend_mode','amp','mirror_tta','preprocessing')
settings={k:manifest[k] for k in keys};e.assert_frozen_settings(settings,rule)
for key,bad in {'villa_revision':'wrong','checkpoint_sha256':'wrong','selected_source_layers':list(range(17)),'shuffle_seed':1,'stride':64,'batch_size':2,'blend_mode':'mean','amp':'bf16','mirror_tta':True,'preprocessing':'changed'}.items():
    mutant=dict(settings);mutant[key]=bad
    try:e.assert_frozen_settings(mutant,rule)
    except AssertionError:pass
    else:raise AssertionError('Wrong frozen reader setting accepted: '+key)
result={'status':'passed','checks':['one interior edited vertex affects its four20px bilinear cells','zero edits produce empty support','boundary edits do not extrapolate beyond last valid native cell','anisotropic native scale preserves x/y convention','degenerate one-class cohort abstains','all10 wrong authoritative reader setting mutations rejected'],'evaluator_sha256':e.sha(p),'test_sha256':e.sha(__file__),'math_sha256':e.MATH_SHA}
r=p.parent/'evaluation-geometry-validation.json';r.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
