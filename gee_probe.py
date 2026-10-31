"""Earth Engine connection probe (service account). Prints only non-secret info."""
import json, os, sys
import ee

key = os.environ.get("GEE_SERVICE_ACCOUNT_KEY", "").strip()
proj = os.environ.get("GEE_PROJECT", "").strip()
acct = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
if not key or not proj:
    sys.exit("ERROR: GEE_SERVICE_ACCOUNT_KEY or GEE_PROJECT secret is empty")
try:
    info = json.loads(key)
except Exception as e:
    sys.exit("ERROR: key is not valid JSON (paste the whole file): %s" % type(e).__name__)
email = info.get("client_email", "")
print("key client_email:", email)
print("key project_id  :", info.get("project_id"))
print("GEE_PROJECT     :", proj)
if acct and acct != email:
    print("WARN: GEE_SERVICE_ACCOUNT differs from key client_email; using key's")
creds = ee.ServiceAccountCredentials(email, key_data=key)
ee.Initialize(creds, project=proj)
print("Initialize OK")
img = ee.Image("KNTU/LiDARLab/IranLandCover/V1")
print("KNTU bands:", img.bandNames().getInfo())
pt = ee.Geometry.Point([51.389, 35.689])  # Tehran
v = img.sample(pt, 10).first().get("classification").getInfo()
print("KNTU class at Tehran (expect 1=Urban):", v)
