"""Offline contracts for public field inventory and catalog-origin routing."""
import ast
import json
from pathlib import Path
import types
import unittest

SPACE=Path(__file__).resolve().parents[1]/'spaces/lasagna-fields'

def functions(file,names,context):
    tree=ast.parse((SPACE/file).read_text())
    body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(body)==len(names)
    exec(compile(ast.Module(body=body,type_ignores=[]),str(SPACE/file),'exec'),context)
    return types.SimpleNamespace(**context)

class CoverageContracts(unittest.TestCase):
    def test_existing_fields_preserve_keys_and_add_provenance(self):
        doc=json.loads((SPACE/'fields.json').read_text())
        app=functions('app.py',{'list_fields'},dict(field_doc=lambda:doc))
        rows=app.list_fields();self.assertEqual(len(rows),56)
        for r in rows:
            self.assertLessEqual({'scroll','volume','manifest','stream','dataset','note','normal_source','availability','provenance'},set(r))
            self.assertIsNone(r['availability']['whole_volume_complete'])
            self.assertNotIn('/fibers/',r['manifest'])
        self.assertEqual(len(app.list_fields('Paris4')),1)
        self.assertEqual(app.list_fields('not-a-scroll'),[])

    def test_coverage_includes_missing_volumes_and_no_volume_fragments(self):
        app=functions('app.py',{'list_coverage'},dict(json=json,HERE=SPACE))
        c=app.list_coverage();self.assertEqual(len(c['samples']),45)
        vols=[v for s in c['samples'] for v in s['volumes']]
        self.assertEqual(len(vols),74)
        self.assertEqual(sum(not v['available_models'] for v in vols),18)
        self.assertEqual(sum(s['coverage']=='no_catalog_volume' for s in c['samples']),6)
        self.assertEqual(len(app.list_coverage('PHercParis4')['samples']),1)
        self.assertEqual(app.list_coverage('not-a-scroll')['samples'],[])

    def test_ct_origin_uses_declared_public_paths(self):
        l=functions('lasfield.py',{'public_ct_urls'},dict(BUCKET='https://bucket.example'))
        origin=lambda typ,url,path:{'type':typ,'origins':[{'path':path,'access_roots':[{'usage':'public-read','url':url}]}]}
        v={'data':[origin('ome-zarr','https://data.aws.ash2txt.org','samples/PHerc0332/volumes/legacy/'),
                   origin('ome-zarr-vcd3d','s3://vesuvius-challenge-open-data','compressed/'),
                   origin('lasagna','s3://vesuvius-challenge-open-data','predictions/fibers/') ]}
        self.assertEqual(l.public_ct_urls(v),['https://data.aws.ash2txt.org/samples/PHerc0332/volumes/legacy/'])
        self.assertEqual(l.public_ct_urls({'data':[origin('ome-zarr','s3://vesuvius-challenge-open-data','scan/')]}),['https://bucket.example/scan/'])
        self.assertEqual(l.public_ct_urls({'data':[origin('ome-zarr','s3://private','scan/')]}),[])

if __name__=='__main__':unittest.main()
