"""Offline world release packaging regression; no real source claims."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
import numpy as np
import global_nwp_stage as g
from pack_world_frames import package_frames

class WorldFrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.src=self.base/'src';self.dest=self.base/'release'
        self.run=datetime(2026,11,26,0,tzinfo=timezone.utc)
    def frame(self,lead,tag='',run=None,domain='ecmwf_ifs025'):
        run=run or self.run;valid=run+timedelta(hours=lead)
        d=self.src/f'world-ecmwf-{lead}{tag}';d.mkdir(parents=True)
        name=f'ecmwf_t2m_{valid:%Y%m%d%H}.webp'
        values=np.tile(np.linspace(260,300,720,dtype=np.float32),(361,1))
        stats=g.render(values,'t2m',d/name)
        field=dict(file=name,variable='temperature_2m',logical_model='ecmwf',units='°C',
                   nominal_resolution='28 km',field_source_domain=domain,lead_hours=lead,
                   init_utc=run.strftime('%Y-%m-%dT%H:%M:%SZ'),valid_utc=valid.strftime('%Y-%m-%dT%H:%M:%SZ'),
                   source_grid=[720,361],source_grid_origin=[-180,-90],source_grid_spacing=[.5,.5],
                   sha256=hashlib.sha256((d/name).read_bytes()).hexdigest(),**stats)
        m=g.product_manifest('ecmwf',run,valid,domain,{'t2m':field})
        (d/'manifest.json').write_text(json.dumps(m))
        return d
    def test_two_exact_frames_immutable_paths(self):
        self.frame(48);self.frame(24)
        c=package_frames(self.src,self.dest)
        self.assertFalse(c['complete']);self.assertEqual(c['available_models'],['ecmwf'])
        f=c['models']['ecmwf']['parameters']['t2m']
        self.assertEqual([r['lead_hours'] for r in f],[24,48])
        self.assertNotEqual(f[0]['file'],f[1]['file'])
        for r in f:self.assertEqual(hashlib.sha256((self.dest/r['file']).read_bytes()).hexdigest(),r['sha256'])
        with self.assertRaises(FileExistsError):package_frames(self.src,self.dest)
    def test_mixed_cycle_rejected_without_partial_release(self):
        self.frame(24);self.frame(48,run=self.run-timedelta(hours=6))
        with self.assertRaisesRegex(ValueError,'mixed initialization'):package_frames(self.src,self.dest)
        self.assertFalse(self.dest.exists())
    def test_duplicate_rejected(self):
        self.frame(24);self.frame(24,'dup')
        with self.assertRaisesRegex(ValueError,'duplicate'):package_frames(self.src,self.dest)
        self.assertFalse(self.dest.exists())
    def test_budget_rejects_atomically(self):
        self.frame(24)
        with self.assertRaisesRegex(ValueError,'budget'):package_frames(self.src,self.dest,100)
        self.assertFalse(self.dest.exists())
    def test_wrong_model_source_rejected(self):
        self.frame(24,domain='ncep_gfs025')
        with self.assertRaisesRegex(ValueError,'source differs'):package_frames(self.src,self.dest)
        self.assertFalse(self.dest.exists())
if __name__=='__main__':unittest.main()
