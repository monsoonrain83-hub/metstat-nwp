# -*- coding: utf-8 -*-
"""MetStat 60/40 production-gated daily MultiModel weight-policy checks."""
import os
import unittest
from datetime import date
from unittest.mock import patch
import mm_weights as w


class Strict6040Tests(unittest.TestCase):
    def test_five_independent_slots_and_no_resolution_double_count(self):
        available=['ecmwf9', 'ecmwf', 'gfs', 'gfs25', 'gem', 'icon', 'ukmo']
        for season in [date(2026, 7, 1), date(2026, 12, 1)]:
            weights, _, missing=w.strict_ecmwf_share_weights(
                'precip', season, available, pid='p24')
            self.assertEqual(set(weights),set(w.MM_MODELS))
            self.assertAlmostEqual(sum(weights.values()),1)
            self.assertAlmostEqual(weights['ecmwf'],0.60)
            self.assertAlmostEqual(sum(v for k,v in weights.items() if k!='ecmwf'),0.40)
            self.assertNotIn('ecmwf9',weights)
            self.assertNotIn('gfs25',weights)
            self.assertEqual(missing,[])

    def test_summer_peer_ratios_remain_from_previous_policy(self):
        weights, _, _ = w.strict_ecmwf_share_weights(
            'precip',date(2026,7,1),['ecmwf','gfs','icon','gem','ukmo'],pid='p24')
        self.assertAlmostEqual(weights['gem']/weights['gfs'],45/25)
        self.assertAlmostEqual(weights['icon']/weights['ukmo'],10/5)

    def test_absent_ecmwf_or_no_independent_peer_is_unavailable(self):
        d=date(2026,12,1)
        self.assertEqual(w.strict_ecmwf_share_weights(
            'precip',d,['gfs','icon','gem'],pid='p24')[0],{})
        self.assertEqual(w.strict_ecmwf_share_weights(
            'precip',d,['ecmwf9'],pid='p24')[0],{})

    def test_gfs_coarse_only_is_one_logical_peer(self):
        weights, _, missing = w.strict_ecmwf_share_weights(
            'pressure', date(2026,12,1),
            ['ecmwf9','gfs25'],pid='z500')
        self.assertEqual(weights,{'ecmwf':0.60,'gfs':0.40})
        self.assertEqual(set(missing),{'gem','icon','ukmo'})

    def test_env_gate_preserves_legacy_until_release(self):
        d=date(2026,12,1)
        available=['ecmwf9','gfs','icon','gem','ukmo']
        with patch.dict(os.environ,{'MM_ECMWF_SHARE_POLICY':'legacy'}):
            legacy=w.weights('precip',d,available,pid='p24')[0]
        with patch.dict(os.environ,{'MM_ECMWF_SHARE_POLICY':'strict60'}):
            active=w.weights('precip',d,available,pid='p24')[0]
        self.assertAlmostEqual(legacy['ecmwf'],0.45)
        self.assertAlmostEqual(active['ecmwf'],0.60)
        self.assertAlmostEqual(sum(active.values()),1)

    def test_selected_secondary_share_no_fake_missing_sources(self):
        weights, _, missing=w.strict_ecmwf_share_weights(
            'convection',date(2026,12,1),['ecmwf','gfs','gem','icon','ukmo'],
            pid='gdi')
        self.assertEqual(weights,{'ecmwf':0.60,'gfs':0.40})
        self.assertEqual(missing,[])


if __name__=='__main__':
    unittest.main()
