"""Do not misrepresent geopotential snapshots as 24-hour means."""
import unittest
import nwp_maps as N

class TestGeopotentialTimeSemantics(unittest.TestCase):
    def test_pressure_anomaly_snapshot_labels(self):
        for level in (500, 700, 850):
            with self.subTest(level=level):
                p = N.PARAMS[f'z{level}a']
                self.assertEqual(p['kind'], 'inst')
                self.assertIn('snapshot', p['en'])
                self.assertIn('لحظه‌ای', p['fa'])
                self.assertNotIn('daily mean', p['en'].lower())
                self.assertNotIn('six-hourly', p['en'].lower())
                self.assertEqual(p['unit'], 'dm')

    def test_temperature_anomalies_are_means_not_snapshots(self):
        self.assertEqual(N.PARAMS['tanom']['kind'], 'day')
        self.assertEqual(N.PARAMS['tanom5']['win_d'], 5)

if __name__ == '__main__': unittest.main()
