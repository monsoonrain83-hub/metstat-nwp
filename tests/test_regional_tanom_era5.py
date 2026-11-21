"""Regression tests: regional T2m anomalies must use ERA5, never Iran stations."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import nwp_maps as N


class TestRegionalTemperatureReference(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)

    def test_me_and_eu_use_era5_even_without_station_climatology(self):
        for key in ('me', 'eu'):
            with (self.subTest(region=key),
                  patch.object(N, 'CLIM', None),
                  patch.object(N, '_era5_at', return_value=np.full((2, 2), 18.0)) as era):
                result = N.clim_at(SimpleNamespace(key=key), self.when)
                np.testing.assert_allclose(result, 18.0)
                era.assert_called_once_with('t2m', unittest.mock.ANY, self.when)

    def test_missing_regional_era5_never_falls_back_to_iran(self):
        with (patch.object(N, 'CLIM', {'me_coef': np.ones((12, 4)), 'me_res': np.ones((12, 2, 2))}),
              patch.object(N, '_era5_at', return_value=None)):
            self.assertIsNone(N.clim_at(SimpleNamespace(key='me'), self.when))

    def test_iran_without_station_reference_does_not_use_era5(self):
        with patch.object(N, 'CLIM', None), patch.object(N, '_era5_at') as era:
            self.assertIsNone(N.clim_at(SimpleNamespace(key='iran'), self.when))
            era.assert_not_called()


if __name__ == '__main__':
    unittest.main()
