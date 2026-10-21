import numpy as np, ens_maps as E
lo=np.arange(3); la=np.arange(2); A=np.full((2,3),1e-5,np.float32)       # 1e-5 kg/m²/s ثابت
# لحظه‌ای ('fcst'): ۲۴ ساعت × ۸۶۴۰۰ × ۱e-5 = ۰٫۸۶۴ mm، ۴۵ روز = ۳۸٫۸۸
got={s:{'prate':(A,lo,la,None)} for s in range(6,24*45+1,6)}
tp=E.cfs_accum(got); assert abs(tp[24][0][0,0]-0.864)<1e-4 and abs(tp[1080][0][0,0]-38.88)<1e-2, (tp[24][0][0,0],tp[1080][0][0,0])
# میانگین ۶ ساعته (a-6..a)
got={s:{'prate':(A,lo,la,(s-6,s))} for s in range(6,24*45+1,6)}
tp=E.cfs_accum(got); assert abs(tp[1080][0][0,0]-38.88)<1e-2
# میانگین از ابتدا (0..s)
got={s:{'prate':(A,lo,la,(0,s))} for s in range(6,24*45+1,6)}
tp=E.cfs_accum(got); assert abs(tp[1080][0][0,0]-38.88)<1e-2
# گام گمشده (۱۲ ساعت فاصله) → پر می‌شود
got={s:{'prate':(A,lo,la,None)} for s in range(6,24*3+1,6) if s!=30}
tp=E.cfs_accum(got); assert abs(tp[72][0][0,0]-2.592)<1e-3
print('OK')
