"""Deterministic synthetic reproductions of current resume/integrity gaps, no network or inference."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import sys,json,tempfile,hashlib,io
from pathlib import Path
sys.path.insert(0,'/workspace/Scrolls')
from kit import fetch,ledger,provenance
with tempfile.TemporaryDirectory(dir='/workspace/scrolls-env/ufsm-review/controls') as td:
    root=Path(td);dest=root/'mirror';dest.mkdir();(dest/'chunk').write_bytes(b'BAD!');calls=[]
    def opener(url,timeout=0):
        calls.append(url)
        if 'list-type=' in url:return io.BytesIO(b'<ListBucketResult><Contents><Key>fixture/chunk</Key><Size>4</Size></Contents></ListBucketResult>')
        return io.BytesIO(b'GOOD')
    n,downloaded,total=fetch.fetch_prefix('fixture',dest,workers=1,opener=opener,base='https://fixture.invalid')
    fetch_case={'synthetic_only':True,'files':n,'downloaded_bytes':downloaded,'expected_total_bytes':total,'object_get_calls':sum('list-type=' not in u for u in calls),'same_size_wrong_bytes_remain':(dest/'chunk').read_bytes()==b'BAD!'}
    snapshot={'checked':'2026-10-07','first_letters':{'volumes':[]}}
    # Use the actual dated local prize snapshot; this reads local package JSON only.
    _,record=ledger.init('fixture','PHerc0813','Synthetic integrity check','Frozen before any outputs',root=root/'experiments')
    artifact=root/'artifact';artifact.write_bytes(b'ORIGINAL');ledger.add_provenance('fixture','synthetic',files=[artifact],root=root/'experiments')
    original_provenance=provenance.build('fixture','/workspace/Scrolls',inputs=[artifact]);artifact.write_bytes(b'CHANGED!')
    ledger_case={'synthetic_only':True,'ledger_check_after_recorded_file_changed':ledger.check('fixture',root=root/'experiments'),'existing_provenance_files_check_after_same_change':provenance.verify(original_provenance,recheck_files=True)}
result={'fetch':fetch_case,'ledger':ledger_case,'limits':'These reproduce existing logical guards with local synthetic files; they benchmark no network/model performance and modify no Scrolls files. Existing kit.provenance already detects changed files when explicitly called with --files.','source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path('/workspace/Scrolls/kit/fetch.py'),Path('/workspace/Scrolls/kit/ledger.py'),Path('/workspace/Scrolls/kit/provenance.py'))}}
assert fetch_case['same_size_wrong_bytes_remain'] and fetch_case['object_get_calls']==0
assert ledger_case['ledger_check_after_recorded_file_changed']==[] and ledger_case['existing_provenance_files_check_after_same_change']
p=Path('/workspace/scrolls-env/ufsm-review/controls/scrolls-gap-receipt.json');p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
