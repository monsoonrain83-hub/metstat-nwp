"""Synthetic, offline regression tests for regional ERA5 climatology builder."""
import unittest
from unittest.mock import patch
import numpy as np
import xarray as xr
import era5_clim as C


class TestERA5TemperatureClimatology(unittest.TestCase):
    def sample(self, temp=293.15, missing=False):
        lat = np.array([5.0, 6.0], dtype=np.float32)
        lon = np.array([40.0, 41.0], dtype=np.float32)
        shape = (366, 4, 2, 2)
        coords = dict(dayofyear=np.arange(1, 367), hour=[0, 6, 12, 18],
                      latitude=lat, longitude=lon)
        t = np.full(shape, temp, dtype=np.float32)
        if missing:
            t[0, 0, 0, 0] = np.nan
        z = np.full((3,) + shape, 5600 * 9.80665, dtype=np.float32)
        ds = xr.Dataset({
            "2m_temperature": (tuple(coords), t),
            "mean_sea_level_pressure": (tuple(coords), np.full(shape, 101300.0, np.float32)),
            "geopotential": (("level",) + tuple(coords), z),
        }, coords={**coords, "level": [500, 700, 850]})
        return ds, lat, lon

    def test_temperature_celsius_and_full_366_days(self):
        ds, lat, lon = self.sample()
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            output = C.build(ds)
        self.assertEqual(output["t2m"].shape, (366, 2, 2))
        self.assertTrue(np.allclose(output["t2m"], 20.0, atol=0.03))
        self.assertEqual(set(output), {"lat", "lon", "z500", "z700", "z850", "msl", "t2m"})

    def test_no_silent_interpolation_of_missing_climatology(self):
        ds, lat, lon = self.sample(missing=True)
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "missing/nonfinite"):
                C.build(ds)

    def test_reject_region_outside_source_grid(self):
        ds, lat, lon = self.sample()
        with patch.object(C, "LATS", np.array([5.0, 6.0, 7.0], np.float32)), \
             patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "does not cover"):
                C.build(ds)

    def test_missing_single_six_hour_slot_cannot_be_hidden_by_mean(self):
        ds, lat, lon = self.sample(missing=True)
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "source slots"):
                C.build(ds)

    def test_reject_missing_hour_even_if_all_remaining_values_are_finite(self):
        ds, lat, lon = self.sample()
        ds = ds.sel(hour=[0, 6, 12])
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "time coordinates"):
                C.build(ds)

    def test_reject_mislabeled_six_hour_slots(self):
        ds, lat, lon = self.sample()
        ds = ds.assign_coords(hour=[0, 6, 12, 21])
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "time coordinates"):
                C.build(ds)

    def test_reject_missing_calendar_day(self):
        ds, lat, lon = self.sample()
        ds = ds.sel(dayofyear=slice(1, 365))
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "time coordinates"):
                C.build(ds)

    def test_reject_infinite_source_slot_before_averaging(self):
        ds, lat, lon = self.sample()
        ds["2m_temperature"].values[0, 0, 0, 0] = np.inf
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "missing/nonfinite source slots"):
                C.build(ds)

    def test_reject_celsius_mislabeled_as_kelvin(self):
        ds, lat, lon = self.sample(temp=20.0)
        with patch.object(C, "LATS", lat), patch.object(C, "LONS", lon):
            with self.assertRaisesRegex(ValueError, "Kelvin"):
                C.build(ds)


if __name__ == "__main__":
    unittest.main()
