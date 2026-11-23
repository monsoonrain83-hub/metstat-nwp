import unittest
from datetime import datetime,timezone
from model_freshness import audit, RULES
class TestModelFreshness(unittest.TestCase):
 def sample(self):
  models={};items=[]
  for name,(age,params,wf) in RULES.items():
   models[name]={'run':'2026112100','done':sum(params.values()),'status':'complete'}
   for p,n in params.items():
    for i in range(n):items.append({'m':name,'run':'2026112100','p':p,'v':str(i)})
  return {'models':models,'items':items}
 def test_healthy_manifest(self):
  report=audit(self.sample(),datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertTrue(report['healthy'])
  self.assertEqual(report['suggested_workflow_dispatches'],[])
 def test_real_host_v2_items_have_no_run_property(self):
  s=self.sample()
  for x in s['items']:x.pop('run',None)
  result=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertTrue(result['healthy'])
  self.assertEqual(result['models']['ecwk']['variable_counts']['wta'],4)
 def test_missing_parameter_triggers_correct_workflow(self):
  s=self.sample();s['items']=[x for x in s['items'] if not (x['m']=='ecwk' and x['p']=='wpa')]
  r=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertIn('wk.yml',r['suggested_workflow_dispatches'])
  self.assertIn('wpa',r['models']['ecwk']['gaps'])
  self.assertNotIn('seas5.yml',r['suggested_workflow_dispatches'])
 def test_old_and_partial_cycles_fail(self):
  s=self.sample();s['models']['ec46c']['run']='2026100100'
  s['models']['ecmwfseas']['status']='downloading'
  r=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertIn('ec46.yml',r['suggested_workflow_dispatches'])
  self.assertIn('seas5.yml',r['suggested_workflow_dispatches'])
 def test_duplicate_records_cannot_pass_as_distinct_forecast_hours(self):
  s=self.sample()
  for x in s['items']:
   if x['m']=='ecwk' and x['p']=='wta':x['v']='2026112500'
  r=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertFalse(r['healthy'])
  self.assertEqual(r['models']['ecwk']['variable_counts']['wta'],1)
  self.assertIn('wta',r['models']['ecwk']['gaps'])
  self.assertIn('wk.yml',r['suggested_workflow_dispatches'])
 def test_missing_valid_time_is_not_a_verified_product(self):
  s=self.sample()
  for x in s['items']:
   if x['m']=='cfswk' and x['p']=='wpa':x.pop('v',None)
  r=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertEqual(r['models']['cfswk']['variable_counts']['wpa'],0)
  self.assertIn('unverifiable_forecast_time',r['models']['cfswk']['problems'])
 def test_lead_hours_supported_when_valid_time_is_absent(self):
  s=self.sample()
  for x in s['items']:
   if x['m']=='cfswk' and x['p']=='wpa':
    x['s']=int(x.pop('v'))*168
  r=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertTrue(r['healthy'])
 def test_future_dated_run_is_not_healthy(self):
  s=self.sample();s['models']['ecwk']['run']='2026120100'
  r=audit(s,datetime(2026,11,21,18,tzinfo=timezone.utc))
  self.assertIn('run_from_future',r['models']['ecwk']['problems'])
  self.assertIn('wk.yml',r['suggested_workflow_dispatches'])
if __name__=='__main__':unittest.main()
