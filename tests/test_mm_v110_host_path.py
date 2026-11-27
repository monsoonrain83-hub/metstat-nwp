"""V110 canonical host publication plan (offline; no host credentials)."""
import tempfile,json,hashlib,unittest
from pathlib import Path
from plan_world_host import plan

class HostPlan(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'catalog.json'
        run='2026112606';valid='2026112706';data=b'fixture bytes';sha=hashlib.sha256(data).hexdigest()
        file=f'ecmwf/{run}/cape/{valid}_{sha[:16]}.webp'
        q=self.root/file;q.parent.mkdir(parents=True);q.write_bytes(data)
        self.f=dict(file=file,sha256=sha,logical_model='ecmwf',variable='cape',init_utc='2026-11-26T06:00:00Z',valid_utc='2026-11-27T06:00:00Z',
                    lead_hours=24,palette='cape',units='J/kg',bbox_wgs84=[-180,-90,180,90],projection='EPSG:4326 equirectangular',
                    field_source_domain='ecmwf_ifs',nominal_resolution='9 km',finite_fraction=1,width=720,height=361)
        self.c=dict(schema=2,mock=False,world_bounds=[-180,-90,180,90],models={'ecmwf':{'run_utc':self.f['init_utc'],'parameters':{'cape':[self.f]}}})
        self.h={'models':{'ecmwf':{'run':run}},'params':[{'id':'cape','sc':'cape'}]}
    def execute(self):
        self.path.write_text(json.dumps(self.c));return plan(self.path,self.h)
    def test_one_path(self):
        r=self.execute()
        self.assertFalse(r['deploy'])
        self.assertEqual(r['manifest'],'online/data/manifest.json')
        self.assertEqual(r['records'][0]['destination'],'online/data/nwp/ecmwf/2026112606/world/cape_2026112706.webp')
    def test_cycle_not_advanced(self):
        self.h['models']['ecmwf']['run']='2026112612'
        r=self.execute();self.assertFalse(r['records']);self.assertIn('cycle mismatch',r['deferred'][0][2])
    def test_incompatible_palette_deferred(self):
        self.h['params'][0]['sc']='rh'
        self.assertFalse(self.execute()['records'])
    def test_checksum_fail_closed(self):
        (self.root/self.f['file']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):self.execute()
    def test_traversal_rejected(self):
        self.f['file']='../../x'
        with self.assertRaisesRegex(ValueError,'staging path'):self.execute()
    def test_duplicate_rejected(self):
        self.c['models']['ecmwf']['parameters']['cape'].append(self.f)
        with self.assertRaisesRegex(ValueError,'duplicate'):self.execute()
if __name__=='__main__':unittest.main()
