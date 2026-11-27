"""Official GDPS contract tests with metadata fixtures, not upstream data."""
import unittest,sys
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
import numpy as np
import world_gem_official as G

RUN=datetime(2026,11,26,12,tzinfo=timezone.utc)
VALID=RUN+timedelta(hours=24)
def sample():
    d=dict(dataDate=20261126,dataTime=1200,validityDate=20261127,validityTime=1200,
           stepType='instant',typeOfLevel='isobaricInhPa',level=850,shortName='t',
           gridType='regular_ll',Ni=2400,Nj=1201,iScansNegatively=0,jPointsAreConsecutive=0,
           alternativeRowScanning=0,latitudeOfFirstGridPointInDegrees=90.,
           latitudeOfLastGridPointInDegrees=-90.,longitudeOfFirstGridPointInDegrees=0.,
           longitudeOfLastGridPointInDegrees=359.85,iDirectionIncrementInDegrees=.15,
           jDirectionIncrementInDegrees=.15,jScansPositively=0,bitmapPresent=0,units='K')
    a=np.full((1201,2400),280.,np.float32);a[0,0]=290.;a[-1,1200]=300.
    ec=SimpleNamespace(codes_new_from_message=lambda raw:1,codes_get=lambda g,k:d[k],
                       codes_get_values=lambda g:a.ravel(),codes_release=lambda g:None)
    raw=b'GRIB'+b'\0'*3+b'\2'+(20).to_bytes(8,'big')+b'7777'
    return d,ec,raw
class Official(unittest.TestCase):
    def test_exact_url(self):
        self.assertEqual(G.field_url(RUN,VALID,'temperature_850hPa'),
          'https://dd.weather.gc.ca/20261126/WXO-DD/model_gdps/15km/12/024/20261126T12Z_MSC_GDPS_AirTemp_IsbL-0850_LatLon0.15_PT024H.grib2')
        for run,valid in [(RUN+timedelta(hours=6),VALID),(RUN,RUN+timedelta(hours=85)),(RUN,RUN-timedelta(hours=1))]:
            with self.assertRaises(ValueError):G.field_url(run,valid,'temperature_850hPa')
    def test_convert_units_not_guessed(self):
        np.testing.assert_allclose(G.convert(np.array([100000.]),'pressure','Pa'),[1000])
        np.testing.assert_allclose(G.convert(np.array([5500.]),'height','gpm'),[5500])
        with self.assertRaises(ValueError):G.convert(np.array([5500.]),'height','unknown')
    def test_decode_orientation_and_temperature(self):
        d,ec,raw=sample()
        with patch.dict(sys.modules,{'eccodes':ec}):
            a,meta=G.decode(raw,'temperature_850hPa',RUN,VALID)
        self.assertEqual(a.shape,(1201,2400))
        self.assertAlmostEqual(float(a[0,0]),26.85,places=3)
        self.assertAlmostEqual(float(a[-1,1200]),16.85,places=3)
        self.assertEqual(meta['origin'],[-180,-90])
    def test_reject_wrong_cycle_grid_or_level(self):
        for key,value in [('dataTime',600),('validityTime',1800),('level',700),
                          ('Ni',100),('gridType','rotated_ll'),('units','unknown'),
                          ('shortName','r'),('alternativeRowScanning',1)]:
            d,ec,raw=sample();d[key]=value
            with self.subTest(key=key),patch.dict(sys.modules,{'eccodes':ec}),self.assertRaises(ValueError):
                G.decode(raw,'temperature_850hPa',RUN,VALID)
    def test_reject_truncation(self):
        _,ec,raw=sample()
        with patch.dict(sys.modules,{'eccodes':ec}),self.assertRaises(ValueError):
            G.decode(raw+b'7777','temperature_850hPa',RUN,VALID)
if __name__=='__main__':unittest.main()
