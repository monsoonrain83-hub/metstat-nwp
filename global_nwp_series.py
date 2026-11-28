"""Stage exact global forecast leads from a single initialization.
This is a review-only inventory; never writes to production or world-data.
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

BASE_FIELDS = ('mslp', 't2m', 'z500')


def utc(text):
    if not isinstance(text, str) or not text.endswith('Z'):
        raise ValueError('expected explicit UTC timestamp')
    return datetime.fromisoformat(text[:-1] + '+00:00')


def stage_series(model, out, leads, acquire, cycle=None):
    leads = list(leads)
    if not leads or any(type(h) is not int or not 0 <= h <= 384 for h in leads) or len(set(leads)) != len(leads):
        raise ValueError('unique integer leads in 0..384 required')
    if cycle is not None and (cycle.tzinfo is None or cycle.utcoffset() is None):
        raise ValueError('cycle must be timezone-aware')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('series output must be empty; do not overwrite a prior cycle')
    pinned = cycle
    inventory = {}
    for h in leads:
        folder = out / f'f{h:03d}'
        try:
            man = acquire(model, folder, h, required_run=pinned)
        except RuntimeError:
            inventory[str(h)] = {'status': 'unavailable', 'reason': 'source acquisition failed or exact lead unavailable',
                                 'available_fields': [], 'missing_fields': list(BASE_FIELDS)}
            continue
        run = utc(man['init_utc'])
        valid = utc(man['valid_utc'])
        if (man.get('model') != model or man.get('full_globe') is not True or man.get('mock') is not False
                or (pinned is not None and run != pinned) or valid != run + timedelta(hours=h)):
            raise ValueError('series provenance mismatch')
        fields = man.get('fields')
        if not isinstance(fields, dict) or not fields or set(fields) - set(BASE_FIELDS):
            raise ValueError('unexpected series fields')
        for name, field in fields.items():
            if (field.get('logical_model') != model or field.get('init_utc') != man['init_utc']
                    or field.get('valid_utc') != man['valid_utc'] or field.get('lead_hours') != h):
                raise ValueError('series field provenance mismatch')
        pinned = run
        missing = sorted(set(BASE_FIELDS) - set(fields))
        inventory[str(h)] = {'status': 'partial' if missing else 'available',
                             'manifest': f'f{h:03d}/manifest.json',
                             'available_fields': sorted(fields), 'missing_fields': missing}
    result = {'schema': 1, 'model': model, 'scope': 'review-only baseline global raster inventory',
              'init_utc': pinned.isoformat().replace('+00:00', 'Z') if pinned else None,
              'requested_leads': leads, 'leads': inventory,
              'complete': all(v['status'] == 'available' for v in inventory.values())}
    temp = out / 'series.json.tmp'
    temp.write_text(json.dumps(result, indent=2), encoding='utf-8')
    temp.replace(out / 'series.json')
    return result


def main():
    from global_nwp_stage import acquire, DOMAINS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=sorted(DOMAINS), required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--leads', type=int, nargs='+', required=True)
    p.add_argument('--init-utc', type=utc)
    a = p.parse_args()
    result = stage_series(a.model, a.out, a.leads, acquire, a.init_utc)
    print(json.dumps(result), flush=True)
    if not result['complete']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
