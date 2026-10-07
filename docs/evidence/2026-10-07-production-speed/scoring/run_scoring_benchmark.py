from pathlib import Path
import subprocess,json,time,statistics,hashlib
root=Path('/workspace/scrolls-env/production-speed');python='/workspace/Scrolls/.venv/bin/python'
freeze=json.loads((root/'scoring-candidate-freeze.json').read_text())
for path,expected in freeze['files_sha256'].items():
    if hashlib.sha256((root/path).read_bytes()).hexdigest()!=expected:raise RuntimeError('Candidate freeze changed: '+path)
results=[];reference=json.loads((root/'scoring-baseline-results.json').read_text())
for pair in range(6):
    order=['scoring-baseline','scoring'] if pair%2==0 else ['scoring','scoring-baseline']
    for position,variant in enumerate(order):
        start=time.perf_counter();proc=subprocess.run([python,str(root/'benchmark_scoring.py'),variant],capture_output=True,text=True,check=True);wall=time.perf_counter()-start
        value=json.loads(proc.stdout)
        if value['outputs']!=reference:raise RuntimeError('Output mismatch in '+variant)
        start=time.perf_counter();cli=subprocess.run([python,str(root/'benchmark_scoring_cli.py'),variant],capture_output=True,text=True,check=True);cli_wall=time.perf_counter()-start
        cli_value=json.loads(cli.stdout)
        if cli_value!=reference['auc_files']:raise RuntimeError('CLI output mismatch in '+variant)
        value.update(pair=pair,position=position,worker_process_wall_s=wall,cli_process_wall_s=cli_wall,exact_output_match=True,cli_exact_output_match=True)
        results.append(value)
        (root/'scoring-benchmark-raw.json').write_text(json.dumps(results,indent=2)+'\n')
        print(pair,variant,'AUC',round(value['operation_times_s']['auc_files'],5),'CLI',round(cli_wall,5),flush=True)
summary={'exact_outputs':True,'pairs':6,'operations':{},'rule_sha256':hashlib.sha256((root/'scoring-benchmark-rule.json').read_bytes()).hexdigest(),'amendment_sha256':hashlib.sha256((root/'scoring-benchmark-process-amendment.json').read_bytes()).hexdigest()}
for name in ('auc_files','hp_files','rows_files','full_pipeline','cli_process_wall_s','worker_process_wall_s'):
    get=lambda r:r[name] if name.endswith('_s') else r['operation_times_s'][name]
    baseline=[get(r) for r in results if r['variant']=='scoring-baseline'];candidate=[get(r) for r in results if r['variant']=='scoring']
    ratios=[]
    for pair in range(6):
        a=next(r for r in results if r['pair']==pair and r['variant']=='scoring-baseline');b=next(r for r in results if r['pair']==pair and r['variant']=='scoring')
        ratios.append(get(a)/get(b))
    summary['operations'][name]={'baseline_times_s':baseline,'candidate_times_s':candidate,'baseline_median_s':statistics.median(baseline),'candidate_median_s':statistics.median(candidate),'ratio_of_medians':statistics.median(baseline)/statistics.median(candidate),'paired_speedup_median':statistics.median(ratios),'paired_speedups':ratios,'paired_speedup_range':[min(ratios),max(ratios)]}
(root/'scoring-benchmark-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
