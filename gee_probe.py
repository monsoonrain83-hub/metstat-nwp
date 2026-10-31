"""Earth Engine connection probe (service account). Prints only non-secret info."""
import json, os, sys, traceback
import ee

def note(level, msg):
    # GitHub annotations are readable through the API even when logs are not
    print("::%s title=GEE probe::%s" % (level, str(msg).replace("\n", " ")[:900]))

def fatal(msg):
    note("error", msg)
    sys.exit(1)

key = os.environ.get("GEE_SERVICE_ACCOUNT_KEY", "").strip()
proj = os.environ.get("GEE_PROJECT", "").strip()
acct = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
if not key or not proj:
    fatal("secret GEE_SERVICE_ACCOUNT_KEY or GEE_PROJECT is empty")
try:
    info = json.loads(key)
except Exception as e:
    fatal("key is not valid JSON (paste the whole file): %s" % type(e).__name__)
email = info.get("client_email", "")
try:
    note("notice","key client_email: %s | key project_id: %s | GEE_PROJECT: %s" % (email, info.get("project_id"), proj))
    if acct and acct != email:
        print("WARN: GEE_SERVICE_ACCOUNT differs from key client_email; using key's")
    creds = ee.ServiceAccountCredentials(email, key_data=key)
    ee.Initialize(creds, project=proj)
    note("notice","Initialize OK")
    img = ee.Image("KNTU/LiDARLab/IranLandCover/V1")
    note("notice","KNTU bands: %s" % img.bandNames().getInfo())
    pt = ee.Geometry.Point([51.389, 35.689])  # Tehran
    v = img.sample(pt, 10).first().get("classification").getInfo()
    note("notice","KNTU class at Tehran (expect 1=Urban): %s" % v)

except Exception as e:
    fatal("%s: %s" % (type(e).__name__, e))
