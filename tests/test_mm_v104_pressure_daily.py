"""V104 pressure day and reference calendar tests. Synthetic inputs only."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import numpy as np
import pressure_daily as pd
import nwp_maps as nm

RUN=datetime(2026,11,26,6,tzinfo=timezone.utc)
def at(h): return RUN+timedelta(hours=h)
def a(x): return np.full((2,2),x,np.float32)
class Source:
    def __init__(self,dom,terrain=0): self.dom=dom;self.terrain=terrain;self.dx=1.
    def hsurf(self): return a(self.terrain)
def state():
    return SimpleNamespace(run=RUN,srcs={'main':Source('fine'),'upper':Source('coarse')})
def data(level,x):
    return {f'geopotential_height_{level}hPa':a(x)}
def metadata():
    return dict(schema=1,source='ERA5',base_period='1991-2020',temporal_basis='synoptic_6h',
                calendar='366_month_day',hours_utc=[0,6,12,18],units='m')
def arrays():
    v=np.full((366,4,2,2),5500.,np.float32)
    v[59,1]=5559.;v[60,1]=5560.;v[59,2]=5659.
    return dict(lat=np.array([30.,31.]),lon=np.array([50.,51.]),z500=v,
                z700=np.full_like(v,3000.))
def region():
    lat,lon=np.meshgrid([30.,31.],[50.,51.],indexing='ij')
    return SimpleNamespace(lat=lat,lon=lon,interp=lambda src,x:x.copy())
class DailyPressureTests(unittest.TestCase):
    def test_plan_only_daily_for_anomaly(self):
        st=state()
        for pid in ('z500a','z700a'):
            for h in (0,6,12,18,30,42):
                self.assertFalse(nm.Engine.plan(None,nm.PARAMS[pid],st,at(h),h,6,True))
            for h in (24,48,360):
                self.assertTrue(nm.Engine.plan(None,nm.PARAMS[pid],st,at(h),h,6,True))
        self.assertTrue(nm.Engine.plan(None,nm.PARAMS['z500'],st,at(6),6,6,True))
    def test_native_mean_and_bounded_history(self):
        st=state()
        for h in range(6,361,6):
            pd.collect(st,{'main':data(500,5500+h)},at(h),[500])
            self.assertLessEqual(len(st.zser[('main',500)]),4)
        src,z=pd.native_day(st,at(360),500)
        self.assertEqual(src.dom,'fine')
        np.testing.assert_array_equal(z,a(5851))
    def test_no_resolution_mixing(self):
        st=state()
        for h in (6,12,18,24):
            pd.collect(st,{'main' if h<=12 else 'upper':data(500,5580)},at(h),[500])
        self.assertIsNone(pd.native_day(st,at(24),500))
    def test_complete_coarse_fallback_and_primary_priority(self):
        st=state()
        for h in (6,12,18,24):
            d={'upper':data(500,5580)}
            if h!=12:d['main']=data(500,5600)
            pd.collect(st,d,at(h),[500])
        self.assertEqual(pd.native_day(st,at(24),500)[0].dom,'coarse')
        pd.collect(st,{'main':data(500,5600)},at(12),[500])
        self.assertEqual(pd.native_day(st,at(24),500)[0].dom,'fine')
    def test_grid_change_invalidates_day(self):
        st=state()
        for h in (6,12,18,24):
            if h==18:st.srcs['main'].dx=.5
            pd.collect(st,{'main':data(500,5500)},at(h),[500])
        self.assertIsNone(pd.native_day(st,at(24),500))
    def test_700_terrain_and_incomplete_cells(self):
        st=state();st.srcs['main'].terrain=3000
        for h in (6,12,18,24):
            v=a(3100);v[0,0]=2900 if h==6 else 3100
            pd.collect(st,{'main':{'geopotential_height_700hPa':v}},at(h),[700])
        _,z=pd.native_day(st,at(24),700)
        self.assertTrue(np.isnan(z[0,0]));self.assertEqual(z[1,1],3100)
    def test_units_and_missing(self):
        self.assertIsNone(pd.physical_height(a(550),500))
        self.assertIsNone(pd.physical_height(a(np.inf),500))
        st=state()
        for h in (6,12,18,24):
            pd.collect(st,{'main':data(500,5580)},at(h),[500])
        ref=SimpleNamespace(at=lambda level,t,r:a(5500))
        z,cont,source=pd.anomaly(st,at(24),500,region(),ref)
        np.testing.assert_array_equal(z,a(8));np.testing.assert_array_equal(cont,a(558))
        self.assertEqual(source,'fine')
        self.assertIsNone(pd.anomaly(st,at(24),500,region(),None))
    def test_calendar_exact_leap_day_and_hour(self):
        r=pd.SynopticReference(arrays(),metadata());g=region()
        def d(y,m,day,h):return datetime(y,m,day,h,tzinfo=timezone.utc)
        np.testing.assert_array_equal(r.at(500,d(2028,2,29,6),g),a(5559))
        np.testing.assert_array_equal(r.at(500,d(2027,3,1,6),g),a(5560))
        np.testing.assert_array_equal(r.at(500,d(2028,2,29,12),g),a(5659))
        self.assertIsNone(r.at(500,d(2028,2,29,3),g))
        g.lon+=10;self.assertIsNone(r.at(500,d(2028,2,29,6),g))
    def test_wrong_base_and_bad_axes_rejected(self):
        m=metadata();m['base_period']='1990-2019'
        with self.assertRaises(ValueError):pd.SynopticReference(arrays(),m)
        v=arrays();v['lat']=np.array([31.,30.])
        with self.assertRaises(ValueError):pd.SynopticReference(v,metadata())
    def test_archive_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'clim.npz';j=Path(td)/'clim.json'
            np.savez_compressed(p,**arrays())
            m=metadata();m['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            j.write_text(json.dumps(m))
            self.assertIsInstance(pd.SynopticReference.load(p,j),pd.SynopticReference)
            m['sha256']='0'*64;j.write_text(json.dumps(m))
            with self.assertRaises(ValueError):pd.SynopticReference.load(p,j)
if __name__=='__main__':unittest.main()
