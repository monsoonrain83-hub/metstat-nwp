"""Offline regression for optional CFS weekly Z500 departure (not hindcast-calibrated)."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np
import wk_maps as wk
import ens_maps as ens


class Collector:
    def __init__(self):
        self.params = None
        self.files = []
    def call(self, action, js=None):
        if action == 'begin':
            self.params = js['params']
            return {'have': []}
        return {}
    def put(self, model, run, path, data, meta):
        self.files.append(path)
    def wait(self):
        pass


class TestCfsWeeklyHeight(unittest.TestCase):
    def fixtures(self):
        run = datetime(2026, 11, 20, tzinfo=timezone.utc)
        lo = np.array([20., 21.]); la = np.array([29., 30.])
        t = np.full((2, 2), 12., dtype=np.float32)
        p = np.ones((2, 2), dtype=np.float32)
        z = np.full((2, 2), 5760., dtype=np.float32)  # metres geopotential height
        products = {d: {'t2m': (t, lo, la), 'p24': (p, lo, la), 'z5': (z, lo, la)}
                    for d in range(1, 36)}
        return run, products

    def get(self, z_reference):
        run, products = self.fixtures()
        with patch.object(ens, 'S3', return_value=object()), \
             patch.object(ens, 'cfs_pick_run', return_value=run), \
             patch.object(ens, 'cfs_collect', return_value={}), \
             patch.object(ens, 'cfs_products', return_value=products), \
             patch.object(wk, 'ltm', return_value={'grid': 1}), \
             patch.object(wk, 'clim_on', return_value=0.), \
             patch.object(wk.N, 'z500_clim_at', side_effect=lambda R, d: z_reference):
            return wk.cfs_weekly(include_z500=True)

    def test_real_daily_z500_fields_produce_signed_decametres(self):
        result = self.get(np.full((2, 2), 5750., dtype=np.float32))
        self.assertEqual(len(result), 6)
        extra = result[5]
        self.assertEqual(extra['field'].shape, (5, 2, 2))
        np.testing.assert_allclose(extra['field'], 1.0)
        self.assertEqual(extra['lon'].shape, (2,))
        self.assertEqual(extra['lat'].shape, (2,))

    def test_missing_reference_keeps_temperature_and_precipitation(self):
        result = self.get(None)
        self.assertEqual(len(result), 5)

    def test_manifest_is_truthful_and_only_adds_z500_when_present(self):
        for ready, expected_count in [(False, 10), (True, 15)]:
            with self.subTest(ready=ready):
                result = self.get(np.full((2, 2), 5750., dtype=np.float32) if ready else None)
                up = Collector()
                with patch.object(wk.L, 'regrid', side_effect=lambda a, x, y: a), \
                     patch.object(wk.N, 'render_me', return_value=(b'mock', None)):
                    made = wk.make_weekly(up, 'cfswk', result, None)
                self.assertEqual(made, expected_count)
                self.assertEqual(len(up.files), expected_count)
                self.assertEqual('wz500a' in up.params, ready)
                if ready:
                    self.assertEqual(up.params['wz500a']['unit'], 'dam')
                    self.assertIn('bias not corrected', up.params['wz500a']['en'])
                    self.assertEqual(sum('/wz500a_' in p for p in up.files), 5)


if __name__ == '__main__':
    unittest.main()
