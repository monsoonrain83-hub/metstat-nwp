import unittest

from model_grid_shape_probe import inspect_one, om_uri, run_model_shapes


class TestOMGridProbe(unittest.TestCase):
    def test_known_om_file_path(self):
        uri = om_uri("cma_grapes_global", "2026-11-23T12:00:00Z",
                     "2026-11-23T18:00Z")
        self.assertEqual(uri, "s3://openmeteo/data_spatial/cma_grapes_global/"
                         "2026/11/23/1200Z/2026-11-23T1800.om")

    def test_no_unverified_or_unknown_source(self):
        with self.assertRaises(ValueError):
            om_uri("../etc/passwd", "2026-11-23T12:00Z", "2026-11-23T18:00Z")
        with self.assertRaises(ValueError):
            om_uri("jma_gsm", "2026-11-23T12:00Z", "2026-11-23T06:00Z")

    def test_metadata_header_shape_not_grid_coverage(self):
        data = {"reference_time": "2026-11-23T12:00:00Z",
                "valid_times": ["2026-11-23T18:00Z"],
                "variables": ["temperature_2m", "geopotential_height_500hPa"]}
        seen = []
        def header(uri, fields):
            seen.append(uri)
            return {"variable": fields[0], "shape": (1201, 2400)}
        result = inspect_one("cma_grapes_global", data, header)
        self.assertEqual((result["rows_ny"], result["columns_nx"]), (1201, 2400))
        self.assertFalse(result["coordinate_extent_verified"])
        self.assertFalse(result["ready_for_publishing"])
        self.assertEqual(len(seen), 1)

    def test_invalid_header_fails_closed(self):
        data = {"reference_time": "2026-11-23T12:00:00Z",
                "valid_times": ["2026-11-23T18:00Z"],
                "variables": ["temperature_2m"]}
        bad = inspect_one("jma_gsm", data, lambda *args: {
            "variable": "temperature_2m", "shape": (1440,)})
        self.assertFalse(bad["shape_verified"])

    def test_retired_and_ensemble_never_probed_as_deterministic(self):
        seen = []
        def fetch(path): seen.append(path); return {}
        out = run_model_shapes(["kma", "weathernext"], fetch, lambda *args: {})
        self.assertEqual(seen, [])
        self.assertFalse(any(v["shape_verified"] for v in out["grid_shapes"]))


if __name__ == "__main__":
    unittest.main()
