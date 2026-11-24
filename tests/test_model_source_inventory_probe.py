import unittest

from model_source_inventory_probe import SOURCES, inspect_manifest, run_probe


class TestRealSourceInventoryContract(unittest.TestCase):
    def test_reads_only_exact_latest_metadata_and_does_not_publish(self):
        paths = []
        def fake(path):
            paths.append(path)
            return {
                "reference_time": "2026-11-23T00:00:00Z",
                "valid_times": ["2026-11-23T06:00:00Z", "2026-11-23T12:00:00Z"],
                "variables": ["precipitation", "geopotential_height_500hPa",
                              "temperature_2m", "wind_u_component_200hPa"],
                "nx": 1440, "ny": 721,
            }
        report = run_probe(fake, ["aifs", "aigfs", "graphcast"])
        self.assertTrue(report["read_only"])
        self.assertEqual(len(report["results"]), 3)
        self.assertTrue(all(x["production_ready"] is False for x in report["results"]))
        self.assertEqual(paths[0], "openmeteo/data_spatial/ecmwf_aifs025/latest.json")
        self.assertIn("openmeteo/data_spatial/gfs_graphcast025/latest.json", paths)
        aifs = report["results"][0]["candidates"][0]
        self.assertEqual(aifs["grid_metadata_from_latest_json"]["nx"], 1440)
        self.assertEqual(aifs["pressure_levels_available"]["geopotential_height"], [500])
        self.assertEqual(aifs["pressure_levels_available"]["wind_u_component"], [200])

    def test_missing_grid_is_unknown_not_guessed(self):
        r = inspect_manifest({"variables": ["precipitation"], "reference_time": "today"})
        self.assertIsNone(r["grid_metadata_from_latest_json"])
        self.assertFalse(r["grid_verified_from_latest_json"])
        self.assertIsNone(r["forecast_valid_time_count"])

    def test_duplicate_valid_times_and_variables_fail_closed(self):
        with self.assertRaises(ValueError):
            inspect_manifest({"variables": ["x", "x"]})
        with self.assertRaises(ValueError):
            inspect_manifest({"variables": ["x"], "valid_times": [6, 6]})
        with self.assertRaises(ValueError):
            inspect_manifest({"variables": None})

    def test_kma_discontinued_even_with_a_readable_manifest(self):
        report = run_probe(lambda path: {"variables": ["precipitation"]}, ["kma"])
        x = report["results"][0]
        self.assertTrue(x["retired_upstream"])
        self.assertFalse(x["production_ready"])

    def test_probe_does_not_drop_other_models_when_one_is_missing(self):
        def fake(path):
            if "jma_gsm" in path:
                raise OSError("not found")
            return {"variables": ["temperature_2m"]}
        report = run_probe(fake, ["grapes", "jma"])
        self.assertTrue(report["results"][0]["source_readable"])
        self.assertFalse(report["results"][1]["source_readable"])
        self.assertFalse(report["results"][0]["production_ready"])

    def test_allowlist(self):
        with self.assertRaises(ValueError):
            run_probe(lambda _: {}, ["../admin"])
        self.assertTrue(SOURCES["weathernext"]["ensemble"])
        self.assertNotEqual(SOURCES["aifs"]["family"], SOURCES["aigfs"]["family"])


if __name__ == "__main__":
    unittest.main()
