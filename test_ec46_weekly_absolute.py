import unittest
import numpy as np
from ec46_maps import weekly_values

class TestEC46WeeklyAbsolute(unittest.TestCase):
 def test_exact_seven_day_precipitation_and_temperature_mean(self):
  precip=np.ones((14,3,4),dtype=np.float32)*3
  temp=np.stack([np.ones((3,4),np.float32)*(20+i) for i in range(14)])
  r=weekly_values(precip,temp,0)
  self.assertTrue(np.allclose(r[0],21.0))
  self.assertTrue(np.allclose(r[1],23.0))
  r2=weekly_values(precip,temp,1)
  self.assertTrue(np.allclose(r2[0],21.0))
  self.assertTrue(np.allclose(r2[1],30.0))
 def test_missing_days_cannot_publish_fake_week(self):
  p=np.ones((7,10,10),np.float32);t=p.copy()
  p[0,0,:]=np.nan
  self.assertIsNone(weekly_values(p,t,0))
  self.assertIsNone(weekly_values(p,t,1))
 def test_negative_precip_is_clamped_and_does_not_become_anomaly(self):
  p=np.full((7,2,2),-0.5,np.float32);t=np.full_like(p,18.)
  z=weekly_values(p,t,0)
  self.assertTrue(np.array_equal(z[0],np.zeros((2,2),np.float32)))
  self.assertTrue(np.all(z[1]==18.))
if __name__=='__main__':unittest.main()
