"""Independent bounded synthetic checks; never opens actual prediction artifacts."""
import importlib.util,json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,'/workspace/Scrolls')
from kit import auc
p=Path('/workspace/scrolls-env/phase-reconstruction/evaluate_w045.py')
spec=importlib.util.spec_from_file_location('frozen_math_audit',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rng=np.random.default_rng(315);shape=(64,64)
ink=rng.random(shape)<.35;mask=rng.random(shape)<.9
maps=[rng.integers(0,256,shape,dtype=np.uint8) for _ in range(3)]
y,x,blocks,inv,weights=m.bootstrap_weights(mask,block_px=16,draws=1000,seed=20261007)
results=[]
for index,a in enumerate(maps):
 point,draws=m.auc_bootstrap(a,ink,y,x,inv,weights)
 direct=auc.auc_scores(a[y,x][ink[y,x]],a[y,x][~ink[y,x]])
 assert abs(point-direct)<1e-12
 errors=[]
 for draw in [0,1,7,23]:
  multiplicity=weights[draw,inv].astype(int);z=np.repeat(a[y,x],multiplicity);lab=np.repeat(ink[y,x],multiplicity)
  errors.append(abs(draws[draw]-auc.auc_scores(z[lab],z[~lab])))
 assert max(errors)<1e-12
 results.append({'map':index,'exact_auc_equal':True,'max_direct_resampled_auc_error':max(errors),'zeros_counted':int((a[y,x]==0).sum())})
a=rng.normal(size=len(y));b=.35*a+rng.normal(size=len(y))
mom=m.correlation_moments(a,b,inv,len(blocks));point=float(m.correlation_from_moments(mom.sum(0)));draws=m.correlation_from_moments(weights@mom)
assert abs(point-np.corrcoef(a,b)[0,1])<1e-12
errors=[]
for draw in [0,1,7,23]:
 multiplicity=weights[draw,inv].astype(int);aa=np.repeat(a,multiplicity);bb=np.repeat(b,multiplicity)
 errors.append(abs(draws[draw]-np.corrcoef(aa,bb)[0,1]))
assert max(errors)<1e-12
identity=m.simultaneous({'same-minus-same':(0.,draws-draws)})
assert identity['same-minus-same']['simultaneous_ci95']==[0.,0.]
bad=draws.copy();bad[:20]=np.nan
assert m.simultaneous({'invalid':(point,bad)})['invalid']['simultaneous_ci95'] is None
contrasts={'a':(.1,rng.normal(.1,.05,1000)),'b':(-.1,rng.normal(-.1,.02,1000))}
bands=m.simultaneous(contrasts);radius=np.percentile(np.max(np.stack([abs(v[1]-v[0]) for v in contrasts.values()],1),1),95)
for name,(point,_) in contrasts.items():np.testing.assert_allclose(bands[name]['simultaneous_ci95'],[point-radius,point+radius])
result={'code_only_no_actual_maps':True,'exact_uint8_auc_and_valid_zero_checks':results,'max_direct_resampled_correlation_error':max(errors),'paired_weights_all_maps':True,'simultaneous_family_radius_equal':True,'identical_contrast_exact_zero_band':True,'invalid_98percent_draw_family_abstains':True,'caveat':'Synthetic arithmetic checks do not calibrate empirical95percent coverage on a single correlated papyrus crop.'}
Path('/workspace/scrolls-env/supervised-overlap-audit/scoring-math-review.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
