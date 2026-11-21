import unittest
from ec46_maps import validate_daily_batch

def point(days=46, offset=0):
    from datetime import date,timedelta
    start=date(2026,11,22)+timedelta(days=offset)
    return {'daily':{
        'time':[(start+timedelta(days=i)).isoformat() for i in range(days)],
        'precipitation_sum':[1.0]*days,
        'temperature_2m_mean':[20.0]*days}}

class DailyEC46BatchIntegrity(unittest.TestCase):
    def test_valid_points(self):
        self.assertEqual(len(validate_daily_batch([point(),point()],2)),46)
    def test_truncated_response_rejected(self):
        with self.assertRaisesRegex(ValueError,'point count'):
            validate_daily_batch([point()],2)
    def test_misaligned_dates_rejected(self):
        with self.assertRaisesRegex(ValueError,'mismatched'):
            validate_daily_batch([point(),point(offset=1)],2)
    def test_partial_daily_series_rejected(self):
        p=point();p['daily']['precipitation_sum'].pop()
        with self.assertRaisesRegex(ValueError,'incomplete'):
            validate_daily_batch([p],1)
    def test_duplicate_dates_rejected(self):
        p=point();p['daily']['time'][1]=p['daily']['time'][0]
        with self.assertRaisesRegex(ValueError,'time axis'):
            validate_daily_batch([p],1)
    def test_nan_and_empty_rejected(self):
        p=point();p['daily']['temperature_2m_mean'][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            validate_daily_batch([p],1)
        p=point();p['daily']['precipitation_sum']=[None]*46
        with self.assertRaisesRegex(ValueError,'empty'):
            validate_daily_batch([p],1)

if __name__=='__main__': unittest.main()
