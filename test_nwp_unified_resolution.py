import unittest
from datetime import datetime, timedelta, timezone
from nwp_unified_resolution import select_frame_source

class UnifiedSourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.run = datetime(2026, 11, 21, 0, tzinfo=timezone.utc)

    def select(self, m, v, lead, fields, run=None):
        r = run or self.run
        return select_frame_source(m, v, r, r + timedelta(hours=lead),
             lambda domain, var, cycle, valid:
                 (domain, var, int((valid - cycle).total_seconds() / 3600)) in fields)

    def test_ecmwf_240h_highres_then_360h_fallback(self):
        f = {('ecmwf_ifs','precipitation',240),
             ('ecmwf_ifs025','precipitation',240),
             ('ecmwf_ifs025','precipitation',246),
             ('ecmwf_ifs025','precipitation',360)}
        self.assertEqual(self.select('ecmwf','precipitation',240,f).nominal_resolution,'9 km')
        self.assertEqual(self.select('ecmwf','precipitation',246,f).nominal_resolution,'28 km')
        self.assertEqual(self.select('ecmwf','precipitation',360,f).lead_hours,360)
        self.assertIsNone(self.select('ecmwf','precipitation',366,f))

    def test_gfs_upper_level_uses_same_model_coarse_grid(self):
        f={('ncep_gfs025','geopotential_height_200hPa',240)}
        a=self.select('gfs','geopotential_height_200hPa',240,f)
        self.assertEqual(a.domain,'ncep_gfs025')
        self.assertIsNone(self.select('gfs','geopotential_height_300hPa',240,f))

    def test_ecmwf_06_and_18_cycles_do_not_fabricate_360h(self):
        f={('ecmwf_ifs025','temperature_2m',360),
           ('ecmwf_ifs025','temperature_2m',144)}
        for h in (6,18):
            r=self.run.replace(hour=h)
            self.assertIsNone(self.select('ecmwf','temperature_2m',360,f,run=r))
            self.assertIsNotNone(self.select('ecmwf','temperature_2m',144,f,run=r))

    def test_unknown_model_missing_source_and_bad_time(self):
        with self.assertRaises(ValueError):
            self.select('gem','t2m',3,set())
        self.assertIsNone(self.select('gfs','t2m',-3,set()))
        self.assertIsNone(self.select('gfs','t2m',385,set()))
        self.assertIsNone(self.select('gfs','t2m',24,set()))
if __name__ == '__main__': unittest.main()
