#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit actual published model files; do not mistake a green action or a fresh 'run' for coverage."""
from collections import Counter
from datetime import datetime, timezone
import json, argparse, os, sys
from urllib.request import Request, urlopen

UTC=timezone.utc
URL='https://wtafkik.ir/online/data/manifest.json'
# Required number of actually published map files per variable in the *current* host run.
RULES={
 'ecwk':(72,{'wta':4,'wpa':4},'wk.yml'),
 'cfswk':(72,{'wta':4,'wpa':4},'wk.yml'),
 'iri':(90*24,{'tpp':2,'tpt':2},'wk.yml'),
 'ec46c':(96,{'p24':10,'ptot':10,'t2m':10},'ec46.yml'),
 'ec46m':(96,{'p24':10,'ptot':10,'t2m':10},'ec46.yml'),
 'ecmwfseas':(50*24,{'lrpa':5,'lrta':5},'seas5.yml'),
 'ecmwfseass':(50*24,{'lrpa':3,'lrta':3},'seas5.yml'),
}
def parse_run(s):
 try:return datetime.strptime(str(s),'%Y%m%d%H').replace(tzinfo=UTC)
 except ValueError:return None
def audit(man,now=None):
 now=now or datetime.now(UTC);models=man.get('models') or {};items=man.get('items') or []
 result={};flows=set()
 for m,(max_age,variables,wf) in RULES.items():
  obj=models.get(m) or {};run=obj.get('run');dt=parse_run(run)
  age=None if dt is None else round((now-dt).total_seconds()/3600,1)
  # Live host manifest v2 omits run on each item: its items list is
  # by definition for the current model run (older items go to items_prev).
  counter=Counter(x.get('p') for x in items if x.get('m')==m and (not x.get('run') or str(x.get('run'))==str(run)))
  gaps={v:[counter[v],required] for v,required in variables.items() if counter[v]<required}
  problems=[]
  if not obj:problems.append('model_missing')
  if not dt:problems.append('run_missing')
  elif age>max_age:problems.append('stale_run')
  if obj and obj.get('status')!='complete':problems.append('not_complete')
  if gaps:problems.append('products_missing')
  if problems:flows.add(wf)
  result[m]={'run':run,'status':obj.get('status','missing'),'done':obj.get('done',0),
     'age_hours':age,'variable_counts':{v:counter[v] for v in variables},
     'required_counts':variables,'gaps':gaps,'problems':problems}
 return {'checked_utc':now.isoformat(),'healthy':not flows,'models':result,
   'suggested_workflow_dispatches':sorted(flows)}
def fetch(url=URL):
 req=Request(url,headers={'Cache-Control':'no-cache','Pragma':'no-cache','User-Agent':'MetStat-model-freshness/1.0'})
 with urlopen(req,timeout=90) as f:return json.load(f)
def main():
 p=argparse.ArgumentParser();p.add_argument('--url',default=URL);p.add_argument('--report',default='model_freshness_report.json')
 a=p.parse_args()
 try:summary=audit(fetch(a.url))
 except Exception as e:
  print('MODEL_MANIFEST_FETCH_ERROR',type(e).__name__,str(e)[:300],flush=True)
  return 3
 with open(a.report,'w',encoding='utf8') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
 for model,x in summary['models'].items():
  print(f'{model}: run={x["run"]} age_h={x["age_hours"]} published={x["done"]} gaps={x["gaps"]} problems={x["problems"]}',flush=True)
 print('NEEDS_WORKFLOWS',','.join(summary['suggested_workflow_dispatches']),flush=True)
 output=os.environ.get('GITHUB_OUTPUT')
 if output:
  with open(output,'a') as f:
   print('workflow_names='+','.join(summary['suggested_workflow_dispatches']),file=f)
   print('healthy='+str(summary['healthy']).lower(),file=f)
 return 0
if __name__=='__main__':sys.exit(main())
