"""End-to-end day-anomaly calculation must use the local ERA5 grid, not Iran."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import nwp_maps as N

class TestRegionalAnomalyRendering(unittest.TestCase):
    def setUp(self):
        self.vt = datetime(2026, 11, 21, 0, tzinfo=timezone.utc)
        self.grid = np.full((2, 3), 20.0, np.float32)
        self.state = SimpleNamespace(model='gfs', srcs={'main': object()},
                                     tser={'main': {self.vt-timedelta(hours=h):
                                         (self.grid, self.grid, self.grid, 6.0)
                                         for h in (0, 6, 12, 18)}})
        self.engine = N.Engine.__new__(N.Engine)
        self.engine.lapse = lambda st, region, f, full=False: f()

    def test_middle_east_uses_its_own_grid(self):
        region = SimpleNamespace(key='me', interp=lambda source, value, order=1: value)
        with patch.object(N, 'clim_at', return_value=np.full((2, 3), 17.0)) as clim:
            value, metadata = self.engine.make({'kind':'day', 'win_d':1}, 'tanom',
                                                self.state, {}, region, self.vt, 24, 6)
        np.testing.assert_allclose(value, 3.0)
        self.assertIn('ERA5', metadata['note'])
        self.assertIn('1990–2019', metadata['note'])
        self.assertEqual(clim.call_args.args[0], region)

    def test_missing_era5_does_not_publish(self):
        region = SimpleNamespace(key='me', interp=lambda source, value, order=1: value)
        with patch.object(N, 'clim_at', return_value=None):
            self.assertIsNone(self.engine.make({'kind':'day', 'win_d':1}, 'tanom',
                                               self.state, {}, region, self.vt, 24, 6))

    def test_invalid_or_wrong_shape_reference_does_not_publish(self):
        region = SimpleNamespace(key='eu', interp=lambda source, value, order=1: value)
        for reference in (np.full((2, 3), np.nan), np.ones((2, 2))):
            with self.subTest(reference_shape=reference.shape), patch.object(N, 'clim_at', return_value=reference):
                self.assertIsNone(self.engine.make({'kind':'day', 'win_d':1}, 'tanom',
                                                   self.state, {}, region, self.vt, 24, 6))

if __name__ == '__main__': unittest.main()
