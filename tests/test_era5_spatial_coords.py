"""Prevent ambiguous ERA5 grid sampling when source coordinates collide."""
import unittest
from unittest.mock import patch
import numpy as np
import xarray as xr
import era5_clim as C


class TestERA5SpatialCoordinates(unittest.TestCase):
    def test_normalized_longitude_collision_is_rejected(self):
        da = xr.DataArray(
            np.ones((2, 3), dtype=np.float32),
            dims=("latitude", "longitude"),
            coords={"latitude": [5.0, 6.0], "longitude": [0.0, 40.0, 360.0]},
        )
        with patch.object(C, "LATS", np.array([5.0, 6.0], np.float32)), \
             patch.object(C, "LONS", np.array([0.0], np.float32)):
            with self.assertRaisesRegex(ValueError, "duplicate/nonfinite longitude"):
                C.select_region(da)

    def test_duplicate_latitude_is_rejected(self):
        da = xr.DataArray(
            np.ones((3, 2), dtype=np.float32),
            dims=("latitude", "longitude"),
            coords={"latitude": [5.0, 5.0, 6.0], "longitude": [40.0, 41.0]},
        )
        with patch.object(C, "LATS", np.array([5.0, 6.0], np.float32)), \
             patch.object(C, "LONS", np.array([40.0, 41.0], np.float32)):
            with self.assertRaisesRegex(ValueError, "duplicate/nonfinite latitude"):
                C.select_region(da)

    def test_unique_grid_is_accepted(self):
        da = xr.DataArray(
            np.ones((2, 2), dtype=np.float32),
            dims=("latitude", "longitude"),
            coords={"latitude": [6.0, 5.0], "longitude": [41.0, 40.0]},
        )
        with patch.object(C, "LATS", np.array([5.0, 6.0], np.float32)), \
             patch.object(C, "LONS", np.array([40.0, 41.0], np.float32)):
            out = C.select_region(da)
        self.assertEqual(out.shape, (2, 2))


if __name__ == "__main__":
    unittest.main()
