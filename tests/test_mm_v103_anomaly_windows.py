"""Exercise disjoint forecast windows and real engine wiring, without network."""
import ast
import unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import numpy as np
import anomaly_windows as aw
import nwp_maps as nm

RUN=datetime(2026,11,26,12,tzinfo=timezone.utc)
def t(h):return RUN+timedelta(hours=h)
def a(x):return np.full((2,3),x,np.float32)
def series():
    return {t(h):(a(h),None,None,6) for h in range(6,361,6)}

class WindowTests(unittest.TestCase):
    def test_daily_all_four_cycles(self):
        for hour in (0,6,12,18):
            run=RUN.replace(hour=hour)
            end=run+timedelta(days=1)
            self.assertEqual(aw.sample_times(run,end,1),tuple(run+timedelta(hours=h) for h in (6,12,18,24)))
            self.assertTrue(nm.Engine.plan(None,nm.PARAMS['tanom'],SimpleNamespace(run=run),end,24,6,True))
    def test_disjoint_windows(self):
        windows=[set(aw.sample_times(RUN,t(h),5)) for h in (120,240,360)]
        self.assertEqual([len(x) for x in windows],[20]*3)
        self.assertEqual(len(set.union(*windows)),60)
        self.assertEqual([min(x) for x in windows],[t(6),t(126),t(246)])
        for h in (24,144,216,336,384):
            self.assertFalse(nm.Engine.plan(None,nm.PARAMS['tanom5'],SimpleNamespace(run=RUN),t(h),h,6,True))
        for h in (120,240,360):
            self.assertTrue(nm.Engine.plan(None,nm.PARAMS['tanom5'],SimpleNamespace(run=RUN),t(h),h,6,True))
    def test_means_are_independent(self):
        s=series()
        for end,mean in [(120,63),(240,183),(360,303)]:
            np.testing.assert_array_equal(aw.temperature_mean(s,RUN,t(end),5),a(mean))
    def test_extra_hourly_samples_do_not_change_weights(self):
        s=series()
        for h in (1,2,3,4,5,7,8,9,10,11):
            s[t(h)]=(a(10000),None,None,1)
        np.testing.assert_array_equal(aw.temperature_mean(s,RUN,t(24),1),a(15))
    def test_missing_step_rejects_only_affected_window(self):
        s=series();del s[t(126)]
        self.assertIsNone(aw.temperature_mean(s,RUN,t(240),5))
        self.assertIsNotNone(aw.temperature_mean(s,RUN,t(120),5))
        self.assertIsNotNone(aw.temperature_mean(s,RUN,t(360),5))
    def test_missing_cells_remain_masked(self):
        s=series();s[t(6)][0][0,0]=np.nan;s[t(12)][0][1,1]=np.inf
        out=aw.temperature_mean(s,RUN,t(24),1)
        self.assertTrue(np.isnan(out[0,0]) and np.isnan(out[1,1]))
        self.assertEqual(out[0,1],15)
    def test_invalid_shapes_and_all_missing(self):
        self.assertIsNone(aw.strict_mean([a(1),np.ones((3,3))]))
        self.assertIsNone(aw.strict_mean([a(np.nan)]))
        self.assertIsNone(aw.strict_mean([a(1),None]))
    def test_climatology_midpoints_and_no_missing_normal(self):
        calls=[]
        def c(v):
            calls.append(v);return a(10)
        np.testing.assert_array_equal(aw.climate_mean(c,RUN,t(240),5),a(10))
        self.assertEqual(calls,[t(h) for h in (132,156,180,204,228)])
        self.assertIsNone(aw.climate_mean(lambda v:None,RUN,t(24),1))
    def test_real_make_uses_exact_window_and_preserves_dem_call(self):
        st=SimpleNamespace(model='ecmwf',run=RUN,srcs={'main':object()},tser={'main':series()})
        reg=SimpleNamespace(key='iran')
        eng=SimpleNamespace(lapse=lambda st,r,f,full: f()+2 if full else self.fail('DEM full not used'))
        with patch.object(nm,'clim_at',return_value=a(20)):
            result,meta=nm.Engine.make(eng,nm.PARAMS['tanom5'],'tanom5',st,{},reg,t(240),240,6)
        np.testing.assert_array_equal(result,a(165))
        self.assertIn('1991',meta['note'])
        with patch.object(nm,'clim_at',return_value=None):
            self.assertIsNone(nm.Engine.make(eng,nm.PARAMS['tanom5'],'tanom5',st,{},reg,t(240),240,6))
    def test_real_step_records_temperature_before_precip_guard(self):
        tree=ast.parse(Path(nm.__file__).read_text())
        engine=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Engine')
        step=next(n for n in engine.body if isinstance(n,ast.FunctionDef) and n.name=='step')
        collection=next(n.lineno for n in ast.walk(step) if isinstance(n,ast.Assign) and any('st.tser[' in ast.unparse(t) for t in n.targets))
        precip_guard=next(n.lineno for n in ast.walk(step) if isinstance(n,ast.If) and ast.unparse(n.test)=='p is None')
        self.assertLess(collection,precip_guard)
    def test_absolute_temperature_plan_unchanged(self):
        st=SimpleNamespace(run=RUN)
        self.assertTrue(nm.Engine.plan(None,nm.PARAMS['tmax'],st,t(30),30,6,True))
        self.assertFalse(nm.Engine.plan(None,nm.PARAMS['tmax'],st,t(24),24,6,True))

if __name__=='__main__': unittest.main()
