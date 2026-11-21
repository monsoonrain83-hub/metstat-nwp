"""Europe must be eligible for both ERA5-based temperature anomaly periods."""
import unittest
import nwp_maps as N

class TestEuropeTemperatureAnomalies(unittest.TestCase):
    def test_daily_and_five_day_available_on_europe(self):
        self.assertIn('tanom', N.EU_PIDS)
        self.assertIn('tanom5', N.EU_PIDS)
        for pid in ('tanom','tanom5'):
            self.assertEqual(N.PARAMS[pid]['kind'], 'day')
            self.assertEqual(N.PARAMS[pid]['sc'], pid)
            self.assertIn('ecmwf', N.PARAMS[pid]['models'])
            self.assertIn('gfs', N.PARAMS[pid]['models'])
        self.assertEqual(N.PARAMS['tanom5']['win_d'], 5)

    def test_no_unrequested_surface_products_enabled_for_europe(self):
        self.assertNotIn('pacc', N.EU_PIDS)
        self.assertNotIn('tmax', N.EU_PIDS)
        self.assertNotIn('tanom10', N.EU_PIDS)

if __name__ == '__main__': unittest.main()
