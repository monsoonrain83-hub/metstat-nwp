# -*- coding: utf-8 -*-
"""Regression tests for the storage-limited MetStat daily anomaly policy."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import mm_maps as MM
import mm_weights as W
import nwp_maps as N


UTC = timezone.utc


class NativeRegion:
    key = 'iran'

    def interp(self, src, field, order=1):
        return np.asarray(field, np.float32)


class Source:
    def hsurf(self):
        return None


class TestDailyAnomalyPolicy(unittest.TestCase):
    def test_model_matrix_and_unrequested_products_absent(self):
        p = N.PARAMS
        self.assertNotIn('tanom10', p)
        self.assertNotIn('mslpa', p)
        for model in ('ecmwf', 'gfs', 'gfs25', 'icon', 'ukmo', 'gem'):
            self.assertIn(model, p['z500a']['models'])
        for pid in ('z700a', 'z850a'):
            self.assertEqual(set(p[pid]['models']), {'ecmwf9', 'ecmwf', 'gfs', 'gfs25'})
        for model in ('ecmwf', 'ecmwf9', 'gfs', 'gfs25', 'icon', 'ukmo', 'gem'):
            self.assertIn(model, p['tanom']['models'])
            self.assertIn(model, p['tanom5']['models'])

    def test_ecmwf9_full_runs_extend_to_360h_without_changing_other_models(self):
        # ECMWF 0.1-degree IFS open data: 00/12 deterministic forecasts to +360h.
        # Only the model cap changes. A missing forecast step must never be invented.
        self.assertEqual(N.MODELS['ecmwf9']['hz']['00'], 360)
        self.assertEqual(N.MODELS['ecmwf9']['hz']['12'], 360)
        self.assertEqual(N.MODELS['ecmwf']['hz']['00'], 360)
        self.assertEqual(N.MODELS['ecmwf']['hz']['12'], 360)
        self.assertEqual(N.MODELS['ecmwf9']['hz']['06'], 144)
        self.assertEqual(N.MODELS['ecmwf9']['hz']['18'], 144)

    def test_ecmwf9_all_preferred_outputs_are_enabled_without_dropping_fallback(self):
        # The 0.1 degree run may only render inputs actually present at a step.
        # Keep 0.25 degree generation as a complete per-field/per-lead fallback.
        for pid, product in N.PARAMS.items():
            if 'ecmwf' in product['models']:
                self.assertIn('ecmwf9', product['models'], pid)
        for pid in ('p24', 'tanom', 'z500a', 'z700a', 'z850a', 'z500', 'sfc'):
            self.assertIn('ecmwf', N.PARAMS[pid]['models'])
            self.assertIn('ecmwf9', N.PARAMS[pid]['models'])
        pressure = N.needed_vars('ecmwf9', ['z500a', 'z700a', 'z850a'], 'all')
        for level in (500, 700, 850):
            self.assertIn(f'geopotential_height_{level}hPa', pressure)
        self.assertIn('pressure_msl', pressure)
        self.assertIn('temperature_2m', pressure)

    def test_pressure_anomaly_snapshots_once_each_24h(self):
        run = datetime(2026, 11, 20, 0, tzinfo=UTC)
        state = SimpleNamespace(run=run)
        for pid in ('z500a', 'z700a', 'z850a'):
            p = N.PARAMS[pid]
            for lead in (0, 3, 6, 12, 18, 24, 30, 48, 120, 144):
                vt = run + timedelta(hours=lead)
                self.assertEqual(N.Engine.plan(None, p, state, vt, lead, 6, True),
                                 lead > 0 and lead % 24 == 0, (pid, lead))

    def test_three_nonoverlapping_five_day_periods(self):
        run = datetime(2026, 11, 20, 0, tzinfo=UTC)
        state = SimpleNamespace(run=run)
        p = N.PARAMS['tanom5']
        for lead in range(0, 385, 6):
            valid = run + timedelta(hours=lead)
            actual = N.Engine.plan(None, p, state, valid, lead, 6, True)
            self.assertEqual(actual, lead in (120, 240, 360), lead)
        self.assertTrue(N.Engine.plan(None, N.PARAMS['tanom'], state, run + timedelta(hours=42), 42, 6, True))
        self.assertFalse(N.Engine.plan(None, N.PARAMS['tanom'], state, run + timedelta(hours=48), 48, 6, True))

    def test_five_day_anomaly_is_mean_not_sum(self):
        run = datetime(2026, 11, 20, 0, tzinfo=UTC)
        end = run + timedelta(hours=120)
        native = np.full((2, 2), 23.0, dtype=np.float32)
        series = {
            run + timedelta(hours=i): (native, native, native, 6.0)
            for i in range(6, 121, 6)
        }
        state = SimpleNamespace(model='ukmo', srcs={'main': Source()}, tser={'main': series})
        engine = SimpleNamespace(lapse=lambda st, region, fn, full=False: fn())
        with patch.object(N, 'clim_at', return_value=np.full((2, 2), 20.0, dtype=np.float32)):
            out = N.Engine.make(engine, N.PARAMS['tanom5'], 'tanom5', state, {}, NativeRegion(), end, 120, 6)
        self.assertIsNotNone(out)
        self.assertTrue(np.allclose(out[0], 3.0, atol=1e-5))

    def test_no_incomplete_five_day_anomaly(self):
        run = datetime(2026, 11, 20, 0, tzinfo=UTC)
        end = run + timedelta(hours=120)
        native = np.full((2, 2), 23.0, dtype=np.float32)
        series = {run + timedelta(hours=i): (native, native, native, 6.0) for i in range(48, 121, 6)}
        state = SimpleNamespace(model='ukmo', srcs={'main': Source()}, tser={'main': series})
        engine = SimpleNamespace(lapse=lambda st, region, fn, full=False: fn())
        self.assertIsNone(N.Engine.make(engine, N.PARAMS['tanom5'], 'tanom5', state, {}, NativeRegion(), end, 120, 6))

    def test_real_lower_resolution_pressure_field_as_fallback(self):
        run = datetime(2026, 11, 20, 0, tzinfo=UTC)
        state = SimpleNamespace(model='gfs', srcs={'main': Source(), 'upper': Source()})
        fields = {'main': {}, 'upper': {'geopotential_height_500hPa': np.full((2, 2), 5700.0)}}
        with patch.object(N, 'z_clim_at', return_value=np.full((2, 2), 5600.0)):
            out = N.Engine.make(None, N.PARAMS['z500a'], 'z500a', state, fields, NativeRegion(), run, 0, 0)
        self.assertIsNotNone(out)
        self.assertTrue(np.allclose(out[0], 10.0, atol=1e-5))
        self.assertIsNone(N.Engine.make(None, N.PARAMS['z500a'], 'z500a', state, {'main': {}}, NativeRegion(), run, 0, 0))

    def test_geopotential_multimodel_uses_existing_daily_weights(self):
        self.assertEqual(W.group_of('z500a'), 'pressure')
        self.assertEqual(W.group_of('z700a'), 'pressure')
        self.assertEqual(W.group_of('z850a'), 'pressure')
        blend = MM.MMCombiner.__new__(MM.MMCombiner)
        blend.nm = SimpleNamespace(PARAMS=N.PARAMS)
        p = blend.build_params()
        for pid in ('z500a', 'z700a', 'z850a', 'tanom', 'tanom5'):
            self.assertIn(pid, p)
            self.assertEqual(MM.max_anomaly_lead(pid), 384)
        self.assertEqual(MM.max_anomaly_lead('p24'), 120)
        w, _, _ = W.weights('pressure', run_date(), ['ecmwf', 'gfs'], pid='z700a')
        self.assertAlmostEqual(w['ecmwf'], 0.6)
        self.assertAlmostEqual(w['gfs'], 0.4)


def run_date():
    return datetime(2026, 11, 20, tzinfo=UTC).date()


if __name__ == '__main__':
    unittest.main()
