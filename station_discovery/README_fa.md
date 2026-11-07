# station_discovery (حالت REVIEW)

گزارش می‌دهد؛ **هیچ‌چیز را در `data/obs/stations.json` یا دیتابیس تولید تغییر نمی‌دهد.**

## اجرا
`python station_discovery/discovery.py --registry data/obs/stations.json --atlas obs_extra_stations.csv --sources atlas,isd_awc`
(`atlas` آفلاین است؛ `isd_awc` به اینترنت نیاز دارد و روی GitHub Actions اجرا می‌شود.)

## خروجی‌ها (`data/obs/discovery/`)
- `report.md` و `summary.json`: خلاصه و پوشش استانی ایران
- `candidates.csv`: coord_conflict، possible_duplicate، new_candidate با اطمینان (high/medium/low) و ستون `decision`
- `registry_issues.csv`: WMO/ICAO تکراری، ICAO بدون WMO، بدون ارتفاع، مختصات خارج از ایران، WMOِ بدون گزارش
- `coverage_iran_by_province.csv`: ایستگاه‌های WMOدار اطلس به تفکیک استان و جاافتاده‌ها
- `obs_extra_stations.generated.csv`: فقط نامزدهای **تأییدشده**

## تأیید
در `station_discovery/approvals.csv` ردیف `wmo,decision,note` بنویسید (`accept` یا `reject`). نامزدِ accept شده به `obs_extra_stations.generated.csv` می‌رود؛ آن را خودتان به `obs_extra_stations.csv` اضافه کنید.

## قواعد تطبیق
فقط شمارهٔ WMO/ICAO و فاصله؛ هیچ‌وقت شباهت نام. فاصلهٔ ≤ ۱۰ km برای یک WMO = match؛ بیشتر = coord_conflict. نامزد جدیدِ کمتر از ۳ km از ایستگاه دیگر = possible_duplicate.
کشورها با `--countries` (کدهای FIPS ISD) قابل تنظیم است؛ منطق اصلی تغییر نمی‌کند.
