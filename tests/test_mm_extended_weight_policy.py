# -*- coding: utf-8 -*-
"""Regression coverage for 60/40 extended-range products (no seasonal blend)."""
import unittest
import numpy as np
import extended_mm as E


class TestExtendedMultimodel(unittest.TestCase):
    def test_weekly_weights(self):
        self.assertEqual(E.weights('weekly', ['ecwk', 'cfswk']), {'ecwk': 0.6, 'cfswk': 0.4})
        self.assertEqual(E.weights('weekly', ['ecwk', 'iri']), {})

    def test_monthly_equal_split_and_exclusion(self):
        w = E.weights('monthly', ['ecmwfseas', 'cfsv2', 'gfdl', 'nasa', 'nmme', 'iri'])
        self.assertEqual(set(w), {'ecmwfseas', 'cfsv2', 'gfdl', 'nasa'})
        self.assertAlmostEqual(w['ecmwfseas'], 0.6)
        for m in ('cfsv2', 'gfdl', 'nasa'):
            self.assertAlmostEqual(w[m], 0.4 / 3)
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertEqual(E.weights('monthly', ['nasa', 'cfsv2']), {})

    def test_no_seasonal_multimodel(self):
        self.assertEqual(E.weights('seasonal', ['ecmwfseass', 'iri']), {})
        self.assertEqual(E.blend('seasonal', {'ecmwfseass': np.ones((2, 2)), 'iri': np.ones((2, 2))}), (None, {}))

    def test_weighted_aggregate_and_pixel_guardrail(self):
        a = np.array([[2.0, np.nan], [3.0, 4.0]])
        b = np.array([[7.0, 4.0], [np.nan, 6.0]])
        c = np.array([[9.0, 8.0], [np.nan, np.nan]])
        result, w = E.blend('monthly', {'ecmwfseas': a, 'cfsv2': b, 'nasa': c, 'nmme': np.zeros((2, 2))})
        self.assertAlmostEqual(result[0, 0], 2 * .6 + 7 * .2 + 9 * .2)
        self.assertTrue(np.isnan(result[0, 1]))  # ECMWF data missing
        self.assertTrue(np.isnan(result[1, 0]))  # no second member
        self.assertAlmostEqual(result[1, 1], (4 * .6 + 6 * .2) / .8)
        self.assertEqual(len(w), 3)

    def test_invalid_grid_not_silently_combined(self):
        with self.assertRaises(ValueError):
            E.blend('weekly', {'ecwk': np.ones((2, 2)), 'cfswk': np.ones((3, 2))})


if __name__ == '__main__':
    unittest.main()
