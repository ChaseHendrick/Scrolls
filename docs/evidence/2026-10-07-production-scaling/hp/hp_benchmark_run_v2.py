from pathlib import Path
import subprocess,json,time,hashlib,statistics,sys
root=Path('/workspace/scrolls-env/production-speed-v2');python='/workspace/Scrolls/.venv/bin/python'
freeze=json.loads((root/'hp-candidate-freeze-v2.json').read_text())
for path,digest in freeze['files_sha256'].items():
    if hashlib.sha256((root/path).read_bytes()).hexdigest()!=digest:raise RuntimeError('Code freeze changed: '+path)
sys.path.insert(0,str(root/'scoring-baseline'))
from kit import provenance
inputs=json.loads((root/'hp-input-freeze.json').read_text())['inputs']
def verify_inputs():
    for item in inputs:
        if provenance.fingerprint(item['path'])['sha256']!=item['sha256']:raise RuntimeError('Frozen input changed: '+item['path'])
verify_inputs()
reference=json.loads((root/'hp-baseline-results.json').read_text());results=[]
def cli_run(variant,case):
    start=time.perf_counter();proc=subprocess.run([python,str(root/'hp_benchmark_cli_v2.py'),variant,case],capture_output=True,text=True,check=True);wall=time.perf_counter()-start
    value=json.loads(proc.stdout)
    if value!=reference[case]['hp_files']:raise RuntimeError('CLI output mismatch: '+variant+' '+case)
    timing=json.loads(next(line[9:] for line in proc.stderr.splitlines() if line.startswith('RSS_JSON ')))
    return value,wall,timing
for case in ('real640','public2560'):
    if case=='public2560':
        for variant in ('scoring-baseline','scoring'):cli_run(variant,case)
    for pair in range(5):
        order=['scoring-baseline','scoring'] if pair%2==0 else ['scoring','scoring-baseline']
        for position,variant in enumerate(order):
            if case=='real640':
                start=time.perf_counter();proc=subprocess.run([python,str(root/'hp_benchmark_worker.py'),variant,case],capture_output=True,text=True,check=True);wall=time.perf_counter()-start
                val=json.loads(proc.stdout)
                if val['outputs']!=reference[case]:raise RuntimeError('File output mismatch')
                val['worker_process_wall_s']=wall
            else:val={'variant':variant,'case':case,'operation_times_s':{}}
            cli_value,cli_wall,timing=cli_run(variant,case)
            if case=='public2560':
                val['outputs']={'hp_files':cli_value};val['operation_times_s']['hp_files']=timing['hp_operation_s']
            val.update(pair=pair,position=position,cli_process_wall_s=cli_wall,cli_hp_operation_s=timing['hp_operation_s'],cli_peak_rss_kib=timing['process_peak_rss_kib'],exact_outputs=True)
            results.append(val);(root/'hp-benchmark-raw.json').write_text(json.dumps(results,indent=2)+'\n')
            print(case,pair,variant,'HP',round(val['operation_times_s']['hp_files'],4),'CLI',round(cli_wall,4),flush=True)
verify_inputs()
summary={'exact_outputs':True,'pairs_per_case':5,'cases':{},'rule_sha256':hashlib.sha256((root/'hp-benchmark-rule.json').read_bytes()).hexdigest(),'amendment_sha256':hashlib.sha256((root/'hp-benchmark-amendment.json').read_bytes()).hexdigest()}
for case in ('real640','public2560'):
    rows=[r for r in results if r['case']==case];names=['hp_files','cli_process_wall_s','cli_hp_operation_s','cli_peak_rss_kib']
    if case=='real640':names+=['auc_files','rows_files','full_pipeline','worker_process_wall_s','process_peak_rss_kib']
    summary['cases'][case]={}
    for name in names:
        get=lambda r:r[name] if name in r else r['operation_times_s'][name]
        baseline=[get(r) for r in rows if r['variant']=='scoring-baseline'];candidate=[get(r) for r in rows if r['variant']=='scoring']
        ratios=[get(next(r for r in rows if r['pair']==p and r['variant']=='scoring-baseline'))/get(next(r for r in rows if r['pair']==p and r['variant']=='scoring')) for p in range(5)]
        summary['cases'][case][name]={'baseline_values':baseline,'candidate_values':candidate,'baseline_median':statistics.median(baseline),'candidate_median':statistics.median(candidate),'ratio_of_medians':statistics.median(baseline)/statistics.median(candidate),'paired_ratios':ratios}
(root/'hp-benchmark-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
