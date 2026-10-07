"""Verify PR24's frozen record against its historical source export."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path('/workspace/Scrolls')
BASELINE = Path('/workspace/scrolls-env/production-speed-v2/scoring-baseline')
REF = 'c43c41a59ac3793b9a653fa236165f6f6b9d47a4'
REL = 'docs/evidence/2026-10-07-production-speed.provenance.json'
sys.path.insert(0, str(ROOT))
from kit import provenance

expected = subprocess.check_output(['git', 'show', f'{REF}:{REL}'], cwd=ROOT)
assert (ROOT / REL).read_bytes() == expected
assert (BASELINE / REL).read_bytes() == expected
record = json.loads(expected)
os.chdir(BASELINE)
problems = provenance.verify(record, recheck_files=True)
assert not problems, problems
os.chdir(ROOT)
historical_paths = [p.as_posix() for p in Path('docs/evidence').iterdir()
                    if p.name != '2026-10-07-production-scaling'
                    and p.name != '2026-10-07-production-scaling.provenance.json']
subprocess.run(['git', 'diff', '--exit-code', REF, '--', *historical_paths], check=True)
result = {'historical_ref': REF, 'record': REL, 'digest': record['digest'],
          'canonical_record_and_all_historical_fingerprints_valid': True,
          'prior_tracked_evidence_unchanged': True,
          'scope': 'PR24 source/docs checked in its frozen export; earlier archives unchanged against PR24.'}
out = Path('/workspace/scrolls-env/production-speed-v2/integration/prior-seal-check.json')
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
