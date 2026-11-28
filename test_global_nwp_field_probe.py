import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import numpy as np
import global_nwp_field_probe as p

RUN=datetime(2026,11,27,12,tzinfo=timezone.utc)
class Source:
    nx,ny,lo0,la0,dx,dy=720,361,-180,-90,.5,.5
    def __init__(self,dom,names):
        self.dom,self.names=dom,names
        self.calls=[]
    def exists(self,r,v): return True
    def read(self,r,v,names):
        self.calls.append((r,v,tuple(names)))
        return {n:np.ones((361,720),np.float32) for n in names if n in self.names}

class ProbeTests(unittest.TestCase):
    def test_wind_pair_cannot_mix_domains(self):
        u,v=p.GROUPS['wind10']
        sources=[Source('ecmwf_ifs',[u]),Source('ecmwf_ifs025',[v])]
        with patch.object(p,'GROUPS',{'wind10':(u,v)}):
            result=p.inventory('ecmwf',RUN,24,sources)
        self.assertIsNone(result['groups']['wind10']['selected_domain'])
    def test_same_domain_pair_preferred(self):
        u,v=p.GROUPS['wind10']
        sources=[Source('ecmwf_ifs',[u]),Source('ecmwf_ifs025',[u,v])]
        with patch.object(p,'GROUPS',{'wind10':(u,v)}):
            result=p.inventory('ecmwf',RUN,24,sources)
        group=result['groups']['wind10']
        self.assertEqual(group['selected_domain'],'ecmwf_ifs025')
        self.assertFalse(group['candidates']['ecmwf_ifs025']['publication_eligible'])
        self.assertEqual(sources[1].calls[0][:2],(RUN,RUN+timedelta(hours=24)))
    def test_precipitation_window_not_invented(self):
        with patch.object(p,'GROUPS',{'precipitation_native':('precipitation',)}):
            r=p.inventory('gfs',RUN,24,[Source('ncep_gfs025',['precipitation'])])
        self.assertFalse(r['groups']['precipitation_native']['accumulation_window_verified'])
    def test_regional_shape_rejected(self):
        s=Source('ncep_gfs025',['precipitation'])
        s.lo0=0
        with patch.object(p,'GROUPS',{'precipitation_native':('precipitation',)}):
            r=p.inventory('gfs',RUN,24,[s])
        self.assertIsNone(r['groups']['precipitation_native']['selected_domain'])
    def test_ecmwf_short_cycle_horizon(self):
        with patch.object(p,'GROUPS',{'precipitation_native':('precipitation',)}):
            r=p.inventory('ecmwf',RUN.replace(hour=6),360,[Source('ecmwf_ifs',['precipitation'])])
        self.assertIsNone(r['groups']['precipitation_native']['selected_domain'])
if __name__=='__main__': unittest.main()
