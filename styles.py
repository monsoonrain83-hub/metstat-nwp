# -*- coding: utf-8 -*-
"""MetStat — رنگ‌بندی و اعداد نوار رنگ نقشه‌های مدل (برگرفته از weather.us؛ رنگ‌ها گسسته، بدون رنگ واسطه)."""
import json, os
INF = float('inf')
_P = json.load(open(os.path.join(os.path.dirname(__file__), 'palettes.json')))
WU = _P['wu_pal']

def rng(a, b, s):
    out, v = [], a
    while v <= b + 1e-9:
        out.append(round(v, 2)); v += s
    return out

PRECIP = {
    'acc': dict(colors=WU, edges=[0, 0.1, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100, 125, 150, 175, 200, 250, 300, 400, 500, INF]),
    'h24': dict(colors=[WU[0]] + WU[2:], edges=[0, 0.1, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 125, 150, 200, 300, INF]),
    'h1':  dict(colors=[WU[0]] + WU[2:], edges=[0, 0.1, 0.2, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20, 24, 30, 40, 50, 60, 80, 100, 125, INF]),
}
T_EDGES = [-INF, -38, -36, -34, -32] + list(range(-30, 37)) + [37.33, 38.67, 40, 41.33, 42.67, 44, 46, 48, 50, INF]
SIG_COLORS = ['#fdf733', '#c1bc29', '#43ff43', '#34c134', '#008200', '#8c8c8c', '#fd5fff', '#ba1abc',
              '#ffc189', '#ff973a', '#47f0ff', '#478cff', '#3568bd', '#ff4343', '#c80000']
SIG_NAMES = ['Fog', 'Fog frz', 'Rain lt', 'Rain mod', 'Rain hvy', 'TS near', 'TS', 'TS svr', 'Mix lt', 'Mix hvy',
             'Snow lt', 'Snow mod', 'Snow hvy', 'Ice lt', 'Ice hvy']
WIND_SFC = [0, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 200, INF]
WIND_UP = [0, 20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 350, INF]
GUST = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 140, 160, 180, 200, INF]
RH_E = [-INF, 1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99, 100, INF]

SC = {
    'temp':  dict(colors=_P['wu_temp'], edges=T_EDGES),
    'tanom': dict(colors=_P['wu_tanom'], edges=[-INF, -15, -12, -10, -8, -6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, INF]),
    'rh':    dict(colors=_P['wu_rh'], edges=RH_E),
    'cape':  dict(colors=_P['wu_cape'], edges=[-INF, 20, 40, 100, 200, 300, 450, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2800, 3200, 3600, 4000, 4500, 5000, INF]),
    'li':    dict(colors=_P['wu_li'], edges=[-INF, -9, -8, -7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 5, 10, 20, 100, INF]),
    'ki':    dict(colors=_P['wu_ki'], edges=[-INF] + rng(8, 44, 2) + [INF]),
    'si':    dict(colors=_P['wu_ki'], edges=[-INF] + rng(-12, 24, 2) + [INF]),
    'gdi':   dict(colors=_P['wu_ki'], edges=[-INF] + rng(-20, 70, 5) + [INF]),
    'pw':    dict(colors=_P['wu_pw'], edges=[-INF] + rng(2, 50, 2) + rng(53, 80, 3) + [INF]),
    'refl':  dict(colors=_P['wu_refl'], edges=[-INF, 0, 2, 4, 6] + list(range(7, 71)) + [INF]),
    'cin':   dict(colors=_P['wu_cin'], edges=[-INF, -1000, -900, -800, -700, -600, -500, -400, -300, -200, -100, -90, -80, -70, -60, -50, -40, -30, -20, -10, -5, INF]),
    'wind':  dict(colors=_P['herbie_wind'], edges=WIND_SFC),
    'windu': dict(colors=_P['herbie_wind'], edges=WIND_UP),
    'gust':  dict(colors=_P['herbie_wind'], edges=GUST),
    'wind10': dict(colors=_P['tt_wind10'], edges=[-INF] + list(range(4, 87, 2)) + [INF]),
    'windup': dict(colors=_P['tt_windup'], edges=[-INF] + list(range(20, 211, 5)) + [220, 230, 240, 250, INF]),
    'z500a': dict(colors=_P['wx_z500a'], edges=[-INF] + list(range(-49, 49)) + [INF]),
    # انومالی پیش‌بینی‌های بلندمدت (ماهانه/فصلی): دما °C و بارش mm/day
    'lrta':  dict(colors=_P['wu_tanom'], edges=[-INF, -4, -3, -2.5, -2, -1.5, -1.25, -1, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4, INF]),
    'lrpa':  dict(colors=['#543005', '#7f4a0c', '#a3691a', '#bf8a2e', '#d6aa55', '#e6c88a', '#f0dcb3', '#f7ecd3', '#ffffff', '#d9efe8', '#b3e0d3', '#86cdbc', '#55b4a3', '#2f9a8c', '#1a7e75', '#0b6159', '#00443f'], edges=[-INF, -4, -3, -2, -1.5, -1, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, INF]),
    'sigwx': dict(colors=SIG_COLORS, edges=[k - 0.5 for k in range(16)]),
}
PRECIP['rad'] = dict(colors=['#ffffff'] + ["#29acb6", "#00cef0", "#01a0f6", "#0028f6", "#00f700", "#00df00", "#00c700", "#00af00", "#008f00", "#f3e100", "#e7b400", "#f98400", "#ff3c00", "#ff0000", "#e10000", "#c20000", "#9e0000", "#dd8cdd", "#ba50ba", "#981498"], edges=[0] + [0.1, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 50, 70, 100, 125, 150, 200, 250, 300] + [INF])   # رنگ‌های رادار dBZ برای بارش تا ۳۰۰ mm؛ صفر = سفید
# شاخص‌های ناپایداری/برش (نقشهٔ خود شاخص‌ها؛ مراحل «نقشه‌های ثانویه»)
def _sq(a, b, n=19): return [round(a + (b - a) * i / (n - 1), 3) for i in range(n)]
_KI = _P['wu_ki']
SC.update({
    'tt':   dict(colors=_KI, edges=[-INF] + _sq(36, 54) + [INF]),
    'ko':   dict(colors=_KI[::-1], edges=[-INF] + _sq(-6, 12) + [INF]),
    'shw':  dict(colors=_KI[::-1], edges=[-INF] + _sq(-9, 9) + [INF]),
    'lr':   dict(colors=_KI, edges=[-INF] + _sq(5, 9.5) + [INF]),
    'shr':  dict(colors=_KI, edges=[-INF] + _sq(0, 36) + [INF]),
    'swt':  dict(colors=_KI, edges=[-INF] + _sq(100, 460) + [INF]),
    'fzl':  dict(colors=_KI[::-1], edges=[-INF] + _sq(0, 4500) + [INF]),
    'hgz':  dict(colors=_KI, edges=[-INF] + _sq(0, 3600) + [INF]),
})
# r81: لایه‌های همدیدی/جبهه‌ای (دوقطبی: آبی منفی، قرمز مثبت؛ ۲۱ ردهٔ گسسته) و ابر همرفتی
_DIV = _P['wu_tanom']
def _sym(v): return [-INF] + [-x for x in v[::-1]] + list(v) + [INF]
SC.update({
    'vo':   dict(colors=_DIV, edges=_sym([1, 2, 4, 6, 9, 12, 16, 20, 25, 30])),          # 1e-5 s⁻¹
    'dv':   dict(colors=_DIV, edges=_sym([0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10])),           # 1e-5 s⁻¹
    'tadv': dict(colors=_DIV, edges=_sym([0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10])),           # K/6h
    'mfc':  dict(colors=_DIV[::-1], edges=_sym([1, 2, 3, 4, 6, 8, 10, 12, 15, 20])),      # g/kg/day؛ همگرایی مثبت = سبز/آبی
    'omg':  dict(colors=_DIV[::-1], edges=_sym([0.05, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0])),   # Pa/s؛ منفی (صعود) = آبی
    'dte':  dict(colors=_DIV[::-1], edges=_sym([1, 2, 3, 4, 5, 6, 8, 10, 12, 15])),       # K؛ منفی = ناپایدار
    'te':   dict(colors=_KI, edges=[-INF] + _sq(290, 362) + [INF]),
    'thw':  dict(colors=_KI, edges=[-INF] + _sq(-6, 30) + [INF]),
    'thk':  dict(colors=_P['wu_temp'][::2][:20] if len(_P['wu_temp'][::2]) >= 20 else _KI, edges=[-INF] + _sq(504, 594) + [INF]),
    'ccc':  dict(colors=['#ffffff', '#eef2f7', '#d9e2ec', '#bcccdc', '#9fb3c8', '#829ab1', '#627d98', '#486581', '#334e68', '#243b53'], edges=[-INF, 1, 10, 20, 30, 40, 50, 60, 70, 75, INF]),
})
# r126: انومالی ترازهای ۸۵۰/۷۰۰ و MSLP + ضخامت لایه‌ها (دسته‌های گسسته، بدون رنگ واسطه)
def _za(step): return [-INF] + [round((-49 + i) * step, 3) for i in range(98)] + [INF]
SC.update({
    'z850a': dict(colors=_P['wx_z500a'], edges=_za(0.5)),
    'z700a': dict(colors=_P['wx_z500a'], edges=_za(0.5)),
    'mslpa': dict(colors=_P['wx_z500a'], edges=_za(0.5)),
    'thk1000': dict(colors=_P['wu_temp'][::2][:20] if len(_P['wu_temp'][::2]) >= 20 else _KI, edges=[-INF] + _sq(504, 594) + [INF]),
    'thk8550': dict(colors=_KI, edges=[-INF] + _sq(372, 444) + [INF]),
    'thk7050': dict(colors=_KI, edges=[-INF] + _sq(234, 270) + [INF]),
    'thk8570': dict(colors=_KI, edges=[-INF] + _sq(126, 162) + [INF]),
})
for k, v in PRECIP.items(): SC['pr_' + k] = v
for k, v in SC.items():
    assert len(v['edges']) == len(v['colors']) + 1, (k, len(v['edges']), len(v['colors']))

def hex2rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
