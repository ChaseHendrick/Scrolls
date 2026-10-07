"""Fetch only listed public control ink map and matching labels, <=100 MB."""
from pathlib import Path
import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
BASE = 'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/'
SEGMENT = 'PHerc0841/segments/20260220213127-w00/'
root = ET.fromstring((OUT/'w00-prefix.xml').read_bytes())
ns = {'s': root.tag.split('}')[0][1:]}
listed = [(x.findtext('s:Key', namespaces=ns), int(x.findtext('s:Size', namespaces=ns)))
          for x in root.findall('s:Contents', ns)]
label_prefix = SEGMENT+'ink-labels/2.403um-volume-20260319124803/20260918/'
selected = [(k,n) for k,n in listed if
            (k.startswith(SEGMENT+'ink-detection/') and k.endswith('.tif')) or
            any(k.startswith(label_prefix+name+'.zarr/') for name in ('inklabels','supervision'))]
assert len([k for k,n in selected if k.endswith('.tif')]) == 1
assert sum(n for k,n in selected) <= 100_000_000
receipts = []
downloaded = 0
for key, expected_size in selected:
    dst = OUT/'public-inputs'/key[len(SEGMENT):]
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = BASE+key
    if not dst.exists():
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(expected_size+1)
        assert len(data) == expected_size
        downloaded += len(data)
        assert downloaded <= 100_000_000
        dst.write_bytes(data)
    assert dst.stat().st_size == expected_size
    receipts.append({'url':url,'path':str(dst),'bytes':expected_size,
                     'sha256':hashlib.sha256(dst.read_bytes()).hexdigest()})
(OUT/'public-input-receipt.json').write_text(json.dumps(receipts,indent=2)+'\n')
print(json.dumps({'files':len(receipts),'bytes':sum(x['bytes'] for x in receipts)},indent=2))
