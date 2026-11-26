"""Guard existing elevation correction for every operational NWP source."""
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import nwp_maps as nm

class PrecipElevationContract(unittest.TestCase):
    def test_all_current_sources_apply_existing_factor_once(self):
        models=('ecmwf','ecmwf9','gfs','gfs25','icon','ukmo','gem')
        run=datetime(2026,11,26,tzinfo=timezone.utc)
        raw=np.array([[0.,4.],[8.,np.nan]],np.float32)
        factor=np.array([[2.,1.5],[.5,1.]],np.float32)
        for model in models:
            for pid in ('p24','pacc'):
                with self.subTest(model=model,pid=pid):
                    P=nm.PARAMS[pid]
                    self.assertIn(model,P['models'])
                    st=SimpleNamespace(model=model,run=run,srcs={'main':object()},hist={})
                    R=SimpleNamespace(key='fars')
                    engine=SimpleNamespace(blend=Mock(return_value=raw.copy()),precip_factor=Mock(return_value=factor))
                    v,_=nm.Engine.make(engine,P,pid,st,{},R,run+timedelta(hours=48),48,6)
                    np.testing.assert_allclose(v,raw*factor,equal_nan=True)
                    engine.precip_factor.assert_called_once_with(st,R)
                    engine.precip_factor.reset_mock()
                    v,_=nm.Engine.make(engine,dict(P,raw=True),pid,st,{},R,run+timedelta(hours=48),48,6)
                    np.testing.assert_allclose(v,raw,equal_nan=True)
                    engine.precip_factor.assert_not_called()
    def test_existing_calibration_unchanged(self):
        self.assertEqual((nm.PREC_CHI,nm.PREC_CEIL,nm.PREC_DZMAX,nm.PREC_FMIN,nm.PREC_FMAX),(.27,2500.,1.5,.5,2.))

if __name__=='__main__': unittest.main()
