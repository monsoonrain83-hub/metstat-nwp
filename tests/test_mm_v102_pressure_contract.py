"""Regression for V102 daily model product policy and same-cycle pressure fallback."""
import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import nwp_maps as nm

RUN = datetime(2026,11,26,0,tzinfo=timezone.utc)
VALID = RUN+timedelta(hours=24)

class Source:
    def __init__(self, name, available=(), data=None, height=0):
        self.dom=name; self.available=set(available); self.data=data or {}
        self.checked=[]; self.reads=[]; self.height=height
    def exists(self, run, valid):
        self.checked.append((run,valid)); return (run,valid) in self.available
    def read(self,run,valid,names):
        self.reads.append((run,valid,names)); return self.data
    def hsurf(self):
        return np.full((2,2),self.height,dtype=np.float32)

class Region:
    key='me'
    def __init__(self): self.calls=[]
    def interp(self,source,array,order=1):
        self.calls.append((source.dom,array.shape))
        return np.array(array,dtype=np.float32)

def field(x): return np.full((2,2),x,dtype=np.float32)

class DailyPolicyTests(unittest.TestCase):
    def test_catalog_does_not_produce_cancelled_products(self):
        self.assertNotIn('z850a',nm.PARAMS)
        self.assertNotIn('tanom10',nm.PARAMS)
        self.assertNotIn('z850a',nm.EU_PIDS)
        self.assertIn('z850',nm.PARAMS)
        self.assertIn('z850',nm.EU_PIDS)
        self.assertIn('tanom',nm.PARAMS)
        self.assertIn('tanom5',nm.PARAMS)
    def test_z700a_only_ecmwf_and_gfs_sources(self):
        self.assertEqual(set(nm.PARAMS['z700a']['models']),{'ecmwf','gfs','gfs25'})
        self.assertTrue({'ecmwf','gfs','gfs25','icon','gem','ukmo'}<=set(nm.PARAMS['z500a']['models']))
        self.assertIn('z500a',nm.EU_PIDS)
        self.assertIn('z700a',nm.EU_PIDS)
        for k in ('z500a','z700a'):
            self.assertEqual(nm.PARAMS[k]['unit'],'dam')
    def test_previous_cycle_not_read(self):
        s=Source('coarse',[(RUN-timedelta(hours=6),VALID)],{'z':field(1)})
        self.assertIsNone(nm.read_same_cycle_upper(s,RUN,VALID,{'z'}))
        self.assertEqual(s.checked,[(RUN,VALID)])
        self.assertFalse(s.reads)
    def test_exact_cycle_read(self):
        s=Source('coarse',[(RUN,VALID)],{'z':field(1)})
        self.assertIs(nm.read_same_cycle_upper(s,RUN,VALID,{'z','a'}),s.data)
        self.assertEqual(s.reads,[(RUN,VALID,['a','z'])])
    def test_actual_step_uses_same_cycle_helper(self):
        tree=ast.parse(Path(nm.__file__).read_text())
        engine=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Engine')
        step=next(n for n in engine.body if isinstance(n,ast.FunctionDef) and n.name=='step')
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='read_same_cycle_upper' for n in ast.walk(step)))
        self.assertFalse(any(isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='rr' for n in ast.walk(step)))
    def test_grid_ownership_primary_preferred(self):
        src={'main':Source('fine'),'upper':Source('coarse')}
        d={'main':{'a':field(1),'b':field(2)},'upper':{'a':field(3),'b':field(4)}}
        u,s=nm.coherent_pressure_fields(src,d,['a','b'])
        self.assertIs(u,d['main']);self.assertIs(s,src['main'])
        del d['main']['b']
        u,s=nm.coherent_pressure_fields(src,d,['a','b'])
        self.assertIs(u,d['upper']);self.assertIs(s,src['upper'])
        del d['upper']['a']
        self.assertEqual(nm.coherent_pressure_fields(src,d,['a','b']),(None,None))
    def test_bad_shape_inf_and_no_shared_finite_cell(self):
        src={'main':Source('fine')}
        cases=[{'a':field(1),'b':np.ones((3,2))},
               {'a':field(float('inf')),'b':field(2)},
               {'a':np.array([[1,np.nan],[np.nan,np.nan]]),'b':np.array([[np.nan,2],[np.nan,np.nan]])}]
        for d in cases:
            with self.subTest(d=d):
                self.assertEqual(nm.coherent_pressure_fields(src,{'main':d},['a','b']),(None,None))
    def daily_state(self, level, value, coarse_height=0):
        src={'main':Source('fine',height=500),'upper':Source('coarse',height=coarse_height)}
        st=SimpleNamespace(model='gfs',srcs=src,run=RUN)
        d={'main':{},'upper':{f'geopotential_height_{level}hPa':field(value)}}
        for h in (6,12,18,24):
            nm.PD.collect(st,d,RUN+timedelta(hours=h),[level])
        return st,d
    def test_actual_z500_anomaly_uses_matching_coarse_grid(self):
        st,d=self.daily_state(500,5580)
        r=Region()
        ref=SimpleNamespace(at=lambda level,t,region:field(5500))
        with patch.object(nm,'daily_pressure_reference',return_value=ref):
            a,extra=nm.Engine.make(None,nm.PARAMS['z500a'],'z500a',st,d,r,VALID,24,6)
        np.testing.assert_array_equal(a,field(8))
        np.testing.assert_array_equal(extra['cont'],field(558))
        self.assertEqual(r.calls,[('coarse',(2,2)),('coarse',(2,2))])
    def test_z700_correct_grid_terrain_mask(self):
        st,d=self.daily_state(700,3000,3100)
        ref=SimpleNamespace(at=lambda level,t,region:field(2900))
        with patch.object(nm,'daily_pressure_reference',return_value=ref):
            self.assertIsNone(nm.Engine.make(None,nm.PARAMS['z700a'],'z700a',st,d,Region(),VALID,24,6))
    def test_no_climatology_no_anomaly(self):
        st,d=self.daily_state(500,5580)
        with patch.object(nm,'daily_pressure_reference',return_value=None):
            self.assertIsNone(nm.Engine.make(None,nm.PARAMS['z500a'],'z500a',st,d,Region(),VALID,24,6))
    def test_index_native_grid_not_mislabeled_when_fallback_missing(self):
        src={'main':Source('fine'),'upper':Source('coarse')}
        st=SimpleNamespace(model='gfs',srcs=src)
        d={'main':{f'{v}_{p}hPa':field(10) for v in ('temperature','relative_humidity') for p in (850,700,500)}}
        r=Region()
        with patch.object(nm,'k_index',return_value=field(21)):
            a,_=nm.Engine.make(None,nm.PARAMS['ki'],'ki',st,d,r,VALID,24,6)
        np.testing.assert_array_equal(a,field(21))
        self.assertEqual(r.calls,[('fine',(2,2))])

if __name__=='__main__': unittest.main()
