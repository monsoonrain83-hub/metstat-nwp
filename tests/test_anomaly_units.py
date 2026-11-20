"""Unit regression: geopotential-height anomaly maps store decametres, not decimetres."""
import unittest
import nwp_maps as N
import ens_maps as E


class GeopotentialUnitTests(unittest.TestCase):
    def test_daily_height_anomalies_decametres(self):
        for level in (500, 700, 850):
            k=f'z{level}a'
            with self.subTest(parameter=k):
                self.assertEqual(N.PARAMS[k]['unit'], 'dam')
                self.assertIn('(dam)', N.PARAMS[k]['en'])

    def test_ensemble_z500_anomaly_decametres(self):
        self.assertEqual(E.PARAMS['z500a'][1], 'dam')


if __name__ == '__main__':
    unittest.main()
