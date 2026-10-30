# r127 probe6: ECMWF open data و UKMO (AWS Open Data) در برابر Open-Meteo — زمان انتشار و ساختار
import re, json, datetime as dt, requests
UTC = dt.timezone.utc; S = requests.Session(); S.headers['User-Agent'] = 'metstat-probe/1.0'
now = dt.datetime.now(UTC); print('now', now.isoformat())
def head(u):
    try: r = S.head(u, timeout=40, allow_redirects=True); return r.status_code, r.headers.get('Content-Length'), r.headers.get('Last-Modified')
    except Exception as e: return 'ERR', str(e)[:80], None
def ls(u, n=40):
    try:
        r = S.get(u, timeout=40); L = re.findall(r'href="([^"?/][^"]*/?)"', r.text); print('GET', u, r.status_code, len(L), L[:n]); return L
    except Exception as e: print('GET', u, 'ERR', str(e)[:80]); return []
print('\n##### ECMWF open data (data.ecmwf.int)')
for back in range(0, 36, 6):
    t = (now - dt.timedelta(hours=back)).replace(minute=0, second=0, microsecond=0); run = t.replace(hour=(t.hour // 6) * 6)
    b = f'https://data.ecmwf.int/forecasts/{run:%Y%m%d}/{run:%H}z/ifs/0p25/oper/{run:%Y%m%d%H}0000-'
    print(run.isoformat(), {h: head(b + f'{h}h-oper-fc.grib2') for h in (0, 24, 90, 144, 240)})
r0 = (now - dt.timedelta(hours=14)).replace(minute=0, second=0, microsecond=0); r0 = r0.replace(hour=(r0.hour // 12) * 12)
ls(f'https://data.ecmwf.int/forecasts/{r0:%Y%m%d}/{r0:%H}z/'); ls(f'https://data.ecmwf.int/forecasts/{r0:%Y%m%d}/{r0:%H}z/ifs/')
ls(f'https://data.ecmwf.int/forecasts/{r0:%Y%m%d}/{r0:%H}z/ifs/0p25/oper/', 12)
print('\n##### UKMO (AWS Open Data met-office-atmospheric-model-data)')
try:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    s3 = boto3.client('s3', region_name='eu-west-2', config=Config(signature_version=UNSIGNED)); B = 'met-office-atmospheric-model-data'
    r = s3.list_objects_v2(Bucket=B, Prefix='', Delimiter='/', MaxKeys=50); print('root:', [x['Prefix'] for x in r.get('CommonPrefixes', [])])
    for p in [x['Prefix'] for x in r.get('CommonPrefixes', [])]:
        if 'global' in p.lower():
            r2 = s3.list_objects_v2(Bucket=B, Prefix=p, Delimiter='/', MaxKeys=60); print(p, [x['Prefix'] for x in r2.get('CommonPrefixes', [])][-6:], [(o['Key'], o['LastModified'].isoformat()) for o in r2.get('Contents', [])][-4:])
            pref = [x['Prefix'] for x in r2.get('CommonPrefixes', [])]
            if pref:
                last = sorted(pref)[-1]; r3 = s3.list_objects_v2(Bucket=B, Prefix=last, MaxKeys=1000); C = r3.get('Contents', [])
                print('  latest folder', last, len(C), 'objs; sample:', [(o['Key'].split('/')[-1], o['Size'], o['LastModified'].isoformat()) for o in C[:3] + C[-3:]])
except Exception as e: print('boto3', type(e).__name__, e)
print('\n##### Open-Meteo')
try:
    import s3fs; fs = s3fs.S3FileSystem(anon=True)
    for d in ('ecmwf_ifs025', 'ecmwf_ifs', 'ukmo_global_deterministic_10km'):
        for f in ('latest.json',):
            try:
                j = json.loads(fs.cat_file(f'openmeteo/data_spatial/{d}/{f}')); print(d, f, 'ref', j.get('reference_time'), 'last_modified', j.get('last_modified_time'), 'n_valid', len(j.get('valid_times', [])), 'last', (j.get('valid_times') or [''])[-1], 'completed', j.get('completed'))
            except Exception as e: print(d, f, 'ERR', str(e)[:100])
except Exception as e: print('s3fs', e)
