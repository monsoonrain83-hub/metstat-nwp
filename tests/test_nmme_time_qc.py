import unittest
from datetime import datetime
from nmme_time_qc import target_month_offsets, valid_months

class TestNMMETime(unittest.TestCase):
    def test_absolute_month_epoch(self):
        self.assertEqual(target_month_offsets([802.5,803.5,804.5], 'months since 1960-01-01', '360_day', '2026110800'), [0,1,2])
    def test_explicit_month_leads(self):
        self.assertEqual(target_month_offsets([.5,1.5,2.5], 'months', 'standard', '2026110800'), [0,1,2])
    def test_absolute_day_axis(self):
        self.assertEqual(target_month_offsets([0,30], 'days since 2026-11-01','360_day','2026110800', lambda *a,**k:[datetime(2026,11,1),datetime(2026,12,1)]),[0,1])
    def test_reject_false_future(self):
        for values,units in [([802.5],'months'),([0,1],''),([1,1],'months'),([2,1],'months'),([float('nan')],'months'),([-1],'months')]:
            with self.subTest(values=values,units=units):
                with self.assertRaises(ValueError): target_month_offsets(values,units,'standard','2026110800')
    def test_year_boundary(self):
        self.assertEqual(valid_months('2026110800',[0,1,2]),['2026110100','2026120100','2027010100'])
    def test_bad_offsets(self):
        with self.assertRaises(ValueError): valid_months('2026110800',[800])
if __name__=='__main__': unittest.main()
