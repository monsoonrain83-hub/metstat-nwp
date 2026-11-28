import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from global_nwp_series import stage_series, BASE_FIELDS

RUN = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)
def stamp(dt): return dt.isoformat().replace('+00:00','Z')

def manifest(model, h, run=RUN, names=BASE_FIELDS):
    r, v = stamp(run), stamp(run + timedelta(hours=h))
    return {'model': model, 'full_globe': True, 'mock': False, 'init_utc':r, 'valid_utc':v,
            'fields':{n:{'logical_model':model,'init_utc':r,'valid_utc':v,'lead_hours':h} for n in names}}

class SeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'series'
    def test_pin_first_success_and_report_missing(self):
        calls=[]
        def acquire(model,out,h,required_run=None):
            calls.append((h,required_run))
            if h in (0,360): raise RuntimeError('missing')
            return manifest(model,h,names=('t2m',) if h==48 else BASE_FIELDS)
        result=stage_series('ecmwf',self.out,[0,24,48,360],acquire)
        self.assertEqual(calls,[(0,None),(24,None),(48,RUN),(360,RUN)])
        self.assertFalse(result['complete'])
        self.assertEqual(result['leads']['48']['missing_fields'],['mslp','z500'])
        self.assertEqual(result['leads']['360']['status'],'unavailable')
    def test_different_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'provenance mismatch'):
            stage_series('gfs',self.out,[24],lambda m,o,h,required_run: manifest(m,h,RUN-timedelta(hours=6)),RUN)
        self.assertFalse((self.out/'series.json').exists())
    def test_different_valid_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'provenance mismatch'):
            stage_series('gfs',self.out,[360],lambda m,o,h,required_run: manifest(m,354),RUN)
    def test_complete_exact_leads(self):
        r=stage_series('gfs',self.out,[24,360,384],lambda m,o,h,required_run: manifest(m,h),RUN)
        self.assertTrue(r['complete'])
        self.assertTrue((self.out/'series.json').is_file())
    def test_duplicate_leads_rejected(self):
        with self.assertRaises(ValueError):
            stage_series('gfs',self.out,[24,24],None)
    def test_no_overwrite(self):
        self.out.mkdir()
        (self.out/'old').touch()
        with self.assertRaisesRegex(ValueError,'must be empty'):
            stage_series('gfs',self.out,[24],None)
    def test_field_wrong_lead_rejected(self):
        def acquire(m,o,h,required_run):
            result=manifest(m,h)
            result['fields']['t2m']['lead_hours']=h-6
            return result
        with self.assertRaisesRegex(ValueError,'field provenance mismatch'):
            stage_series('gfs',self.out,[24],acquire,RUN)

if __name__=='__main__': unittest.main()
