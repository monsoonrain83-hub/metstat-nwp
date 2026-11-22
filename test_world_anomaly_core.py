import unittest
from datetime import datetime, timezone
import numpy as np
from world_anomaly_core import anomaly, five_day_blocks, AnomalyUnavailable

class WorldAnomalyTests(unittest.TestCase):
    def setUp(self):
        self.valid=datetime(2026,11,23,12,tzinfo=timezone.utc)
        self.f={'bbox_wgs84':[-180.,-90.,180.,90.],'grid_shape':[4,8],'grid_id':'global-0.25deg','units':'K'}
        self.c={**self.f,'base_period':'1991-2020','source':'ERA5 verified global 1991-2020',
                'valid_mmdd':'11-23','valid_hour_utc':12,'verified':True}
    def test_k_to_c_anomaly_and_provenance(self):
        out, m=anomaly('ecmwf','t2m',self.valid,np.full((4,8),283.15),np.full((4,8),278.15),self.f,self.c)
        self.assertAlmostEqual(float(out[0,0]),5)
        self.assertEqual(m['units'],'°C')
        self.assertEqual(m['baseline_period'],'1991-2020')
    def test_geopotential_to_dam_and_mslp(self):
        for param,raw,ref,fu,cu,want in [
            ('z500',5800*9.80665,5700,'m²/s²','m',10),
            ('mslp',101500,1005,'Pa','hPa',10)]:
            f={**self.f,'units':fu};c={**self.c,'units':cu}
            x,_=anomaly('gfs',param,self.valid,np.full((4,8),raw),np.full((4,8),ref),f,c)
            self.assertAlmostEqual(float(x[0,0]),want,places=3)
    def test_no_regional_baseline_no_regrid_no_bad_hour(self):
        for patch in [{'bbox_wgs84':[-15,5,95,65]}, {'grid_id':'regional'}, {'valid_hour_utc':0}, {'source':''}, {'verified':False}]:
            with self.subTest(patch=patch),self.assertRaises(AnomalyUnavailable):
                anomaly('ecmwf','t2m',self.valid,np.full((4,8),280),np.full((4,8),279),self.f,{**self.c,**patch})
    def test_icon_cannot_label_z850_and_missing_climate_rejected(self):
        with self.assertRaises(AnomalyUnavailable):
            anomaly('icon','z850',self.valid,np.full((4,8),1500),np.full((4,8),1500),
                    {**self.f,'units':'m'},{**self.c,'units':'m'})
        with self.assertRaises(AnomalyUnavailable):
            anomaly('icon','t2m',self.valid,np.full((4,8),280),np.full((4,8),280),
                    self.f,{**self.c,'base_period':'1990-2019'})
    def test_independent_five_day_periods(self):
        a=five_day_blocks({d:np.full((4,8),d,dtype=float) for d in range(1,16)})
        self.assertEqual(tuple(a),( '1-5','6-10','11-15'))
        self.assertEqual([float(a[k][0,0]) for k in a],[3,8,13])
        with self.assertRaises(AnomalyUnavailable):
            five_day_blocks({d:np.full((4,8),d,dtype=float) for d in range(1,15)})
if __name__=='__main__':unittest.main()
