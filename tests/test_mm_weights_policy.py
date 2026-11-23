# -*- coding: utf-8 -*-
"""Regression assertions for five-model seasonal and parameter weights."""
import unittest
from datetime import date
import mm_weights as m

MODELS = ['ecmwf9', 'gfs', 'gem', 'icon', 'ukmo']

class TestMultimodelWeights(unittest.TestCase):
    def test_cold_baseline(self):
        for g in m.GROUPS:
            b, season = m.base_weights(g, date(2026, 11, 12))
            self.assertEqual(season, 'cold')
            self.assertEqual(b, {'ecmwf': 45, 'gfs': 30, 'gem': 10, 'icon': 10, 'ukmo': 5})

    def test_warm_baseline(self):
        for g in m.GROUPS:
            b, season = m.base_weights(g, date(2026, 7, 1))
            self.assertEqual(season, 'warm')
            self.assertEqual(b, {'gem': 45, 'gfs': 25, 'ecmwf': 15, 'icon': 10, 'ukmo': 5})

    def test_season_boundaries_1405(self):
        for day, expected in [
            (date(2026, 5, 19), 'cold'), (date(2026, 5, 20), 'warm'),
            (date(2026, 10, 26), 'warm'), (date(2026, 10, 27), 'cold')
        ]:
            self.assertEqual(m.season(day), expected)

    def test_ecmwf_fallback(self):
        self.assertEqual(m.pick_sources(MODELS)['ecmwf'], 'ecmwf9')
        self.assertEqual(m.pick_sources(['ecmwf', 'gfs', 'gem'])['ecmwf'], 'ecmwf')

    def test_daily_ecmwf_60_and_legacy_relative_non_ecmwf_ratios(self):
        # The baseline/parameter tables above remain as historical reference;
        # the master requirements supersede their ECMWF absolute share only.
        cases = [
            ("convection", "cape", False),
            ("convection", "ki", False),
            ("humidity", "pw", False),
            ("wind", "gust", False),
            ("temp", "t2m", False),
            ("temp", "tmin", False),
            ("temp", "tmax", False),
            ("precip", "wrain", True),
            ("convection", "hail", True),
        ]
        for d in (date(2026, 7, 1), date(2026, 11, 12)):
            for group, pid, secondary in cases:
                with self.subTest(date=d, param=pid):
                    historical, _ = m.base_weights(group, d)
                    historical = m._specific_weights(group, pid, secondary) or historical
                    others = [k for k in m.MM_MODELS if k != "ecmwf" and
                              historical.get(k, 0) > 0]
                    total_other = sum(historical[k] for k in others)
                    w, _, _ = m.weights(group, d, MODELS, pid=pid, secondary=secondary)
                    self.assertAlmostEqual(w["ecmwf"], .60)
                    self.assertAlmostEqual(sum(w.values()), 1.0)
                    self.assertEqual(set(w), {"ecmwf", *others})
                    for k in others:
                        self.assertAlmostEqual(w[k], .40 * historical[k] / total_other)

    def test_gdi_only_two_models(self):
        for d in (date(2026, 7, 1), date(2026, 11, 12)):
            w, _, missing = m.weights('convection', d, MODELS, pid='gdi')
            self.assertEqual(set(w), {'gfs', 'ecmwf'})
            self.assertAlmostEqual(w['gfs'], 0.60)
            self.assertAlmostEqual(w['ecmwf'], 0.40)
            self.assertEqual(set(missing), set())  # GDI policy explicitly excludes these slots

    def test_missing_secondary_models_normalizes(self):
        w, _, missed = m.weights('convection', date(2026, 7, 1), ['ecmwf9', 'gfs'], pid='ki')
        self.assertEqual(set(w), {'ecmwf', 'gfs'})
        self.assertAlmostEqual(w['gfs'], 0.40)
        self.assertEqual(set(missed), {'gem', 'icon', 'ukmo'})

if __name__ == '__main__':
    unittest.main()
