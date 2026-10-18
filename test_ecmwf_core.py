import numpy as np, datetime as dt, ecmwf_indices as E
rng=np.random.default_rng(1); mask=E.domain_mask(E.SPEC['nao'][4]); la,lo=np.meshgrid(E.LATS,E.LONS,indexing='ij')
true=np.exp(-((la-38)**2+(lo+30)**2)/300)-np.exp(-((la-65)**2+(lo+20)**2)/300)      # دوقطبی NAO
T=360; amp=rng.normal(0,60,T); anom=amp[:,None,None]*true+rng.normal(0,5,(T,)+true.shape)
months=np.tile(np.arange(1,13),T//12)
pat=E.build_eof(anom,mask,E.SPEC['nao'][5]); w=E.weights(); a=(true*w)[mask]; a/=np.linalg.norm(a); c=float((pat[mask]*a).sum())
print('corr pattern',round(c,3)); assert c>0.97
sig=E.monthly_sigma(anom,pat,mask,months); clim=np.zeros((12,)+true.shape)
Z=np.stack([+80*true,-80*true]); idx=E.index_series(Z,[dt.date(2026,1,10)]*2,clim,pat,mask,sig); print(idx); assert idx[0]>1 and idx[1]<-1
c2=E.coarsen(np.random.rand(2,721,1440),np.linspace(90,-90,721),np.arange(0,360,.25)); print(c2.shape, np.isnan(c2[:,:29]).sum()); 
print('ok')
