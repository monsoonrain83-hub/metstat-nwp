# -*- coding: utf-8 -*-
"""Offline contract tests for proposed SEAS5 anomaly fields (no CDS/host calls)."""
import unittest
import numpy as np
import seas5_maps as S


class TestSeas5Anomaly(unittest.TestCase):
    def test_units_mslp(self):
        a = np.array([-500., 0., 450.])
        np.testing.assert_allclose(S.convert('mslpa', a, 'Pa'), [-5., 0., 4.5])
        np.testing.assert_allclose(S.convert('mslpa', a / 100., 'hPa'), [-5., 0., 4.5])
        with self.assertRaises(RuntimeError):
            S.convert('mslpa', a, 'K')

    def test_units_geopotential(self):
        a = np.array([-98.0665, 0., 196.133])
        np.testing.assert_allclose(S.convert('z500a', a, 'm**2 s**-2'), [-1., 0., 2.], rtol=1e-6)
        np.testing.assert_allclose(S.convert('z500a', np.array([50.]), 'm'), [5.])
        with self.assertRaises(RuntimeError):
            S.convert('z500a', a, 'Pa')

    def test_cds_datasets_are_distinct(self):
        calls = []
        class Fake:
            def retrieve(self, dataset, args, path): calls.append((dataset, args, path))
        S.retrieve(Fake(), 'geopotential_anomaly', 2026, 11, '/tmp/z500.nc', pressure_level=500)
        self.assertEqual(calls[0][0], 'seasonal-postprocessed-pressure-levels')
        self.assertEqual(calls[0][1]['pressure_level'], ['500'])
        self.assertEqual(calls[0][1]['system'], '51')
        S.retrieve(Fake(), 'mean_sea_level_pressure_anomaly', 2026, 11, '/tmp/slp.nc')
        self.assertEqual(calls[1][0], 'seasonal-postprocessed-single-levels')
        self.assertNotIn('pressure_level', calls[1][1])

    def test_manifest_only_advertises_available_products(self):
        p = S.begin_payload('ecmwfseas', '2026110100', {'t2a', 'mslpa'})
        self.assertIn('lrta', p['params'])
        self.assertIn('lrslpa', p['params'])
        self.assertNotIn('lrz500a', p['params'])
        self.assertNotIn('lrpa', p['params'])
        self.assertEqual(p['params']['lrslpa']['unit'], 'hPa')
        self.assertEqual(p['params']['lrslpa']['en'], 'Mean sea level pressure anomaly (hPa)')
        q = S.begin_payload('ecmwfseass', '2026110100', {'z500a'})
        self.assertEqual(q['info']['span'], 3) if 'span' in q['info'] else self.assertEqual(S.SEAS_MODELS['ecmwfseass']['span'], 3)
        self.assertIn('lrz500a', q['params'])


if __name__ == '__main__':
    unittest.main()
