"""Gate optional ICON and UKMO native global grids without fake regional extents."""
import unittest
from datetime import datetime, timezone
import numpy as np
import global_nwp_stage as g

class ExtraWorldCatalog(unittest.TestCase):
    def test_exact_provenance_and_model_mapping(self):
        self.assertEqual(g.DOMAINS['icon'], 'dwd_icon')
        self.assertEqual(g.DOMAINS['ukmo'], 'ukmo_global_deterministic_10km')
        self.assertEqual(g.NOMINAL_SINGLE_SOURCE['icon'], '13 km')
        self.assertEqual(g.NOMINAL_SINGLE_SOURCE['ukmo'], '10 km')
        self.assertEqual(g.NOMINAL_SINGLE_SOURCE['gem'], '15 km')
    def test_region_fakes_rejected(self):
        class Grid:
            nx=1440;ny=721;lo0=-14;la0=8;dx=0.25;dy=0.25
        with self.assertRaises(ValueError):
            g.validate_global_geometry(Grid(),np.full((721,1440),280,dtype=np.float32))
    def test_global_ukmo_geometry_provable(self):
        class Grid:
            nx=2560;ny=1920;lo0=-180;la0=-90;dx=360/2560;dy=180/1920
        a=np.full((1920,2560),1013.,dtype=np.float32)
        self.assertEqual(g.validate_global_geometry(Grid(),a).shape,a.shape)
    def test_manifest_does_not_claim_wrong_grid(self):
        dt=datetime(2026,11,23,0,tzinfo=timezone.utc)
        x=g.product_manifest('ukmo',dt,dt,g.DOMAINS['ukmo'],{'mslp':{'field_source_domain':g.DOMAINS['ukmo'],'nominal_resolution':'10 km'}})
        self.assertEqual(x['source_domain'],g.DOMAINS['ukmo'])
        self.assertEqual(x['fields']['mslp']['nominal_resolution'],'10 km')
if __name__=='__main__':unittest.main()
