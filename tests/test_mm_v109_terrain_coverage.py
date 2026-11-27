"""Terrain-aware global QC must not count missing input as masked terrain."""
import unittest
from types import SimpleNamespace
import numpy as np
import world_convection as C
from pack_global_products import valid_coverage

def meta(valid=800,excluded=180,unknown=0,total=1000):
    return dict(finite_fraction=round(valid/total,5),coverage_basis='terrain_eligible_cells_v1',
                pressure_level_mask=[925,850,700,500],surface_pressure_basis='native surface_pressure',
                total_cells=total,terrain_excluded_cells=excluded,pressure_unknown_cells=unknown,valid_cells=valid)
class Coverage(unittest.TestCase):
    def test_physically_masked_gdi(self):
        self.assertTrue(valid_coverage('gdi',meta(),40,25))
    def test_unknown_pressure_is_missing_not_exclusion(self):
        self.assertFalse(valid_coverage('gdi',meta(valid=800,excluded=100,unknown=100),40,25))
    def test_missing_meteorology_is_not_exclusion(self):
        self.assertFalse(valid_coverage('gdi',meta(valid=700,excluded=180),40,25))
    def test_counts_and_masks_cannot_bypass_gate(self):
        for m in (meta(total=1001),meta(valid=700,excluded=301),meta(valid=800,excluded=200,unknown=1),
                  dict(meta(),finite_fraction=.95),dict(meta(),pressure_level_mask=[850]),dict(meta(),valid_cells=True)):
            self.assertFalse(valid_coverage('gdi',m,40,25))
        self.assertFalse(valid_coverage('cape',meta(),40,25))
        self.assertFalse(valid_coverage('ki',dict(finite_fraction=.99,pressure_level_mask=[850]),40,25))
    def test_unmasked_gate_unchanged(self):
        self.assertFalse(valid_coverage('cape',dict(finite_fraction=.89),40,25))
        self.assertTrue(valid_coverage('cape',dict(finite_fraction=.90),40,25))
        self.assertFalse(valid_coverage('sigwx',dict(finite_fraction=float('nan')),40,25))
    def test_actual_derivation_counts(self):
        def a(v):return np.full((10,10),v,np.float32)
        data={'surface_pressure':a(1010)}
        data['surface_pressure'][0,:]=800
        data['surface_pressure'][1,0]=np.nan
        for p,t in [(925,20),(850,15),(700,5),(500,-20)]:
            data[f'temperature_{p}hPa']=a(t)
            data[f'relative_humidity_{p}hPa']=a(70)
        data['relative_humidity_700hPa'][2,0]=np.nan
        v,m=C.derive('gfs',SimpleNamespace(),data,lambda s,v:v,{'ki'})['ki']
        self.assertEqual((m['total_cells'],m['terrain_excluded_cells'],m['pressure_unknown_cells'],m['valid_cells']),(100,10,1,88))
        self.assertTrue(valid_coverage('ki',dict(m,finite_fraction=.88),10,10))
        self.assertTrue(np.isnan(v[0,:]).all())
        self.assertTrue(np.isnan(v[1,0]) and np.isnan(v[2,0]))
if __name__=='__main__':unittest.main()
