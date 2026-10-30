# r127 probe5: GFS رسمی NOAA (AWS S3 noaa-gfs-bdp-pds + NOMADS) در برابر Open-Meteo: زمان انتشار و ساختار
import re, json, datetime as dt, requests
UTC = dt.timezone.utc; S = requests.Session(); S.headers['User-Agent'] = 'metstat-probe/1.0'
now = dt.datetime.now(UTC); print('now', now.isoformat())
def head(u):
    try:
        r = S.head(u, timeout=40, allow_redirects=True); return r.status_code, r.headers.get('Content-Length'), r.headers.get('Last-Modified')
    except Exception as e: return 'ERR', str(e)[:80], None
print('\n## NOAA AWS S3 (آخرین ران‌ها)')
for back in range(0, 30, 6):
    t = (now - dt.timedelta(hours=back)).replace(minute=0, second=0, microsecond=0); run = t.replace(hour=(t.hour // 6) * 6)
    b = f'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.0p25.f'
    print(run.isoformat(), {f: head(b + f'{f:03d}') for f in (0, 3, 24, 120, 240, 384)})
    print('   idx f000:', head(b + '000.idx'))
print('\n## NOMADS')
for u in ('https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/', 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl'):
    try: r = S.get(u, timeout=40); print(u, r.status_code, re.findall(r'href="(gfs\.\d{8}/)"', r.text)[-3:])
    except Exception as e: print(u, 'ERR', str(e)[:100])
print('\n## نمونهٔ idx')
try:
    run = (now - dt.timedelta(hours=8)).replace(minute=0, second=0, microsecond=0); run = run.replace(hour=(run.hour // 6) * 6)
    r = S.get(f'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.0p25.f006.idx', timeout=40)
    L = r.text.splitlines(); print(len(L), 'خط'); [print('  ', x) for x in L if re.search(r':(APCP|TMP:2 m|PRMSL|RH:2 m|UGRD:10 m|VGRD:10 m|GUST|CAPE:surface|HGT:500 mb|HGT:850 mb|PWAT|CSNOW|WEASD)', x)][:0]
    [print('  ', x) for x in L if re.search(r':(APCP:surface|TMP:2 m|PRMSL|RH:2 m|UGRD:10 m|VGRD:10 m|GUST|CAPE:surface|HGT:500 mb|HGT:850 mb|PWAT)', x)]
except Exception as e: print('ERR', e)
print('\n## Open-Meteo (مقایسه)')
try:
    import s3fs; fs = s3fs.S3FileSystem(anon=True)
    for f in ('in-progress.json', 'latest.json'):
        try: print(f, fs.cat_file(f'openmeteo/data_spatial/ncep_gfs025/{f}').decode()[:600])
        except Exception as e: print(f, 'ERR', str(e)[:100])
except Exception as e: print('s3fs', e)
