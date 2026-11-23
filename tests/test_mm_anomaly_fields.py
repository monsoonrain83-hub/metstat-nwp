# -*- coding: utf-8 -*-
"""Regression: publish REAL Z500/MSLP/temperature anomalies in MetStat MultiModel."""
import unittest
from datetime import date
from types import SimpleNamespace
import numpy as np
import mm_weights as W
from mm_maps import MMCombiner, mm_extend_params


class TestDailyAnomalyMultimodel(unittest.TestCase):
    @staticmethod
    def fake_combiner():
        def field(code, models, me_only=False, category="ul"):
            return dict(kind="inst", sc=code, models=models, unit="dam" if code == "z500a" else "hPa",
                        fa="آنومالی", en="Anomaly", ord=12, cat=category, me_only=me_only)
        data = {
            "z500a": field("z500a", ["ecmwf", "gfs", "gem"], True),
            "mslpa": field("mslpa", ["ecmwf", "gfs", "gfs25"], True, "sf"),
            "tanom": field("tanom", ["ecmwf", "gfs", "gem"], False, "tp"),
            "z850a": field("z850a", ["ecmwf"], True),  # unavailable: do not invent output
            "raw": dict(field("temp", ["ecmwf", "gfs"]), raw=True),
            "missing": field("temp", ["ecmwf"], False),
        }
        s = MMCombiner.__new__(MMCombiner)
        s.nm = SimpleNamespace(PARAMS=data)
        return s

    def test_models_are_extended_only_when_combiner_enabled(self):
        dummy = {}
        def field(models):
            return {'models': list(models)}
        for p in ('tanom', 'tanom5', 'tanom10', 'z500a', 'mslpa'):
            dummy[p] = field(['ecmwf', 'gfs'])
        mm_extend_params(dummy)
        for p in ('tanom', 'tanom5', 'tanom10', 'mslpa'):
            self.assertTrue({'ecmwf', 'gfs', 'icon', 'ukmo', 'gem', 'gfs25'}.issubset(dummy[p]['models']))
        self.assertTrue({'icon', 'ukmo', 'gfs25'}.issubset(dummy['z500a']['models']))

    def test_pressure_anomaly_weight_group(self):
        self.assertEqual(W.group_of("z500a"), "pressure")
        self.assertEqual(W.group_of("mslpa"), "pressure")
        for p in ("z500a", "mslpa"):
            weights, _, _ = W.weights("pressure", date(2026, 11, 20),
                                      ["ecmwf", "gfs", "gem"], pid=p)
            self.assertEqual(set(weights), {"ecmwf", "gfs", "gem"})
            self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_built_catalogue_only_advertises_present_fields(self):
        s = self.fake_combiner()
        products = s.build_params()
        for p in ("z500a", "mslpa", "tanom"):
            self.assertIn(p, products)
            self.assertIn("en", products[p])
        for p in ("z850a", "raw", "missing"):
            self.assertNotIn(p, products)

    def test_weighted_anomaly_preserves_signed_units_and_missing_pixels(self):
        s = self.fake_combiner()
        fields = {
            "ecmwf": np.array([[-2., np.nan], [3., np.nan]], dtype=np.float32),
            "gfs": np.array([[2., 4.], [-1., np.nan]], dtype=np.float32),
        }
        weights = {"ecmwf": 0.6, "gfs": 0.4}
        out = s.combine("w", weights, fields, "z500a")
        self.assertAlmostEqual(float(out[0, 0]), -0.4)
        self.assertAlmostEqual(float(out[0, 1]), 4.)
        self.assertAlmostEqual(float(out[1, 0]), 1.4)
        self.assertTrue(np.isnan(out[1, 1]))
        self.assertEqual(out.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
