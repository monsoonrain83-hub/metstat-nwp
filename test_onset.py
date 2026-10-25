import numpy as np, sys; sys.path.insert(0,'.')
import onset_methods as M
rng=np.random.default_rng(1); N=6
def synth(onset_day, end_day, wetp=.35, mean=9, N=N):
    p=np.zeros((M.T,N))
    for c in range(N):
        s=onset_day[c]; e=end_day[c]
        for t in range(M.T):
            if s<=t<=e and rng.random()<wetp: p[t,c]=rng.gamma(.8,mean)
            elif rng.random()<.01: p[t,c]=rng.gamma(.5,3)
    return p
od=np.array([70,80,95,110,120,60]); ed=np.array([250,240,230,220,200,260])   # آغاز ۷۰ تا ۱۲۰ (۹ اکتبر..۲۸ نوامبر)، پایان ~ ۸ آوریل تا ۱۶ مه
p=synth(od,ed)
for k,(f,fa,en,hasO,hasC) in M.METHODS.items():
    o,c=f(p); print(k.ljust(4), 'onset',o.tolist(),'cess',c.tolist())
print('truth onset',od.tolist(),'cess',ed.tolist())
# ویژگی‌ها: NaN ← -1
q=p.copy(); q[10,0]=np.nan; o,c=M.m_siv(q); assert o[0]==-1 and c[0]==-1
# بدون بارش ← -1
z=np.zeros((M.T,2)); 
for k,(f,*_) in M.METHODS.items():
    o,c=f(z); assert (o==-1).all() or k in ('prs',) , (k,o)
print('ok')
