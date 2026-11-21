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

    def test_cycle_candidates_do_not_depend_on_coarse_metadata(self):
        class Fake:
            def __init__(self, entries=None, broken=False):
                self.entries, self.broken = entries or [], broken
            def runs(self):
                if self.broken:
                    raise OSError('temporarily unavailable metadata')
                return self.entries

        high = Fake([{'reference_time':'2026-11-21T00:00:00Z',
                      'valid_times':['2026-11-22T00:00', '2026-12-06T00:00']}])
        for coarse in (Fake(), Fake(broken=True)):
            cycles = g.cycle_candidates(coarse, high)
            self.assertEqual(len(cycles), 1)
            self.assertEqual(cycles[0]['reference_time'], '2026-11-21T00:00')
            self.assertEqual(g.valid_candidates(cycles[0],
                datetime(2026,11,21,tzinfo=timezone.utc), 360)[0],
                datetime(2026,12,6,tzinfo=timezone.utc))

    def test_union_same_cycle_valid_hours_without_mixing_different_cycles(self):
        coarse = type('Source', (), {'runs':lambda self: [
            {'reference_time':'2026-11-21T00:00:00Z',
             'valid_times':['2026-11-22T00:00', 'not-a-time']},
            {'reference_time':'2026-11-20T12:00:00Z',
             'valid_times':['2026-11-21T12:00']} ]})()
        high = type('Source', (), {'runs':lambda self: [
            {'reference_time':'2026-11-21T00:00:00Z',
             'valid_times':['2026-12-06T00:00','2026-11-22T00:00']} ]})()
        cycles = g.cycle_candidates(coarse, high)
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0]['valid_times'],
                         ['2026-11-22T00:00', '2026-12-06T00:00'])
        self.assertEqual(cycles[1]['reference_time'], '2026-11-20T12:00')

    def test_manifest_root_is_true_selected_high_resolution_source(self):
        from datetime import timedelta
        t=datetime(2026,11,21,0,tzinfo=timezone.utc)
        v=t+timedelta(hours=240)
        fields={'t2m':{'field_source_domain':'ecmwf_ifs','nominal_resolution':'9 km'},
                'z500':{'field_source_domain':'ecmwf_ifs025','nominal_resolution':'28 km'}}
        mixed=g.product_manifest('ecmwf',t,v,'ecmwf_ifs025',fields)
        self.assertEqual(mixed['source_domain'],'mixed-per-field')
        self.assertEqual(mixed['schema'],2)
        self.assertTrue(mixed['generated_at_utc'].endswith('Z'))
        high=g.product_manifest('ecmwf',t,v,'ecmwf_ifs025',{'t2m':fields['t2m']})
        self.assertEqual(high['source_domain'],'ecmwf_ifs')

    def test_rendered_webp_file_hash_matches_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            dest=Path(td)/'real.webp'
            g.render(np.full((32,64),273.15,dtype=np.float32),'t2m',dest)
            self.assertEqual(len(hashlib.sha256(dest.read_bytes()).hexdigest()),64)

    def test_extended_pressure_level_catalog_is_opt_in_and_complete(self):
        self.assertEqual(set(g.EXTRA_FIELDS), {
            'z850','z700','z300','z200',
            't850','t700','t500','t300','t200',
            'rh850','rh700','rh500','rh300','rh200'})
        self.assertEqual(set(g.FIELDS),{'t2m','z500','mslp'})
        self.assertEqual(g.field_spec('z200')[1],'dam')
        self.assertEqual(g.field_spec('t850')[1],'°C')
        with self.assertRaises(ValueError):g.field_spec('fake')

    def test_850_500_200_height_units_converted(self):
        for p,metres,dam in [('z850',1500.,150.),('z500',5800.,580.),('z200',12000.,1200.)]:
            actual=g.to_units(p,np.full((8,12),metres,np.float32))
            self.assertAlmostEqual(float(np.nanmedian(actual)),dam,places=2)
        geopotential=5800.*9.80665
        self.assertAlmostEqual(float(np.nanmedian(
            g.to_units('z500',np.full((8,12),geopotential,np.float32)))),580.,places=2)
        with self.assertRaises(ValueError):
            g.to_units('z200',np.full((8,12),40.,np.float32))

    def test_temperature_and_relative_humidity_units(self):
        t=g.to_units('t700',np.full((10,15),243.15,np.float32))
        self.assertAlmostEqual(float(np.nanmedian(t)),-30.,places=3)
        rh=g.to_units('rh850',np.full((10,15),0.65,np.float32))
        self.assertAlmostEqual(float(np.nanmedian(rh)),65.,places=2)
        with self.assertRaises(ValueError):
            g.to_units('rh500',np.full((10,15),250.,np.float32))
        with self.assertRaises(ValueError):
            g.to_units('t850',np.full((10,15),100.,np.float32))

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
