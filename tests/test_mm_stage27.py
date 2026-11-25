"""Regression: mandatory 60/40 daily blend and inclusive +180 h horizon."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace

import numpy as np

import mm_weights as W
from mm_maps import MMCombiner

RUN = datetime(2026, 11, 23, 0, tzinfo=timezone.utc)


class Stage27DailyMultiModel(unittest.TestCase):
    def test_ecmwf_is_exactly_sixty_percent_in_both_seasons(self):
        cases = (datetime(2026, 1, 15, tzinfo=timezone.utc),
                 datetime(2026, 7, 15, tzinfo=timezone.utc))
        for valid in cases:
            for group, pid in (("precip", "p24"),
                               ("temp", "tmax"),
                               ("wind", "gust"),
                               ("convection", "cape"),
                               ("convection", "gdi")):
                with self.subTest(valid=valid, pid=pid):
                    w, season, missing = W.weights(
                        group, valid,
                        ["ecmwf9", "ecmwf", "gfs", "gfs25", "icon", "gem", "ukmo"],
                        pid=pid)
                    self.assertAlmostEqual(w["ecmwf"], .60, places=12)
                    self.assertAlmostEqual(sum(v for k, v in w.items()
                                               if k != "ecmwf"), .40, places=12)
                    self.assertAlmostEqual(sum(w.values()), 1, places=12)
                    self.assertEqual(len(w), 2 if pid == 'gdi' else 5)

    def test_missing_optional_models_do_not_shift_ecmwf_share(self):
        w, *_ = W.weights("precip", RUN, ["ecmwf9", "gfs25"], pid="p24")
        self.assertEqual(w, {"ecmwf": .60, "gfs": .40})
        self.assertEqual(W.pick_sources(["ecmwf9", "ecmwf", "gfs", "gfs25"]),
                         {"ecmwf": "ecmwf9", "gfs": "gfs"})
        # The final map must never pretend a single ECMWF is a multi-model.
        w, *_ = W.weights("precip", RUN, ["ecmwf"], pid="p24")
        self.assertEqual(w, {})
        w, *_ = W.weights("precip", RUN, ["gfs", "icon"], pid="p24")
        self.assertEqual(w, {})

    def test_180_hour_field_stages_and_picks_but_181_rejected(self):
        with TemporaryDirectory() as tmp:
            m = MMCombiner.__new__(MMCombiner)
            m.dir = tmp
            m.nm = SimpleNamespace(
                PARAMS={"p24": {"models": ["ecmwf", "gfs"]}},
                MODELS={"ecmwf": {"hz": {"00": 360, "12": 360}},
                        "gfs": {"hz": 384}})
            m.pmm = {"p24": {"kind": "win"}}
            m.idx = {}
            m.first = {}
            m.prog = {}
            m.lock = Lock()
            a = np.full((3, 4), 2.0, dtype=np.float32)
            valid = RUN + timedelta(hours=180)
            m.sink("ecmwf", "iran", "p24", RUN, valid, a, {})
            m.sink("gfs", "iran", "p24", RUN, valid, a, {})
            key = ("iran", "p24", RUN, valid)
            self.assertEqual(set(m.idx[key]), {"ecmwf", "gfs"})
            self.assertEqual(m.decide(key), {"ecmwf": "ecmwf", "gfs": "gfs"})
            for staged in m.idx[key].values():
                self.assertTrue(Path(staged).is_file())
            invalid = RUN + timedelta(hours=181)
            m.sink("gfs", "iran", "p24", RUN, invalid, a, {})
            self.assertNotIn(("iran", "p24", RUN, invalid), m.idx)


if __name__ == "__main__":
    unittest.main()
