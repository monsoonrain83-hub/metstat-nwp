"""Producer-first GDPS integration, with fixture-backed field readers."""
import unittest,tempfile
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from pathlib import Path
import numpy as np
import global_nwp_stage as G
import world_gem_official as GO
import nwp_source_policy as SP
from pack_global_products import verify_manifest_field

RUN=datetime(2026,11,26,12,tzinfo=timezone.utc)
VALID=RUN+timedelta(hours=24)
class OfficialFirst(unittest.TestCase):
    def test_source_bundle_and_raster_verification(self):
        # Small but geographically complete grid accepted by shared renderer.
        # Use actual official dimensions in the packaging verification test.
        a=np.broadcast_to(np.linspace(-45,40,GO.NY,dtype=np.float32)[:,None],(GO.NY,GO.NX))
        key='temperature_2m'
        fields={key:a}
        report={key:dict(status='verified',source_url=GO.field_url(RUN,VALID,key),
                         grid=[GO.NX,GO.NY],origin=[-180,-90],spacing=[.15,.15])}
        with tempfile.TemporaryDirectory() as td,patch.object(GO,'read',return_value=(fields,report)):
            path=Path(td)
            products,reason=G.official_gem_products(RUN,VALID,path,False,[])
            self.assertEqual(set(products),{'t2m'})
            row=products['t2m']
            self.assertEqual(row['distribution'],'producer')
            self.assertEqual(row['field_source_domain'],SP.ECCC_DOMAIN)
            self.assertEqual(row['source_fields'],report)
            self.assertIn('lacks',reason)
            man=G.product_manifest('gem',RUN,VALID,'cmc_gem_gdps_15km',products)
            verify_manifest_field('gem','t2m',row,man,path)
            row['source_fields'][key]['source_url']='https://example.org/unverified'
            with self.assertRaisesRegex(ValueError,'official GDPS source metadata'):
                verify_manifest_field('gem','t2m',row,man,path)
    def test_unavailable_official(self):
        with patch.object(GO,'read',side_effect=RuntimeError('test')):
            p,reason=G.official_gem_products(RUN,VALID,Path('.'),True,[])
            self.assertFalse(p)
            self.assertIn('failed',reason)
    def test_intermediary_provenance(self):
        with self.assertRaises(ValueError):
            SP.provenance('gem','cmc_gem_gdps_15km',attempted=True)
        m=SP.provenance('gem','cmc_gem_gdps_15km',attempted=True,reason='no validated product')
        self.assertTrue(m['official_attempted'])
        self.assertEqual(m['distribution'],'intermediary')
        self.assertFalse(SP.provenance('gfs','ncep_gfs013')['official_attempted'])
if __name__=='__main__':unittest.main()
