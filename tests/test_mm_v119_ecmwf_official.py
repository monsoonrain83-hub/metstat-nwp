import unittest,json
from datetime import datetime,timezone
import numpy as np
from world_ecmwf_official import urls,select,daily_precip
RUN=datetime(2026,11,26,12,tzinfo=timezone.utc)
class OfficialIndex(unittest.TestCase):
    def test_documented_file_paths(self):
        self.assertTrue(urls('ifs','0p1',RUN,24,'z500')[0].endswith('-24h-oper-fc-pl.index'))
        self.assertTrue(urls('ifs','0p1',RUN,24,'t2m')[0].endswith('-24h-oper-fc-sfc.index'))
        self.assertIn('/aifs-single/0p25/oper/',urls('aifs-single','0p25',RUN,24,'pacc')[0])
    def test_single_exact_message(self):
        row={'param':'z','levelist':'500','step':'24','_offset':20,'_length':100}
        self.assertEqual(select(json.dumps(row).encode(),'z500',24),(20,100))
        with self.assertRaises(ValueError):select(json.dumps(row).encode(),'z500',48)
        with self.assertRaises(ValueError):select((json.dumps(row)+'\n'+json.dumps(row)).encode(),'z500',24)
    def test_bad_range_rejected(self):
        row={'param':'2t','step':'24','_offset':-1,'_length':100}
        with self.assertRaises(ValueError):select(json.dumps(row).encode(),'t2m',24)
    def test_accumulation_window(self):
        np.testing.assert_equal(daily_precip(np.array([5.,2.]),np.array([3.,2.])),[2.,0.])
        with self.assertRaises(ValueError):daily_precip(np.array([1.]),np.array([2.]))
if __name__=='__main__':unittest.main()
