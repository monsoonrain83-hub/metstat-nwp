"""Regression checks for ERA5 calendar and geographic coverage in NWP renderer."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import nwp_maps as N


class TestERA5Sampling(unittest.TestCase):
    def setUp(self):
        self.normal = {
            'lat': np.array([10., 11.], dtype=np.float32),
            'lon': np.array([40., 41.], dtype=np.float32),
            't2m': np.broadcast_to(
                np.arange(366, dtype=np.float32)[:, None, None],
                (366, 2, 2)).copy()
        }
        self.region = SimpleNamespace(
            lat=np.array([[10.5]], dtype=np.float32),
            lon=np.array([[40.5]], dtype=np.float32))

    def sample(self, date):
        with patch.object(N, 'load_era5c', return_value=self.normal):
            return N._era5_at('t2m', self.region, date)

    def test_non_leap_march_first_skips_feb29_climatology_slot(self):
        value = self.sample(datetime(2025, 3, 1, tzinfo=timezone.utc))
        self.assertAlmostEqual(float(value[0, 0]), 60.)

    def test_leap_march_first_uses_366_day_calendar(self):
        value = self.sample(datetime(2024, 3, 1, tzinfo=timezone.utc))
        self.assertAlmostEqual(float(value[0, 0]), 60.)

    def test_non_leap_december_31_is_not_wrapped_to_january(self):
        value = self.sample(datetime(2025, 12, 31, tzinfo=timezone.utc))
        self.assertAlmostEqual(float(value[0, 0]), 365.)

    def test_outside_domain_is_not_clamped_to_edge(self):
        self.region.lon[:] = 42.
        self.assertIsNone(self.sample(datetime(2025, 3, 1, tzinfo=timezone.utc)))

    def test_duplicate_longitude_rejected(self):
        self.normal['lon'] = np.array([40., 40.], dtype=np.float32)
        self.region.lon[:] = 40.
        self.assertIsNone(self.sample(datetime(2025, 3, 1, tzinfo=timezone.utc)))

    def test_irregular_latitude_spacing_rejected(self):
        self.normal['lat'] = np.array([10., 11., 13.], dtype=np.float32)
        self.normal['t2m'] = np.zeros((366, 3, 2), dtype=np.float32)
        self.assertIsNone(self.sample(datetime(2025, 3, 1, tzinfo=timezone.utc)))

    def test_nonfinite_grid_coordinate_rejected(self):
        self.normal['lon'] = np.array([40., np.nan], dtype=np.float32)
        self.assertIsNone(self.sample(datetime(2025, 3, 1, tzinfo=timezone.utc)))

    def test_missing_field_is_not_fabricated(self):
        with patch.object(N, 'load_era5c', return_value=self.normal):
            self.assertIsNone(N._era5_at('not_present', self.region,
                                        datetime(2025, 3, 1, tzinfo=timezone.utc)))


if __name__ == '__main__':
    unittest.main()
