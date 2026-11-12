# -*- coding: utf-8 -*-
"""Regression tests for the four-model, 120-hour MetStat policy."""
import unittest
from datetime import date
import mm_weights as m

class TestMultimodelWeights(unittest.TestCase):
    def test_cold_all_groups(self):
        for g in m.GROUPS:
            b, s = m.base_weights(g, date(2026, 11, 12))
            self.assertEqual((s, b), ('cold', {'ecmwf': 60, 'gfs': 20, 'gem': 10, 'icon': 10}))
    def test_warm_all_groups(self):
        for g in m.GROUPS:
            b, s = m.base_weights(g, date(2026, 7, 1))
            self.assertEqual((s, b), ('warm', {'gem': 60, 'gfs': 15, 'ecmwf': 15, 'icon': 10}))
    def test_season_boundaries_1405(self):
        # 1405/02/29=2026-05-19; 1405/02/30=2026-05-20
        # 1405/08/04=2026-10-26; 1405/08/05=2026-10-27
        for day, expected in [(date(2026,5,19),'cold'), (date(2026,5,20),'warm'),
                              (date(2026,10,26),'warm'), (date(2026,10,27),'cold')]:
            self.assertEqual(m.season(day), expected)
    def test_priority_is_per_available_parameter(self):
        sources=m.pick_sources(['ecmwf9','ecmwf','gfs','gem','icon'])
        self.assertEqual(sources['ecmwf'], 'ecmwf9')
        sources=m.pick_sources(['ecmwf','gfs','gem','icon'])
        self.assertEqual(sources['ecmwf'], 'ecmwf')
    def test_no_ukmo_and_exact_normalization(self):
        for d in (date(2026,7,1),date(2026,11,12)):
            for group in m.GROUPS:
                w,_,missing=m.weights(group,d,['ecmwf9','ecmwf','gfs','icon','gem','ukmo'])
                self.assertEqual(set(w), {'ecmwf','gfs','gem','icon'})
                self.assertAlmostEqual(sum(w.values()),1.0)
                self.assertEqual(missing,[])
if __name__=='__main__': unittest.main()
