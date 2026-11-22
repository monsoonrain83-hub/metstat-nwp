import unittest
from resolution_selector import FieldRequest, select_source


class ResolutionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.req = FieldRequest("ecmwf", "2026-11-22T00:00Z", "p24", "2026-11-23T00:00Z", "iran")

    def test_prefers_higher_resolution(self):
        result = select_source(self.req, lambda source, req: True)
        self.assertEqual(result.source, "ecmwf_ifs")
        self.assertEqual(result.nominal_resolution, "9 km")

    def test_falls_back_same_request(self):
        result = select_source(self.req, lambda source, req: source == "ecmwf_ifs025")
        self.assertEqual(result.source, "ecmwf_ifs025")
        self.assertEqual(result.cycle, self.req.cycle)

    def test_unavailable_not_fabricated(self):
        self.assertIsNone(select_source(self.req, lambda source, req: False))

    def test_gfs_and_alias(self):
        req = FieldRequest("gfs25", self.req.cycle, "z200", self.req.valid_time, "world")
        result = select_source(req, lambda source, req: source == "ncep_gfs025")
        self.assertEqual((result.model, result.source), ("gfs", "ncep_gfs025"))

    def test_read_failure_allows_fallback(self):
        def check(source, req):
            if source == "ecmwf_ifs":
                raise OSError("partial file")
            return True
        self.assertEqual(select_source(self.req, check).source, "ecmwf_ifs025")

    def test_rejects_unknown_model(self):
        with self.assertRaises(ValueError):
            select_source(FieldRequest("ukmo", self.req.cycle, "z500", self.req.valid_time, "iran"), lambda s, r: True)

    def test_requires_valid_time(self):
        with self.assertRaises(ValueError):
            select_source(FieldRequest("gfs", self.req.cycle, "p24", "", "iran"), lambda s, r: True)

    def test_no_truthy_non_boolean_qc(self):
        self.assertIsNone(select_source(self.req, lambda s, r: "available"))


if __name__ == "__main__":
    unittest.main()
