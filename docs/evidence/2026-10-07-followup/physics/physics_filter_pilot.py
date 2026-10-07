"""Exploratory, frozen same-acquisition reconstruction transfer measurement.

No renderer, inference, labels, ink claims or network accesses.
"""
from pathlib import Path
import hashlib, json, resource, sys, time, os
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
import numpy as np
from scipy import fft, ndimage
from register_ct_pilot import load_patch, peak, digest

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'physics-filter-pilot'
RULE=OUT/'rule.json'

def freeze():
    OUT.mkdir(exist_ok=True)
    if RULE.exists():raise RuntimeError('Refusing frozen rule overwrite')
    source=json.loads((ROOT/'registration-rule.json').read_text())
    rule={'schema':1,'scope':'Public PHerc0139 structural CT, pag0 versus pag50 only; no labels or inference',
          'source_rule_sha256':digest((ROOT/'registration-rule.json').read_bytes()),
          'script_sha256':digest(Path(__file__).read_bytes()),
          'patches':[r for r in source['requests'] if r['volume'] in ['pag0','pag50']],
          'alignment':{'template128_search160':True,'require_integer_shift_zyx':[0,0,0],'minimum_gradient_ncc':.6,'minimum_peak_margin':.03,'require_interior_peak':True},
          'split':'cube0 learns all transfer/gain/offset coefficients; disjoint cube1 is held back',
          'filter':'32 fixed radial bins of Re(cross-spectrum)/input spectrum power, using separable Hann window; no fitted upper bound or positivity clip; apply coefficients to unwindowed heldback FFT and evaluate center96cube',
          'baseline':'one global affine contrast fit on cube0 applied unchanged to cube1',
          'primary':'heldback residual RMS divided by pag50 std, and relative RMS reduction versus affine baseline',
          'positive_gate':{'maximum_normalized_rms':.15,'minimum_rms_reduction':.2,'minimum_prediction_correlation':.95},
          'band_voxel_wavelengths':[[2,4],[4,8],[8,16],[16,32]],
          'controls':{'self':'same pag0 input/target gives normalizedRMS<=1e-4 and correlation>=.9999','misregistered':'pag50 x-shift8vox must lower heldback correlation>=.1','depth_shuffle':'pag50 fixed depth permutation seed20261007 must lower heldback correlation>=.1'},
          'resources':{'max_peak_rss_bytes':2*1024**3,'cpu_threads':1,'network_bytes':0},
          'readout':'TRANSFER_PREDICTABLE only if alignment, prediction and all controls pass; otherwise NEGATIVE_OR_INCONCLUSIVE. This measures reconstruction redundancy/attenuation, not independent acquisition, noise, ink, topology or legibility.'}
    RULE.write_text(json.dumps(rule,indent=2)+'\n')
    print('FROZEN',digest(RULE.read_bytes()))

def centered(a,n=128):
    lo=(np.asarray(a.shape)-n)//2
    return a[tuple(slice(int(x),int(x+n)) for x in lo)].astype(np.float32)

def arrays(rule):
    return {name:[load_patch(next(r for r in rule['patches'] if r['volume']==name and r['patch']==p)) for p in range(2)] for name in ['pag0','pag50']}

def prepare_grid(n=128):
    freqs=[fft.fftfreq(n),fft.fftfreq(n),fft.rfftfreq(n)]
    radius=np.sqrt(freqs[0][:,None,None]**2+freqs[1][None,:,None]**2+freqs[2][None,None,:]**2).astype(np.float32)
    bins=np.minimum((radius/(np.sqrt(3)/2)*32).astype(int),31)
    h=np.hanning(n).astype(np.float32)
    window=h[:,None,None]*h[None,:,None]*h[None,None,:]
    return radius,bins,window

def spectra(a,b,window):
    return fft.rfftn((a-a.mean())*window,workers=1),fft.rfftn((b-b.mean())*window,workers=1)

def fit_transfer(a,b,bins,window):
    fa,fb=spectra(a,b,window)
    cross=(fa.conj()*fb).real
    power=(fa.conj()*fa).real
    c=np.bincount(bins.ravel(),weights=cross.ravel(),minlength=32)
    p=np.bincount(bins.ravel(),weights=power.ravel(),minlength=32)
    response=np.divide(c,p,out=np.zeros_like(c),where=p>1e-10)
    am=a.mean();bm=b.mean();gain=float(np.mean((a-am)*(b-bm))/np.mean((a-am)**2))
    return response,gain,float(bm-gain*am),float(am),float(bm)

def predict(a,response,bins,am,bm):
    return fft.irfftn(fft.rfftn(a-am,workers=1)*response[bins],s=a.shape,workers=1)+bm

def summary(pred,b):
    p=centered(pred,96).astype(np.float64).ravel();q=centered(b,96).astype(np.float64).ravel()
    rms=float(np.sqrt(np.mean((p-q)**2)));sd=float(q.std())
    return {'rms_uint8_units':rms,'target_std_uint8_units':sd,'normalized_rms':rms/sd,'correlation':float(np.corrcoef(p,q)[0,1])}

def bands(a,b,radius,window):
    fa,fb=spectra(a,b,window);aa=np.abs(fa)**2;bb=np.abs(fb)**2;c=fa.conj()*fb
    rows=[]
    for lo,hi in [[2,4],[4,8],[8,16],[16,32]]:
        mask=(radius>=1/hi)&(radius<1/lo)
        pa=float(aa[mask].sum());pb=float(bb[mask].sum());cross=complex(c[mask].sum())
        rows.append({'wavelength_vox':[lo,hi],'wavelength_um':[lo*9.362,hi*9.362],'pag50_to_pag0_rms_ratio':(pb/pa)**.5,'magnitude_squared_coherence':abs(cross)**2/(pa*pb),'real_cross_transfer':cross.real/pa})
    return rows

def run():
    rule=json.loads(RULE.read_text())
    assert rule['script_sha256']==digest(Path(__file__).read_bytes())
    assert rule['source_rule_sha256']==digest((ROOT/'registration-rule.json').read_bytes())
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    try:os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    except AttributeError:pass
    started=time.monotonic();raw=arrays(rule);alignment=[]
    for p in range(2):
        a=centered(raw['pag0'][p],128);b=centered(raw['pag50'][p],160)
        r=peak(a,b);r['patch']=p
        r['pass']=r['shift_zyx_vox']==[0,0,0] and r['ncc']>=.6 and r['peak_margin']>=.03 and not r['boundary']
        alignment.append(r)
        print('ALIGN',json.dumps(r),flush=True)
    result={'rule_sha256':digest(RULE.read_bytes()),'alignment':alignment,'limits':rule['readout']}
    if not all(r['pass'] for r in alignment):
        result['outcome']='PAIR_ALIGNMENT_FAILED';save(result);return
    a=[centered(v) for v in raw['pag0']];b=[centered(v) for v in raw['pag50']]
    radius,bins,window=prepare_grid()
    response,gain,offset,am,bm=fit_transfer(a[0],b[0],bins,window)
    predicted=predict(a[1],response,bins,am,bm)
    primary=summary(predicted,b[1]);base=summary(gain*a[1]+offset,b[1]);primary['rms_reduction_vs_affine']=1-primary['rms_uint8_units']/base['rms_uint8_units']
    self_response,self_gain,self_off,self_am,self_bm=fit_transfer(a[0],a[0],bins,window)
    self_stats=summary(predict(a[1],self_response,bins,self_am,self_bm),a[1])
    shift_stats=summary(predicted,np.roll(b[1],8,axis=2))
    rng=np.random.default_rng(20261007)
    shuffle_stats=summary(predicted,b[1][rng.permutation(128)])
    controls={'self':dict(self_stats,passed=self_stats['normalized_rms']<=1e-4 and self_stats['correlation']>=.9999),
              'misregistered':dict(shift_stats,correlation_drop=primary['correlation']-shift_stats['correlation'],passed=primary['correlation']-shift_stats['correlation']>=.1),
              'depth_shuffle':dict(shuffle_stats,correlation_drop=primary['correlation']-shuffle_stats['correlation'],passed=primary['correlation']-shuffle_stats['correlation']>=.1)}
    passed=primary['normalized_rms']<=.15 and primary['rms_reduction_vs_affine']>=.2 and primary['correlation']>=.95 and all(v['passed'] for v in controls.values())
    result.update(outcome='TRANSFER_PREDICTABLE' if passed else 'NEGATIVE_OR_INCONCLUSIVE',primary=primary,affine_baseline=base,controls=controls,
                  affine_gain=gain,affine_offset=offset,radial_transfer=response.tolist(),bands=[dict(patch=p,measurements=bands(a[p],b[p],radius,window)) for p in range(2)],
                  elapsed_seconds=time.monotonic()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    save(result)

def save(result):
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('RESULT',json.dumps(result),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--freeze']:freeze()
    else:run()
