"""External authoritative reader audit; preserves the immutable primary evaluator."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
import argparse,hashlib,json
from pathlib import Path
import numpy as np
R=Path('/workspace/scrolls-env/phase-reconstruction')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--folder',type=Path,action='append',required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    p=R/'w045-ink-evaluation-rule.json';assert sha(p)=='688e6c97637f151e1d444ce3a54e3a6c988707d2ed296deb948a6a45e3034ec0';rule=json.loads(p.read_text())['reader']
    assert rule['name']=='d9v2' and rule['precision']=='fp32' and rule['central_planes']==17
    expected={'status':'inference_completed_scoring_pending','reader':rule['name'],'device':'cpu','villa_revision':rule['villa_revision'],'checkpoint_sha256':rule['checkpoint_sha256'],'checkpoint_state':'ema_model','exported_layer_count':28,'input_shape':[17,640,640],'selected_source_layers':list(range(6,23)),'reverse_source_layers':list(range(22,5,-1)),'shuffle_seed':rule['shuffle_seed'],'stride':rule['stride'],'batch_size':rule['batch'],'blend_mode':rule['blend'],'amp':'disabled','mirror_tta':rule['mirror_tta'],'preprocessing':'tifxyz_robust'}
    expected['shuffle_source_layers']=np.array(expected['selected_source_layers'])[np.random.default_rng(rule['shuffle_seed']).permutation(17)].tolist()
    proofs={}
    for folder in a.folder:
        path=folder/'inference_manifest.json';m=json.loads(path.read_text())
        for k,v in expected.items():assert m[k]==v,str(folder)+' wrong '+k
        for output in m['outputs'].values():assert sha(output['path'])==output['sha256']
        assert set(m['outputs'])=={'forward','reverse','shuffle'}
        proofs[str(folder)]={'manifest_sha256':sha(path),'all_authoritative_settings_match':True,'all_output_hashes_verified':True}
    record={'status':'passed','rule_sha256':sha(p),'script_sha256':sha(__file__),'primary_evaluator_unchanged_sha256':sha(R/'evaluate_w045.py'),'expected':expected,'folders':proofs,'scope':'External authoritative settings verification of listed folders only; no registration approval or score-based depth selection.'}
    with a.out.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
    print(json.dumps({'status':'passed','result_sha256':sha(a.out),'folder_count':len(a.folder)}))
if __name__=='__main__':main()
