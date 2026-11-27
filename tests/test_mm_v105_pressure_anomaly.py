"""Tests for user-revised six-hour anomalies and absolute-field H/L invariance."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
import pressure_anomaly as pa
import nwp_maps as nm
import hl_centers as hl

RUN=datetime(2026,11,26,6,tzinfo=timezone.utc)
def t(h):return RUN+timedelta(hours=h)
def a(v):return np.full((2,2),v,np.float32)
class Source:
    dom='same'
    def hsurf(self):return a(0)
def reg():
    lat,lon=np.meshgrid([30.,31.],[50.,51.],indexing='ij')
    return SimpleNamespace(key='me',lat=lat,lon=lon,interp=lambda src,v:v.copy())
def ref(source='ERA5'):
    n=366 if source=='ERA5' else 365
    v=np.full((n,4,2,2),5500.,np.float32)
    v[58,1]=5580;v[59,1]=5600;v[60,1]=5620
    return pa.SynopticReference(dict(lat=np.array([30.,31.]),lon=np.array([50.,51.]),field=v),
          dict(schema=1,source=source,parameter='z500',base_period='1991-2020',
               calendar=f'{n}_month_day',temporal_basis='synoptic_6h',hours_utc=[0,6,12,18],units='m'),'z500',source)
class FrameTests(unittest.TestCase):
    def test_six_hour_not_daily(self):
        st=SimpleNamespace(run=RUN)
        for p in ('z850a','z700a','z500a','z300a','mslpa'):
            for h in (0,6,12,18,24,30,42,240):
                self.assertTrue(nm.Engine.plan(None,nm.PARAMS[p],st,t(h),h,6,True))
            for h in (-6,3,9,15,25):
                self.assertFalse(nm.Engine.plan(None,nm.PARAMS[p],st,t(h),h,3,True))
    def test_every_frame_calculated_without_history(self):
        st=SimpleNamespace(run=RUN,model='gfs',srcs={'main':Source()})
        r=reg()
        for p,raw,norm,expected in [('z850a',1500,1400,10),('z700a',3100,3000,10),
          ('z500a',5550,5500,5),('z300a',9300,9200,10),('mslpa',1020,1000,20)]:
            k='pressure_msl' if p=='mslpa' else 'geopotential_height_'+p[1:4]+'hPa'
            with patch.object(nm,'pressure_reference',return_value=SimpleNamespace(at=lambda time,region:a(norm),source='ERA5')):
                out,extra=nm.Engine.make(None,nm.PARAMS[p],p,st,{'main':{k:a(raw)}},r,t(6),6,6)
                np.testing.assert_array_equal(out,a(expected))
                kind,height,_=extra['hl']
                self.assertEqual(kind,'msl' if p=='mslpa' else int(p[1:4]))
                np.testing.assert_array_equal(height,a(raw if p=='mslpa' else raw/10))
                self.assertNotIn('anomaly_hl',extra)
    def test_exact_calendar_no_drift_and_leap_day(self):
        r=reg()
        d=lambda y,m,day:datetime(y,m,day,6,tzinfo=timezone.utc)
        e=ref();n=ref('NCEP-NCAR Reanalysis 1')
        np.testing.assert_array_equal(e.at(d(2028,2,29),r),a(5600))
        np.testing.assert_array_equal(e.at(d(2027,3,1),r),a(5620))
        np.testing.assert_array_equal(n.at(d(2028,2,29),r),a(5590))
        np.testing.assert_array_equal(n.at(d(2027,3,1),r),a(5600))
    def test_no_reference_no_product(self):
        self.assertIsNone(pa.anomaly(Source(),a(5500),'z500',t(6),reg(),None))
    def test_bad_units_and_missing_cells(self):
        self.assertIsNone(pa.physical(a(550),'z500'))
        v=a(5500);v[0,0]=np.inf
        out,_=pa.anomaly(Source(),v,'z500',t(6),reg(),SimpleNamespace(at=lambda t,r:a(5500)))
        self.assertTrue(np.isnan(out[0,0]))
    def test_centers_unchanged_when_anomaly_sign_reverses(self):
        y,x=np.mgrid[:400,:600]
        height=(5500+200*np.exp(-((x-130)**2+(y-200)**2)/2000)-200*np.exp(-((x-470)**2+(y-200)**2)/2000)).astype(np.float32)
        r=SimpleNamespace(key='me',interp=lambda src,v:v.copy())
        st=SimpleNamespace(run=RUN,model='gfs',srcs={'main':Source()})
        d={'main':{'geopotential_height_500hPa':height}}
        layers=[]
        expected=hl.find_centers(height/10,500,None,16)
        self.assertEqual({c[0] for c in expected},{'H','L'})
        for norm in (5300.,5800.):
            with patch.object(nm,'pressure_reference',return_value=SimpleNamespace(at=lambda t,r:np.full_like(height,norm),source='ERA5')):
                out,extra=nm.Engine.make(None,nm.PARAMS['z500a'],'z500a',st,d,r,t(6),6,6)
            kind,field,ps=extra['hl']
            centers=hl.find_centers(field,kind,ps,16)
            self.assertEqual(centers,expected)
            layers.append(hl.encode_layer(centers,600,400))
        self.assertEqual(layers[0],layers[1])
    def test_existing_absolute_color_and_300_support(self):
        self.assertEqual(hl.COL,{'L':(214,32,28,255),'H':(31,79,216,255)})
        self.assertIn(300,hl.THR)
        self.assertFalse(hasattr(hl,'find_anomaly_centers'))
    def test_fixed_300_palette(self):
        self.assertIn('z300a',nm.styles.SC)
if __name__=='__main__':unittest.main()
