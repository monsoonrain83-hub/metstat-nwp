import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image
import global_nwp_stage as g

class GlobalNWPTests(unittest.TestCase):
    def test_global_raster_north_up_and_physically_checked(self):
        with tempfile.TemporaryDirectory() as td:
            arr = 273.15 + np.linspace(38,-38,61, dtype=np.float32)[:,None] + np.zeros((61,120),np.float32)
            out=Path(td)/'world.webp'
            stats=g.render(arr,'t2m',out)
            self.assertEqual((stats['width'],stats['height']),(120,61))
            with Image.open(out) as im:
                self.assertNotEqual(im.getpixel((20,0)), im.getpixel((20,60)))
            self.assertEqual(stats['finite_fraction'],1.0)
            for p,v in [('z500',5400.0),('mslp',101300.0)]:
                z=Path(td)/(p+'.webp')
                self.assertTrue(g.render(np.full((61,120),v,np.float32),p,z)['finite_fraction']>0.9)
    def test_native_field_survives_missing_or_failed_coarse_source(self):
        class Fake:
            def __init__(self, dom, exists, error=False):
                self.dom,self.present,self.error=dom,exists,error
            def exists(self,run,valid):return self.present
            def read(self,run,valid,fields):
                if self.error:raise OSError('archive temporarily unavailable')
                return {fields[0]:np.ones((2,3),np.float32)}
        now=datetime(2026,11,21,0,tzinfo=timezone.utc)
        hi=Fake('ecmwf_ifs',True)
        for coarse in (Fake('ecmwf_ifs025',False),Fake('ecmwf_ifs025',True,True)):
            errors=[]
            found=g.read_independent_sources((coarse,hi),now,now,
                                             ['temperature_2m'],errors)
            self.assertIn('ecmwf_ifs',found)
            self.assertNotIn('ecmwf_ifs025',found)
            self.assertEqual(found['ecmwf_ifs']['temperature_2m'].shape,(2,3))
        self.assertEqual(len(errors),1)

    def test_metadata_bbox_and_time(self):
        dt=datetime(2026,11,21,12,tzinfo=timezone.utc)
        v=datetime(2026,11,22,12,tzinfo=timezone.utc)
        m=g.product_manifest('gfs',dt,v,g.DOMAINS['gfs'],{})
        self.assertEqual(m['bbox_wgs84'],[-180.0,-90.0,180.0,90.0])
        self.assertTrue(m['full_globe'])
        self.assertFalse(m['mock'])
        self.assertEqual(m['projection'],'EPSG:4326 equirectangular')
    def test_requested_360h_is_reachable_without_fabrication(self):
        start=datetime(2026,11,21,0,tzinfo=timezone.utc)
        m={'valid_times':['2026-11-21T00:00','2026-12-06T00:00']}
        self.assertEqual(g.valid_candidates(m,start,360)[0],datetime(2026,12,6,0,tzinfo=timezone.utc))
        self.assertEqual(g.valid_candidates(m,start,361)[0],datetime(2026,12,6,0,tzinfo=timezone.utc))

    def test_select_lead_and_reject_bad_data(self):
        m={'valid_times':['2026-11-21T12:00','2026-11-22T12:00','2026-11-26T12:00']}
        dt=datetime(2026,11,21,12,tzinfo=timezone.utc)
        self.assertEqual(g.valid_candidates(m,dt,24)[0].day,22)
        with self.assertRaises(ValueError):g.to_units('z500',np.full((2,3),100.0))
        with self.assertRaises(ValueError):g.to_units('t2m',np.full((2,3),600.0))

if __name__=='__main__':unittest.main()
