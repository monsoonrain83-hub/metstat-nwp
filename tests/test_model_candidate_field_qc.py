import unittest

import numpy as np

from model_candidate_field_qc import evaluate_sample, probe_model, run


RUN = "2026-11-23T12:00:00Z"
VALID = "2026-11-23T18:00Z"


def fetched(path):
    return {
        "reference_time": RUN, "valid_times": [VALID],
        "variables": ["temperature_2m", "geopotential_height_500hPa", "precipitation"],
    }


def sampled(uri, variables):
    values = {"temperature_2m": 291.1,
              "geopotential_height_500hPa": 5600,
              "precipitation": 1.8}
    return {v: {"shape": [721, 1440],
                "sample": np.full((16,16), values[v], np.float32)}
            for v in variables}


class TestCandidateFieldQC(unittest.TestCase):
    def test_same_run_sample_and_provenance_never_production(self):
        for name in ("aigfs","grapes","jma"):
            row = probe_model(name, fetched, sampled)
            self.assertTrue(row["sample_qc_passed"], row)
            self.assertEqual(row["run_utc"], RUN)
            self.assertEqual(row["valid_utc"], VALID)
            self.assertEqual(row["grid_shape"], [721,1440])
            self.assertFalse(row["production_ready"])
            self.assertFalse(row["projection_verified"])
            self.assertFalse(row["precipitation_accumulation_verified"])
            self.assertEqual([v["tentative_units"] for v in row["fields"]],
                             ["K","m","raw accumulation (interval/unit unverified)"])

    def test_temperature_celsius_and_geopotential_dam(self):
        self.assertEqual(evaluate_sample("temperature_2m",
                                        np.full((16,16), 21.7))["tentative_units"],"°C")
        self.assertEqual(evaluate_sample("geopotential_height_500hPa",
                                        np.full((16,16),550))["tentative_units"],"dam")

    def test_nan_and_negative_precipitation_fail(self):
        x = np.full((16,16),3.0)
        x[:12,:] = np.nan
        self.assertFalse(evaluate_sample("precipitation",x)["passed"])
        self.assertFalse(evaluate_sample("precipitation",
                         np.full((16,16),-30.0))["passed"])

    def test_shape_and_field_missing_fail(self):
        def mismatch(uri, variables):
            val=sampled(uri,variables)
            val["precipitation"]["shape"]=[361,720]
            return val
        r=probe_model("jma",fetched,mismatch)
        self.assertFalse(r["sample_qc_passed"])
        self.assertEqual(r["fields"][-1]["reason"],"per-field-shape-mismatch")
        r=probe_model("jma",fetched,lambda uri,vars: {"temperature_2m":sampled(uri,vars)["temperature_2m"]})
        self.assertFalse(r["sample_qc_passed"])

    def test_unapproved_source_and_missing_run(self):
        with self.assertRaises(ValueError):
            probe_model("kma",fetched,sampled)
        r=probe_model("aigfs",lambda path:{"variables":["temperature_2m"]},sampled)
        self.assertFalse(r["sample_qc_passed"])
        self.assertFalse(r["production_ready"])

    def test_batch_run_read_only(self):
        results=run(["aigfs","grapes","jma"],fetched,sampled)
        self.assertEqual(len(results["samples"]),3)
        self.assertTrue(results["read_only"])
        self.assertFalse(any(x["production_ready"] for x in results["samples"]))


if __name__=="__main__":
    unittest.main()
