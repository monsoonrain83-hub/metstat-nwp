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

    def test_exact_hour_only_and_missing_lead_fail_closed(self):
        run = datetime(2026, 11, 21, 0, tzinfo=timezone.utc)
        meta = {'valid_times': ['2026-11-22T00:00Z', '2026-12-06T00:00Z']}
        self.assertEqual(g.valid_candidates(meta, run, 24),
                         [datetime(2026, 11, 22, tzinfo=timezone.utc)])
        self.assertEqual(g.valid_candidates(meta, run, 360),
                         [datetime(2026, 12, 6, tzinfo=timezone.utc)])
        self.assertEqual(g.valid_candidates(meta, run, 240), [])
        self.assertEqual(g.valid_candidates(meta, run, 361), [])
        for value in (-1, 385, 24.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                g.valid_candidates(meta, run, value)

    def test_global_geometry_rejects_regional_and_corrupt_grid(self):
        from types import SimpleNamespace as Grid
        real = Grid(nx=1440, ny=721, lo0=-180., la0=-90., dx=.25, dy=.25)
        arr = np.ones((721, 1440), np.float32)
        self.assertEqual(g.validate_global_geometry(real, arr).shape, arr.shape)
        gfs = Grid(nx=3072, ny=1536, lo0=-180., la0=-.11714935 * 1535 / 2,
                   dx=360 / 3072, dy=.11714935)
        self.assertEqual(g.validate_global_geometry(
            gfs, np.ones((1536, 3072), np.float32)).shape, (1536, 3072))
        for bad in (
            Grid(nx=1440, ny=721, lo0=20., la0=-90., dx=.25, dy=.25),
            Grid(nx=1440, ny=721, lo0=-180., la0=10., dx=.25, dy=.25),
            Grid(nx=1440, ny=721, lo0=-180., la0=-90., dx=-.25, dy=.25),
            Grid(nx=1440, ny=721, lo0=-180., la0=-90., dx=float('nan'), dy=.25),
        ):
            with self.subTest(grid=bad), self.assertRaises(ValueError):
                g.validate_global_geometry(bad, arr)
        with self.assertRaises(ValueError):
            g.validate_global_geometry(real, np.ones((700, 1000), np.float32))

    def test_acquire_refuses_nearest_step_even_if_data_exist(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        class FakeSource:
            def __init__(self, domain, fs):
                self.dom = domain
                self.nx, self.ny = 720, 361
                self.lo0, self.la0, self.dx, self.dy = -180, -90, .5, .5
            def runs(self):
                return [{'reference_time': '2026-11-21T00:00:00Z',
                         'valid_times': ['2026-11-22T00:00:00Z']}]
            def exists(self, run, valid):
                raise AssertionError('No source may be read for missing +360h')

        fake_s3 = SimpleNamespace(S3FileSystem=lambda **kwargs: object())
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(sys.modules, {'s3fs': fake_s3}), \
                 patch.object(g.N, 'S3Source', FakeSource):
                with self.assertRaisesRegex(RuntimeError, 'no valid global arrays'):
                    g.acquire('ecmwf', Path(td), 360)
            self.assertFalse((Path(td) / 'manifest.json').exists())
            self.assertEqual(list(Path(td).glob('*.webp')), [])

    def test_acquire_highres_without_coarse_cycle_or_raster(self):
        """Exercise the real staging entrypoint; no S3 traffic or fake fallback."""
        import hashlib
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        class FakeSource:
            def __init__(self, domain, fs):
                self.dom = domain
                self.nx, self.ny = 720, 361
                self.lo0, self.la0, self.dx, self.dy = -180, -90, 0.5, 0.5
            def runs(self):
                if self.dom == 'ecmwf_ifs025':
                    return []  # Coarse metadata unavailable: MUST NOT block high res.
                return [{'reference_time': '2026-11-21T00:00:00Z',
                         'valid_times': ['2026-11-22T00:00:00Z']}]
            def exists(self, run, valid):
                return self.dom == 'ecmwf_ifs'
            def read(self, run, valid, names):
                if self.dom != 'ecmwf_ifs':
                    raise AssertionError('Coarse archive must not be accessed')
                return {'temperature_2m': np.full((361, 720), 280, np.float32)}

        fake_s3 = SimpleNamespace(S3FileSystem=lambda **kwargs: object())
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with patch.dict(sys.modules, {'s3fs': fake_s3}), \
                 patch.object(g.N, 'S3Source', FakeSource):
                manifest = g.acquire('ecmwf', out, 24)
            self.assertEqual(manifest['schema'], 2)
            self.assertEqual(manifest['source_domain'], 'ecmwf_ifs')
            self.assertEqual(manifest['init_utc'], '2026-11-21T00:00:00Z')
            self.assertEqual(manifest['valid_utc'], '2026-11-22T00:00:00Z')
            self.assertEqual(set(manifest['fields']), {'t2m'})
            field = manifest['fields']['t2m']
            self.assertEqual(field['nominal_resolution'], '9 km')
            self.assertEqual(field['field_source_domain'], 'ecmwf_ifs')
            self.assertEqual(field['lead_hours'], 24)
            self.assertEqual(field['sha256'], hashlib.sha256(
                (out / field['file']).read_bytes()).hexdigest())
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['fields'],
                             manifest['fields'])

    def test_acquire_per_field_mixed_source_is_not_duplicated(self):
        """One t2m from high resolution, one Z500 from validated coarse source."""
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        class FakeSource:
            def __init__(self, domain, fs):
                self.dom = domain
                self.nx, self.ny = 720, 361
                self.lo0, self.la0, self.dx, self.dy = -180, -90, 0.5, 0.5
            def runs(self):
                return [{'reference_time': '2026-11-21T00:00:00Z',
                         'valid_times': ['2026-11-22T00:00:00Z']}]
            def exists(self, run, valid):
                return True
            def read(self, run, valid, names):
                field = ('temperature_2m' if self.dom == 'ecmwf_ifs'
                         else 'geopotential_height_500hPa')
                value = 281.0 if self.dom == 'ecmwf_ifs' else 5400.0
                return {field: np.full((361, 720), value, np.float32)}

        with tempfile.TemporaryDirectory() as td:
            fake_s3 = SimpleNamespace(S3FileSystem=lambda **kwargs: object())
            with patch.dict(sys.modules, {'s3fs': fake_s3}), \
                 patch.object(g.N, 'S3Source', FakeSource):
                manifest = g.acquire('ecmwf', Path(td), 24)
            self.assertEqual(set(manifest['fields']), {'t2m', 'z500'})
            self.assertEqual(manifest['source_domain'], 'mixed-per-field')
            self.assertEqual(manifest['fields']['t2m']['field_source_domain'],
                             'ecmwf_ifs')
            self.assertEqual(manifest['fields']['z500']['field_source_domain'],
                             'ecmwf_ifs025')
            self.assertEqual(manifest['fields']['z500']['nominal_resolution'],
                             '28 km')

    def test_cycle_metadata_unifies_real_utc_instants_not_local_clock_strings(self):
        """Coarse UTC and high-res +03:30 metadata describe ONE forecast run."""
        class Source:
            def __init__(self, items):
                self.items = items
            def runs(self):
                return self.items

        coarse = Source([{
            'reference_time': '2026-11-21T00:00:00Z',
            'valid_times': ['2026-11-22T00:00Z', '2026-11-22T00:00']
        }])
        high = Source([{
            'reference_time': '2026-11-21T03:30:00+03:30',
            'valid_times': ['2026-11-22T03:30:00+03:30',
                            '2026-11-22T03:30:00+03:30',
                            '2026-11-22T03:30:15+03:30']
        }])
        result = g.cycle_candidates(coarse, high)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['reference_time'], '2026-11-21T00:00')
        self.assertEqual(result[0]['valid_times'], ['2026-11-22T00:00'])
        run = g.resolve_cycle(result[0])
        self.assertEqual(g.valid_candidates(result[0], run),
                         [datetime(2026, 11, 22, tzinfo=timezone.utc)])

    def test_metadata_offset_crosses_utc_midnight(self):
        self.assertEqual(
            g.parse_meta_utc('2026-11-21T23:30:00-01:00'),
            datetime(2026, 11, 22, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(
            g.parse_meta_utc('2026-11-22T00:30'),
            datetime(2026, 11, 22, 0, 30, tzinfo=timezone.utc))

    def test_bad_metadata_time_is_rejected_not_truncated(self):
        for bad in ('not-a-time', '2026-11-21',
                    '2026-11-21T00:00malformed',
                    '2026-11-21T00:00:15Z', None):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, TypeError)):
                    g.parse_meta_utc(bad)
        class Source:
            def runs(self):
                return [{'reference_time': '2026-11-21T00:00Z',
                         'valid_times': ['2026-11-22T00:00garbage',
                                         '2026-11-22T00:00Z']}]
        cycles = g.cycle_candidates(Source())
        self.assertEqual(cycles[0]['valid_times'], ['2026-11-22T00:00'])

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
        self.assertEqual(g.valid_candidates(m,start,361), [])

    def test_select_lead_and_reject_bad_data(self):
        m={'valid_times':['2026-11-21T12:00','2026-11-22T12:00','2026-11-26T12:00']}
        dt=datetime(2026,11,21,12,tzinfo=timezone.utc)
        self.assertEqual(g.valid_candidates(m,dt,24)[0].day,22)
        with self.assertRaises(ValueError):g.to_units('z500',np.full((2,3),100.0))
        with self.assertRaises(ValueError):g.to_units('t2m',np.full((2,3),600.0))

if __name__=='__main__':unittest.main()
