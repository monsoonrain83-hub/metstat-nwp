import unittest
from wk_maps import validate_ec46_batch

def point(times=('2026-11-23','2026-11-30')):
    return {'weekly':{'time':list(times),'temperature_2m_anomaly':[1.0,2.0],
                      'precipitation_anomaly':[3.0,4.0]}}

class EC46IntegrityTests(unittest.TestCase):
    def test_good_batch(self):
        t, rows=validate_ec46_batch([point(),point()],2)
        self.assertEqual(len(rows),2)
        self.assertEqual(t,['2026-11-23','2026-11-30'])

    def test_truncated_batch(self):
        with self.assertRaisesRegex(ValueError,'point count'):
            validate_ec46_batch([point()],2)

    def test_different_time_axes(self):
        with self.assertRaisesRegex(ValueError,'mismatched'):
            validate_ec46_batch([point(),point(('2026-11-24','2026-12-01'))],2)

    def test_malformed_field(self):
        bad=point();bad['weekly']['precipitation_anomaly']=[1.0]
        with self.assertRaisesRegex(ValueError,'incomplete'):
            validate_ec46_batch([bad],1)

    def test_all_missing_field(self):
        bad=point();bad['weekly']['temperature_2m_anomaly']=[None,None]
        with self.assertRaisesRegex(ValueError,'empty'):
            validate_ec46_batch([bad],1)

    def test_wrong_baseline_time(self):
        with self.assertRaisesRegex(ValueError,'mismatched'):
            validate_ec46_batch([point()],1,['2026-11-22','2026-11-29'])

if __name__=='__main__': unittest.main()
