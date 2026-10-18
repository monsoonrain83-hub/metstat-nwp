# -*- coding: utf-8 -*-
"""MetStat MultiModel (مالتی مدل MetStat): ترکیب وزنی نقشه‌های مدل‌ها + نقشه‌های بیشینه/کمینه.

با `nwp_maps.py --mm DIR` فعال می‌شود. هر مدل پس از ساخت میدان (که اصلاح ارتفاعی خودش را دارد) آن را با `sink` در DIR می‌نویسد؛
`tick` هر چند ثانیه می‌بیند برای کدام (پارامتر، منطقه، چرخه، ساعت اعتبار) همهٔ مدل‌های لازم آماده‌اند، وزن می‌دهد، با همان `render`
می‌کشد و به‌عنوان مدل «mm» آپلود می‌کند. ساعت اول به‌محض کامل‌شدن همهٔ مدل‌ها بالا می‌آید و بعد به ترتیب.
"""
import os, sys, time, threading, json
import numpy as np
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mm_weights as W

UTC = timezone.utc
MM_ID = 'mm'
MM_NAME = 'MetStat MultiModel'
MM_LABEL = 'MetStat MultiModel'
MM_FA = 'مالتی مدل MetStat'
SOURCES = ('ecmwf9', 'ecmwf', 'gfs', 'gfs25', 'icon', 'gem', 'ukmo', 'arpege')   # مدل‌هایی که میدانشان ذخیره می‌شود
WAIT_MAX = 45 * 60            # اگر پس از ۴۵ دقیقه از اولین میدان، منبعی نیامد، با همان‌هایی که هستند ساخته می‌شود
MINMAX_FA = {'max': 'بیشینهٔ مدل‌ها', 'min': 'کمینهٔ مدل‌ها'}
MINMAX_EN = {'max': 'model maximum', 'min': 'model minimum'}
SC_VOTE = ('sigwx',)           # پارامترهای رده‌ای: رأی وزنی به‌جای میانگین


def mm_extend_params(PARAMS):
    """پارامترهایی که در nwp_maps فقط برای ECMWF بودند، برای بقیهٔ مدل‌های مالتی‌مدل هم فعال می‌شود (اگر متغیرش در Open-Meteo باشد، میدان ساخته می‌شود؛ وگرنه فقط از ترکیب حذف می‌شود)."""
    allm = ['ecmwf', 'gfs', 'gfs25', 'icon', 'ukmo', 'arpege', 'gem']
    for pid in ('t2m', 'tmax', 'tmin', 'rh', 'pw', 'gust', 'sfc'):
        if pid in PARAMS: PARAMS[pid]['models'] = list(dict.fromkeys(list(PARAMS[pid]['models']) + allm))
    up = ['ecmwf', 'icon', 'ukmo', 'arpege', 'gfs25']          # مدل‌هایی که ترازهای فشاری‌شان در خواندن اصلی هست
    for pid in ('z850', 'z700', 'z500', 'w500', 'w300'):
        if pid in PARAMS: PARAMS[pid]['models'] = list(dict.fromkeys(list(PARAMS[pid]['models']) + up))


class MMCombiner:
    def __init__(s, nm, eng, d):
        s.nm, s.eng, s.dir = nm, eng, d; os.makedirs(d, exist_ok=True)
        s.lock = threading.Lock(); s.sec_hd = {}; s.idx = {}; s.prog = {}; s.first = {}; s.done = set(); s.have = {}; s.begun = set(); s.n = 0
        s.model = dict(name=MM_NAME, label=MM_LABEL, prov='NWP centres')
        s.pmm = s.build_params(); s.t_log = time.time(); s.cnt = {}
        nm_ = nm; nm_.log(f'مالتی‌مدل MetStat فعال است: {len(s.pmm)} پارامتر؛ میدان‌ها در {d}')

    # ---- تعریف پارامترهای مالتی‌مدل (شامل بیشینه/کمینه)
    def build_params(s):
        nm = s.nm; out = {}
        for pid, P in nm.PARAMS.items():
            if P.get('me_only') or P.get('raw'): continue
            if s.grp(pid) is None: continue
            if len([m for m in P['models'] if m in W.MM_MODELS or m in ('ecmwf9', 'gfs25')]) < 2: continue
            out[pid] = P
        k0 = max(P['ord'] for P in nm.PARAMS.values()) + 1
        for i, (pid, kinds) in enumerate(W.MINMAX.items()):
            if pid not in out: continue
            for kd in kinds:
                P = dict(out[pid], fa=f"{out[pid]['fa']} — {MINMAX_FA[kd]}", en=f"{out[pid]['en']} — {MINMAX_EN[kd]}", ord=k0 + 2 * i + (kd == 'min'), mmk=kd, base=pid, alt='')
                out[f'{pid}m{"x" if kd == "max" else "n"}'] = P
        for pid, P in out.items(): P.setdefault('mmk', 'w'); P.setdefault('base', pid)
        return out

    def grp(s, pid):
        P = s.nm.PARAMS.get(pid) or {}
        return W.HAZ_GROUP.get(P.get('haz')) if P.get('kind') == 'sec' else W.group_of(pid)

    # ---- ورودی از Engine
    def hz(s, src, run):
        h = s.nm.MODELS[src]['hz']; return h[run.strftime('%H')] if isinstance(h, dict) else h

    def sink(s, mkey, rk, pid, run, vt, field, extra):
        if mkey not in SOURCES or run.hour not in (0, 12) or pid not in s.nm.PARAMS or pid not in s.pmm: return      # فقط پارامترهای مالتی‌مدل (بدون گروه وزنی مثل w10 رد می‌شوند)
        if field is None: return
        p = os.path.join(s.dir, rk, pid, f'{run:%Y%m%d%H}'); os.makedirs(p, exist_ok=True)
        path = os.path.join(p, f'{mkey}_{vt:%Y%m%d%H}.npz'); tmp = path + '.tmp.npz'
        z = dict(f=np.asarray(field, np.float32))
        if extra.get('cont') is not None: z['c'] = np.asarray(extra['cont'], np.float32); z['cl'] = np.asarray(extra.get('cont_lvls', []), np.float32); z['cf'] = np.array(str(extra.get('cont_fmt', '%d')))
        if extra.get('barbs') is not None: z['bu'], z['bv'] = (np.asarray(a, np.float32) for a in extra['barbs'])
        if extra.get('note'): z['note'] = np.array(str(extra['note']))
        np.savez(tmp, **z); os.replace(tmp, path)
        with s.lock:
            k = (rk, pid, run, vt); s.idx.setdefault(k, {})[mkey] = path; s.first.setdefault(k, time.time())

    def progress(s, mkey, run, vt):
        with s.lock: s.prog[(mkey, run)] = max(vt, s.prog.get((mkey, run), vt))

    # ---- آمادگی یک کلید
    def decide(s, k, final=False):
        """None: هنوز صبر؛ وگرنه {slot: src} منابع انتخاب‌شده."""
        rk, pid, run, vt = k; nm = s.nm; P = nm.PARAMS.get(pid)
        if not P: return {}
        lead = int(round((vt - run).total_seconds() / 3600)); have = s.idx.get(k, {}); pick = {}
        timed = final or time.time() - s.first.get(k, time.time()) > WAIT_MAX
        for slot in W.MM_MODELS:
            cands = [m for m in W.SLOT_SRC.get(slot, (slot,)) if m in P['models'] and m in nm.MODELS and lead <= s.hz(m, run)]
            if not cands: continue
            chosen = None; pending = False
            for m in cands:
                if m in have: chosen = m; break
                pr = s.prog.get((m, run))
                if pr is None or pr < vt: pending = True                # منبع برتر هنوز به این گام نرسیده
            if pending and not timed: return None
            if chosen: pick[slot] = chosen
        return pick

    # ---- ترکیب
    def load(s, path):
        z = np.load(path, allow_pickle=False); o = {k: z[k] for k in z.files}; return o

    def combine(s, kind, wts, arrs, pid):
        """arrs: {slot: میدان}. kind: w/max/min."""
        slots = list(arrs); A = np.stack([arrs[m] for m in slots]).astype(np.float64); V = ~np.isnan(A)
        if kind == 'max': return np.where(V.any(0), np.nanmax(np.where(V, A, -np.inf), 0), np.nan).astype(np.float32)
        if kind == 'min': return np.where(V.any(0), np.nanmin(np.where(V, A, np.inf), 0), np.nan).astype(np.float32)
        w = np.array([wts[m] for m in slots])[:, None, None] * V; ws = w.sum(0)
        if pid in SC_VOTE:
            cls = np.rint(np.nan_to_num(A, nan=-1)).astype(int); out = np.full(A.shape[1:], np.nan)
            best = np.full(A.shape[1:], -1.0)
            for c in np.unique(cls[cls >= 0]):
                sc_ = (w * (cls == c)).sum(0)
                m = sc_ > best; out = np.where(m, c, out); best = np.where(m, sc_, best)
            return out.astype(np.float32)
        return np.where(ws > 0, (np.nan_to_num(A) * w).sum(0) / np.maximum(ws, 1e-12), np.nan).astype(np.float32)

    def begin(s, run):
        rid = f'{run:%Y%m%d%H}'
        if rid in s.begun: return
        nm = s.nm; up = s.eng.up
        params = {k: dict(fa=v['fa'], unit=v['unit'], cat=v['cat'], o=v['ord'], sc=(v.get('me') or {}).get('sc', v['sc']), mu=(v.get('me') or {}).get('unit', v['unit']),
                          alt=v.get('alt', ''), me=int(bool(v.get('me_only'))), ln=int(bool(v.get('cont') or v.get('barbs') or v.get('ln')))) for k, v in s.pmm.items()}
        r = up.call('begin', js={'model': MM_ID, 'run': rid, 'name': MM_NAME, 'label': MM_LABEL, 'fa': MM_FA,
                                 'info': dict(tclass='daily', res='multi', cyc='00/12', prov=s.model['prov']),
                                 'cats': [dict(id=i, fa=fa, o=o) for i, fa, o in nm.CATS], 'scales': nm.scales_payload(), 'params': params})
        s.have[rid] = set(r.get('have', [])); s.begun.add(rid); nm.log(f'▶ {MM_NAME} اجرای {rid}: {len(params)} پارامتر، {len(s.have[rid])} نقشه از قبل روی هاست')

    def tick(s, final=False):
        nm = s.nm; made = {}; ks = []
        with s.lock: ks = sorted(s.idx, key=lambda k: (k[2], k[3], k[0], str(k[1]).startswith('warn'), k[1]))      # «هشدار ترکیبی» آخر تا همهٔ خطرهای همان ساعت آماده باشند
        for k in ks:
            if k in s.done: continue
            rk, pid, run, vt = k; pick = s.decide(k, final)
            if pick is None: continue
            s.done.add(k)
            try:
                made[(run)] = made.get(run, 0) + s.make(k, pick)
            except Exception as e:
                import traceback; traceback.print_exc(); nm.log(f'  ! {MM_NAME} {pid} {rk} {vt:%Y%m%d%H}: {e}')
            for p in s.idx.get(k, {}).values():
                try: os.remove(p)
                except OSError: pass
        if time.time() - s.t_log > 600:                       # گزارش وضعیت برای عیب‌یابی
            s.t_log = time.time(); pend = [k for k in ks if k not in s.done]
            nm.log(f'مالتی‌مدل: {len(s.done)} ترکیب انجام، {len(pend)} در انتظار؛ پیشرفت مدل‌ها: ' + ', '.join(f'{m}@{v:%d%H}' for (m, r), v in sorted(s.prog.items())) + ' | ساخته‌شده: بارش ' + str(sum(v for k, v in s.cnt.items() if k[:1] == 'p' and k[:2] != 'pw')) + '، برف ' + str(sum(v for k, v in s.cnt.items() if k[:1] == 's' and k[:2] not in ('sf', 'sh', 'si', 'sw'))) + '، کل ' + str(sum(s.cnt.values())))
        s.eng.up.wait()
        for run, n in made.items():
            if n: s.eng.up.call('sync', js={'model': MM_ID, 'run': f'{run:%Y%m%d%H}'}); nm.log(f'■ {MM_NAME} {run:%Y%m%d%H}: +{n} نقشه')

    def make(s, k, pick):
        nm = s.nm; rk, pid, run, vt = k; P0 = nm.PARAMS[pid]; lead = int(round((vt - run).total_seconds() / 3600))
        if len(pick) < 2: return 0
        s.begin(run); rid = f'{run:%Y%m%d%H}'; R = s.eng.regions[rk]; D = {m: s.load(s.idx[k][src]) for m, src in pick.items()}
        wts, season, _ = W.weights(s.grp(pid), vt, list(pick.values()))
        if not wts: return 0
        made = 0
        for mpid, P in s.pmm.items():
            if P['base'] != pid: continue
            fname = f'{rk}/{mpid}_{vt:%Y%m%d%H}.' + ('webp' if rk == 'me' else 'png')
            if fname in s.have.get(rid, set()): continue
            kind = P['mmk']; DD = {m: d for m, d in D.items() if kind != 'w' or m in wts}; arrs = {m: d['f'] for m, d in DD.items()}
            field = s.combine(kind, wts, arrs, pid)
            sec = P0['kind'] == 'sec'
            if sec: field = np.where(np.isnan(field), np.nan, np.floor(field + 0.5)).astype(np.float32)          # رده‌ای: گرد به نزدیک‌ترین رده
            if sec:
                hk = (rk, run, vt, P0['win']); hd = s.sec_hd.setdefault(hk, {}); hd[P0['haz']] = field
                if len(s.sec_hd) > 400:
                    for _k in sorted(s.sec_hd, key=lambda t: t[2])[:100]: s.sec_hd.pop(_k, None)
            if P0.get('skip_empty') and not (np.nanmax(field) >= 0.1): continue
            extra = {}
            if kind == 'w':
                d0 = next(iter(DD.values()))
                if all('c' in d for d in DD.values()):
                    extra['cont'] = s.combine('w', wts, {m: d['c'] for m, d in DD.items()}, 'x'); extra['cont_lvls'] = d0['cl']; extra['cont_fmt'] = str(d0['cf'])
                if all('bu' in d for d in DD.values()):
                    extra['barbs'] = (s.combine('w', wts, {m: d['bu'] for m, d in DD.items()}, 'x'), s.combine('w', wts, {m: d['bv'] for m, d in DD.items()}, 'x'))
            used = {m: pick[m] for m in (wts if kind == 'w' else pick)}
            wstr = ','.join((f'{src}:{round(wts[m] * 100)}' if kind == 'w' else src) for m, src in used.items())
            cap_en = (W.caption(wts, 'en') if kind == 'w' else ('Model ' + ('maximum' if kind == 'max' else 'minimum') + ' of: ' + ', '.join(W.EN[m] for m in used)))
            mix = {src: round(wts[m] * 100) for m, src in used.items()} if kind == 'w' else {src: 0 for m, src in used.items()}
            sc = nm.styles.SC[P['sc']]
            mk = dict(v=1, p=mpid, m=MM_NAME, r=rid, t=f'{vt:%Y%m%d%H}', g=rk, h=P0.get('h', 0) if P0['kind'] == 'win' else (24 if P0['kind'] == 'day' else 0),
                      s=P['sc'], u=P['unit'], n=P['fa'], e=nm.edges_txt(sc['edges']), mm=mix)
            if P0.get('wv'): mk['wv'] = P0['wv']
            if rk == 'me':
                png, lines = nm.render_me(R, field, (P.get('me') or {}).get('sc', P['sc']), **{a: b for a, b in extra.items() if a in ('cont', 'cont_lvls', 'cont_fmt', 'barbs')})
                s.eng.up.put(MM_ID, rid, fname, png, dict(r=rk, m=MM_ID, p=mpid, s=lead, v=f'{vt:%Y%m%d%H}', w=wstr))
                if lines: s.eng.up.put(MM_ID, rid, f'me/{mpid}L_{vt:%Y%m%d%H}.webp', lines, dict(r=rk, m=MM_ID, p=mpid + 'L', s=lead, v=f'{vt:%Y%m%d%H}'))
            else:
                title = P['en']
                if P0['kind'] == 'win' and P0['h'] == 0: title += f', {lead}h'
                note = 'Elevation-adjusted per model before blending'
                if sec:
                    icons = None
                    if P0['haz'] == 'warn':
                        try: icons = nm.warn_icons.pick(s.sec_hd.get((rk, run, vt, P0['win']), {}), np.array(R.overlay), nm.FX0, nm.FY0)
                        except Exception as e_: nm.log(f'  ! آیکن هشدار مالتی‌مدل: {type(e_).__name__}: {e_}')
                    png = nm.render(R, field, P['sc'], title, vt, run, s.model, '', mk, caption=cap_en, note='Derived index from model fields, blended across models', icons=icons)
                else:
                    png = nm.render(R, field, P['sc'], title, vt, run, s.model, P['unit'], mk, caption=cap_en, note=note, **extra)
                s.eng.up.put(MM_ID, rid, fname, png, dict(r=rk, m=MM_ID, p=mpid, s=lead, v=f'{vt:%Y%m%d%H}', w=wstr))
            s.have.setdefault(rid, set()).add(fname); made += 1; s.cnt[mpid] = s.cnt.get(mpid, 0) + 1
        return made
