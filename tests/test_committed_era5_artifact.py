"""Validate the committed ERA5 climatology used for live regional anomalies.
This tests the actual NPZ artifact, not synthetic mock arrays.
"""
from pathlib import Path
import unittest
import numpy as np

FILE = Path(__file__).resolve().parents[1] / 'data/static/era5_clim_1deg.npz'

class TestCommittedERA5Artifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FILE.is_file():
            raise AssertionError(f'ERA5 artifact missing from checkout: {FILE}')
        cls.npz = np.load(FILE, allow_pickle=False)

    @classmethod
    def tearDownClass(cls):
        cls.npz.close()

    def test_complete_daily_reference_fields(self):
        required = {'lat','lon','z500','z700','z850','msl','t2m'}
        self.assertFalse(required - set(self.npz.files), f'Missing fields: {required - set(self.npz.files)}')
        lat = np.asarray(self.npz['lat'], dtype=np.float64)
        lon = np.asarray(self.npz['lon'], dtype=np.float64)
        self.assertEqual(lat.ndim, 1)
        self.assertEqual(lon.ndim, 1)
        self.assertGreater(len(lat), 2)
        self.assertGreater(len(lon), 2)
        self.assertTrue(np.all(np.isfinite(lat)) and np.all(np.diff(lat)>0))
        self.assertTrue(np.all(np.isfinite(lon)) and np.all(np.diff(lon)>0))
        self.assertLessEqual(lat[0], 5.0)
        self.assertGreaterEqual(lat[-1], 65.0)
        self.assertLessEqual(lon[0], -15.0)
        self.assertGreaterEqual(lon[-1], 95.0)
        for key in ('z500','z700','z850','msl','t2m'):
            with self.subTest(key=key):
                field=np.asarray(self.npz[key], dtype=np.float32)
                self.assertEqual(field.shape,(366,len(lat),len(lon)))
                self.assertTrue(np.isfinite(field).all(),f'{key}: nonfinite reference values')
                low,high={'z500':(3500,7000),'z700':(1500,4000),'z850':(500,2500),'msl':(800,1150),'t2m':(-100,60)}[key]
                self.assertGreater(float(field.min()),low,f'{key}: units or range invalid')
                self.assertLess(float(field.max()),high,f'{key}: units or range invalid')

if __name__=='__main__': unittest.main()
