"""Stage38: stop malformed daily MultiModel fields before host publication.

These tests use only local temporary arrays. They do not assert that a
valid-shaped grid has correct CRS, unit, model cycle, or geographical extent.
"""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace

import numpy as np

from mm_field_qc import MultiModelFieldError, prepare_field, validate_blend_payloads
from mm_maps import MMCombiner

RUN = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
VALID = RUN + timedelta(hours=180)


class TestStage38InputQC(unittest.TestCase):
    def test_real_zeros_are_valid_precipitation(self):
        arr = prepare_field(np.zeros((8, 8), dtype=np.float64))
        self.assertEqual(arr.dtype, np.dtype("float32"))
        self.assertTrue(np.all(arr == 0))

    def test_masked_values_remain_nan_and_unmasked_remain_finite(self):
        mask = np.zeros((4, 5), dtype=bool)
        mask[0, 0] = True
        original = np.ma.array(np.ones((4, 5)), mask=mask)
        arr = prepare_field(original)
        self.assertTrue(np.isnan(arr[0, 0]))
        self.assertEqual(arr[1, 1], 1.0)

    def test_reject_non_2d_and_non_numeric(self):
        for a in (np.zeros((20,)), np.zeros((2, 2, 2)), np.array([["x", "y"], ["x", "y"]])):
            with self.subTest(shape=a.shape), self.assertRaises(MultiModelFieldError):
                prepare_field(a)

    def test_reject_all_nan_and_infinite_grid(self):
        for a in (np.full((8, 8), np.nan),
                  np.full((8, 8), np.inf),
                  np.array([[0., 0.], [0., -np.inf]])):
            with self.subTest(reason=str(a.flat[0])), self.assertRaises(MultiModelFieldError):
                prepare_field(a)

    def test_reject_nearly_empty_grid(self):
        a = np.full((20, 20), np.nan)
        a.flat[0] = 1
        with self.assertRaises(MultiModelFieldError):
            prepare_field(a)
        self.assertEqual(np.isfinite(prepare_field(a, min_fraction=0.001)).sum(), 1)

    def test_sparse_alert_is_valid_but_all_missing_alert_is_not(self):
        sparse = np.full((50, 50), np.nan)
        sparse[15, 15] = 4.0
        with self.assertRaises(MultiModelFieldError):
            prepare_field(sparse)  # continuous variable: less than 1% valid
        checked = prepare_field(sparse, min_fraction=0.0)
        self.assertEqual(checked[15, 15], 4.0)
        self.assertEqual(validate_blend_payloads({
            "ecmwf": {"f": checked},
            "gfs": {"f": checked.copy()},
        }, min_fraction=0.0), (50, 50))
        with self.assertRaises(MultiModelFieldError):
            prepare_field(np.full((50, 50), np.nan), min_fraction=0.0)

    def test_sparse_real_alert_is_saved_by_producer(self):
        with TemporaryDirectory() as directory:
            c, logs = self.fake_combiner(directory)
            c.nm.PARAMS["alert"] = {"models": ["ecmwf", "gfs"], "kind": "sec"}
            c.pmm["alert"] = {"kind": "sec"}
            sparse = np.full((20, 20), np.nan)
            sparse[3, 7] = 2.0
            c.sink("ecmwf", "iran", "alert", RUN, VALID, sparse, {})
            key = ("iran", "alert", RUN, VALID)
            self.assertIn("ecmwf", c.idx[key])
            saved = c.load(c.idx[key]["ecmwf"])
            self.assertEqual(saved["f"][3, 7], 2.0)
            self.assertEqual(np.isfinite(saved["f"]).sum(), 1)

    def test_same_shape_two_families_pass(self):
        got = validate_blend_payloads({
            "ecmwf": {"f": np.full((5, 6), 4)},
            "gfs": {"f": np.zeros((5, 6))},
        })
        self.assertEqual(got, (5, 6))

    def test_reject_mismatch_not_broadcast(self):
        with self.assertRaisesRegex(MultiModelFieldError, "grid mismatch"):
            validate_blend_payloads({
                "ecmwf": {"f": np.zeros((5, 6))},
                "gfs": {"f": np.zeros((5, 2))},
            })

    def test_reject_wrong_contour_or_wind_grids(self):
        for key in ("c", "bu", "bv"):
            with self.subTest(field=key), self.assertRaisesRegex(MultiModelFieldError, key):
                validate_blend_payloads({
                    "ecmwf": {"f": np.zeros((5, 6)), key: np.zeros((4, 6))},
                    "gfs": {"f": np.zeros((5, 6))},
                })

    def fake_combiner(self, directory):
        c = MMCombiner.__new__(MMCombiner)
        c.dir = directory
        c.idx = {}
        c.first = {}
        c.prog = {}
        c.lock = Lock()
        c.pmm = {"p24": {"kind": "win"}}
        logs = []
        c.nm = SimpleNamespace(
            PARAMS={"p24": {"models": ["ecmwf", "gfs"], "kind": "win"}},
            MODELS={"ecmwf": {"hz": {"00": 360, "12": 360}},
                    "gfs": {"hz": 384}},
            log=logs.append,
        )
        return c, logs

    def test_sink_rejects_bad_array_without_creating_manifest_input(self):
        with TemporaryDirectory() as directory:
            c, logs = self.fake_combiner(directory)
            k = ("iran", "p24", RUN, VALID)
            c.sink("ecmwf", "iran", "p24", RUN, VALID, np.full((5, 6), np.nan), {})
            self.assertNotIn(k, c.idx)
            self.assertEqual(list(Path(directory).rglob("*.npz")), [])
            self.assertTrue(any("rejected" in line for line in logs))
            c.sink("ecmwf", "iran", "p24", RUN, VALID, np.zeros((5, 6)), {})
            self.assertIn("ecmwf", c.idx[k])
            self.assertTrue(Path(c.idx[k]["ecmwf"]).is_file())

    def test_higher_res_invalid_does_not_claim_same_family_slot(self):
        with TemporaryDirectory() as directory:
            c, logs = self.fake_combiner(directory)
            c.nm.PARAMS["p24"]["models"] = ["ecmwf9", "ecmwf", "gfs"]
            c.nm.MODELS["ecmwf9"] = {"hz": {"00": 360, "12": 360}}
            k = ("iran", "p24", RUN, VALID)
            c.sink("ecmwf9", "iran", "p24", RUN, VALID, np.full((5, 6), np.nan), {})
            c.progress("ecmwf9", RUN, VALID)
            c.sink("ecmwf", "iran", "p24", RUN, VALID, np.zeros((5, 6)), {})
            c.sink("gfs", "iran", "p24", RUN, VALID, np.zeros((5, 6)), {})
            self.assertEqual(c.decide(k), {"ecmwf": "ecmwf", "gfs": "gfs"})

    def test_make_rejects_mismatched_staged_grids_before_begin(self):
        with TemporaryDirectory() as directory:
            c, logs = self.fake_combiner(directory)
            k = ("iran", "p24", RUN, VALID)
            one = Path(directory) / "ecmwf.npz"
            two = Path(directory) / "gfs.npz"
            np.savez(one, f=np.ones((6, 6), dtype=np.float32))
            np.savez(two, f=np.ones((7, 6), dtype=np.float32))
            c.idx[k] = {"ecmwf": str(one), "gfs": str(two)}
            c.eng = SimpleNamespace(regions={"iran": object()})
            begin_called = []
            c.begin = lambda *_: begin_called.append(True)
            with self.assertRaisesRegex(MultiModelFieldError, "grid mismatch"):
                c.make(k, {"ecmwf": "ecmwf", "gfs": "gfs"})
            self.assertEqual(begin_called, [], "Must fail before host 'begin'")


if __name__ == "__main__":
    unittest.main()
