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

    def test_parameter_weights(self):
        cases = [
            ('convection', 'cape', False, {'ecmwf': 50, 'gfs': 20, 'icon': 20, 'gem': 5, 'ukmo': 5}),
            ('convection', 'cin', False, {'ecmwf': 50, 'gfs': 20, 'icon': 20, 'gem': 5, 'ukmo': 5}),
            ('convection', 'ki', False, {'gfs': 50, 'ecmwf': 25}),
            ('humidity', 'pw', False, {'ecmwf': 50, 'gfs': 25}),
            ('wind', 'gust', False, {'ecmwf': 70}),
            ('temp', 't2m', False, {'ecmwf': 50}),
            ('temp', 'tmin', False, {'ecmwf': 40, 'gem': 20, 'gfs': 25, 'icon': 7.5, 'ukmo': 7.5}),
            ('temp', 'tmax', False, {'gfs': 50, 'ecmwf': 25}),
            ('precip', 'wrain', True, {'ecmwf': 50}),
            ('convection', 'hail', True, {'gfs': 50, 'ecmwf': 25})
        ]
        for d in (date(2026, 7, 1), date(2026, 11, 12)):
            for group, pid, secondary, expected in cases:
                with self.subTest(date=d, param=pid):
                    w, _, _ = m.weights(group, d, MODELS, pid=pid, secondary=secondary)
                    self.assertAlmostEqual(sum(w.values()), 1.0)
                    self.assertEqual(set(w), {'ecmwf', 'gfs', 'gem', 'icon', 'ukmo'})
                    self.assertAlmostEqual(w['ecmwf'], .60)
                    raw = m._specific_weights(group, pid, secondary)
                    total = sum(raw[k] for k in raw if k != 'ecmwf')
                    for model in w:
                        if model != 'ecmwf':
                            self.assertAlmostEqual(w[model], .40 * raw[model] / total)

    def test_gdi_only_two_models(self):
        for d in (date(2026, 7, 1), date(2026, 11, 12)):
            w, _, missing = m.weights('convection', d, MODELS, pid='gdi')
            self.assertEqual(set(w), {'gfs', 'ecmwf'})
            self.assertAlmostEqual(w['gfs'], 0.40)
            self.assertAlmostEqual(w['ecmwf'], 0.60)
            self.assertEqual(set(missing), set())  # GDI policy explicitly excludes these slots

    def test_missing_secondary_models_normalizes(self):
        w, _, missed = m.weights('convection', date(2026, 7, 1), ['ecmwf9', 'gfs'], pid='ki')
        self.assertEqual(set(w), {'ecmwf', 'gfs'})
        self.assertAlmostEqual(w['gfs'], 0.40)
        self.assertEqual(set(missed), {'gem', 'icon', 'ukmo'})

    def test_missing_core_model_never_becomes_single_model(self):
        for available in (['ecmwf9'], ['gfs'], ['ecmwf9','gem'], ['gfs','icon']):
            w, _, _ = m.weights('precip', date(2026,11,25), available)
            self.assertEqual(w, {})

    def test_family_deduplication_and_excluded_models(self):
        w, _, _ = m.weights('precip', date(2026,11,25),
            ['ecmwf9','ecmwf','gfs','gfs25','gem','icon','ukmo','iri','arpege','aifs','aigfs'])
        self.assertEqual(set(w), set(m.MM_MODELS))
        self.assertAlmostEqual(w['ecmwf'], .60)
        self.assertAlmostEqual(sum(w.values()), 1)

if __name__ == '__main__':
    unittest.main()
