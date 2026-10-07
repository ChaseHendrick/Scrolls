"""Launch exactly four frozen actual geometry readers, two 2-thread CPU jobs."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import sys
R=Path('/workspace/scrolls-env/supervised-surfacefix')
PY=Path('/workspace/scrolls-env/inference-venv/bin/python')
ADAPTER=Path('/workspace/scrolls-env/infer_layers_cpu.py')
TAGS=('baseline','reference','minus1','plus1')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,r):
    with p.open('x') as f:json.dump(r,f,indent=2);f.write('\n')
def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--code-amendment-sha256',required=True);args=ap.parse_args()
    amendment_path=R/'schema2-code-amendment.json';assert sha(amendment_path)==args.code_amendment_sha256
    amendment=json.loads(amendment_path.read_text())
    for p,d in amendment['input_sha256'].items():assert sha(p)==d,p
    rule=R/'label-evaluation-rule.json';audit_path=R/'published-audit-result.json';audit=json.loads(audit_path.read_text());assert audit['all_pass'] is True
    assert sha(ADAPTER)=='1357601e51ff49d5487465ddd14a77de642d1fad325d51814e702b8087e30495'
    inputs={str(p):sha(p) for p in (rule,R/'rule.json',audit_path,amendment_path,ADAPTER,Path(__file__))}
    layers={}
    for tag in TAGS:
        assert not (R/('reader-'+tag)).exists(),'Preserve prior/partial output; never overwrite.'
        if tag in ('baseline','reference'):expected=audit['parts'][tag]['canonical_layer_sha256']
        else:
            rp=R/('layers-'+tag+'-receipt.json');rd=json.loads(rp.read_text());inputs[str(rp)]=sha(rp);assert rd['published_audit_sha256']==sha(audit_path);expected=rd['canonical_layer_sha256']
        assert sorted(expected)==[f'{i:02}.tif' for i in range(28)]
        layers[tag]={}
        for name,d in expected.items():
            p=R/('layers-'+tag)/name;assert sha(p)==d;layers[tag][str(p)]=d
    commands={tag:[str(PY),str(ADAPTER),'--reader','d9v2','--layers-dir',str(R/('layers-'+tag)),'--output-dir',str(R/('reader-'+tag)),'--threads','2'] for tag in TAGS}
    dump(R/'reader-orchestration-freeze.json',{'input_sha256':inputs,'canonical_layers_sha256':layers,'commands':commands,'parallel_jobs':2,'threads_each':2,'no_label_scoring_before_frozen_actual_apply':True})
    def run(tag):
        with (R/('reader-'+tag+'.log')).open('x') as f:result=subprocess.run(commands[tag],stdout=f,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(tag+' reader failed with exit '+str(result.returncode))
        m=R/('reader-'+tag)/'inference_manifest.json';data=json.loads(m.read_text());assert data['status']=='inference_completed_scoring_pending'
        assert data['layer_sha256']=={Path(p).name:d for p,d in layers[tag].items()}
        result={'tag':tag,'manifest_sha256':sha(m),'output_sha256':{k:o['sha256'] for k,o in data['outputs'].items()}}
        print(json.dumps(result),flush=True);return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,TAGS))
    dump(R/'reader-orchestration-completed.json',{'status':'all12_maps_completed_no_label_scores','freeze_sha256':sha(R/'reader-orchestration-freeze.json'),'results':results})
if __name__=='__main__':main()
