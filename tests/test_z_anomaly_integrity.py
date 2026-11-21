"""Geopotential anomaly grids must not publish when source or normal is corrupt."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import nwp_maps as N

class TestGeopotentialAnomalyGuard(unittest.TestCase):
    def setUp(self):
        self.engine = N.Engine.__new__(N.Engine)
        self.vt = datetime(2026, 11, 21, tzinfo=timezone.utc)
        self.grid = np.full((3, 4), 5600.0, np.float32)
        self.region = SimpleNamespace(key='me', interp=lambda source, arr: arr)
        self.state = SimpleNamespace(model='gfs', srcs={'main': object()})

    def make(self, field, clim, pid='z500a'):
        level = int(pid[1:4]); key = f'geopotential_height_{level}hPa'
        with patch.object(N, 'z_clim_at', return_value=clim):
            return self.engine.make({'kind':'inst'}, pid, self.state,
                                    {'main': {key: field}}, self.region, self.vt, 24, 6)

    def test_valid_500_anomaly_and_contours(self):
        result = self.make(self.grid, self.grid - 100)
        self.assertIsNotNone(result)
        anomaly, metadata = result
        np.testing.assert_allclose(anomaly, 10)
        np.testing.assert_allclose(metadata['cont'], 560)

    def test_reject_missing_corrupt_or_wrong_shape(self):
        for normal in (np.full((3, 4), np.nan), np.ones((2, 4)), np.ones((3, 4))*np.inf):
            with self.subTest(normal_shape=normal.shape):
                self.assertIsNone(self.make(self.grid, normal))
        broken = self.grid.copy(); broken[0, 0] = np.nan
        self.assertIsNone(self.make(broken, self.grid))

    def test_all_supported_pressure_levels(self):
        for pid in ('z500a','z700a','z850a'):
            with self.subTest(pid=pid):
                self.assertIsNotNone(self.make(self.grid, self.grid - 100, pid))

if __name__ == '__main__': unittest.main()
