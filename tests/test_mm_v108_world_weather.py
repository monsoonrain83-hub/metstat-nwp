"""V108 strict interval, weather classification and clear/missing tests."""
import unittest,tempfile,hashlib
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path
import numpy as np
from PIL import Image
import global_nwp_stage as G
import world_significant_weather as W
import nwp_maps as N
from pack_global_products import verify_manifest_field

RUN=datetime(2026,11,26,12,tzinfo=timezone.utc)
def t(h):return RUN+timedelta(hours=h)
def a(v):return np.full((2,3),v,np.float32)
def grid(s,v):
    if not isinstance(v,np.ndarray) or v.shape!=(2,3):raise ValueError('grid')
    return v
def source(hours=(0,1,2,3,6,9),run=RUN,completed=True):
    return SimpleNamespace(dom='ecmwf_ifs025',exists=lambda r,v:r==RUN,
       jget=lambda key:dict(reference_time=run.isoformat(),completed=completed,
                             valid_times=[(run+timedelta(hours=h)).isoformat() for h in hours]))
def data():
    return dict(precipitation=np.array([[0.,3.,12.],[np.nan,0.,.6]],np.float32),
                snowfall_water_equivalent=a(0),temperature_2m=a(20),
                relative_humidity_2m=a(60),cape=a(900),
                wind_u_component_10m=a(4),wind_v_component_10m=a(0))
class WeatherTests(unittest.TestCase):
    def test_exact_native_variable_steps(self):
        s=source()
        self.assertEqual(W.completed_interval(s,RUN,t(3),G.parse_meta_utc),(t(2),t(3)))
        self.assertEqual(W.completed_interval(s,RUN,t(6),G.parse_meta_utc),(t(3),t(6)))
    def test_wrong_or_partial_run_rejected(self):
        for s in (source(run=t(-6)),source(completed=False),source(hours=(0,2,6)),source(hours=(1,2,3))):
            self.assertIsNone(W.completed_interval(s,RUN,t(3),G.parse_meta_utc))
        self.assertIsNone(W.completed_interval(source(),RUN,RUN,G.parse_meta_utc))
    def test_missing_predecessor(self):
        s=source();s.exists=lambda r,v:False
        self.assertIsNone(W.completed_interval(s,RUN,t(6),G.parse_meta_utc))
    def test_rate_exact_and_clear_missing_distinct(self):
        d=data();o=W.derive(source(),d,grid,(t(3),t(6)),W.PRODUCTS)
        f,m=o['refl'];self.assertEqual(m['interval_hours'],3)
        self.assertEqual(f[0,0],-1);self.assertTrue(np.isnan(f[1,0]))
        np.testing.assert_allclose(f[0,1],N.refl_from_rate(a(1),a(0))[0,0])
        w=o['sigwx'][0];self.assertEqual(w[0,0],-1);self.assertTrue(np.isnan(w[1,0]))
        self.assertEqual(w[0,1],6)
        self.assertFalse(o['sigwx'][1]['ice_type_available'])
    def test_missing_input_no_false_clear(self):
        d=data();del d['cape']
        o=W.derive(source(),d,grid,(t(3),t(6)),W.PRODUCTS)
        self.assertIn('refl',o);self.assertNotIn('sigwx',o)
        self.assertEqual(W.derive(source(),d,grid,None,W.PRODUCTS),{})
        d['snowfall_water_equivalent'][0,1]=10
        self.assertTrue(np.isnan(W.derive(source(),d,grid,(t(3),t(6)),W.PRODUCTS)['refl'][0][0,1]))
    def test_new_models_not_enabled(self):
        s=source();s.dom='aifs'
        self.assertEqual(W.derive(s,data(),grid,(t(3),t(6)),W.PRODUCTS),{})
    def test_fixed_palette_and_manifest_interval(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);valid=t(24);p=d/'ecmwf_sigwx_2026112712.webp'
            arr=np.random.default_rng(108).integers(-1,15,(361,720)).astype(np.float32)
            arr[-1,0]=-1;arr[-1,1]=np.nan
            stats=G.render_convection(arr,'sigwx',p)
            with Image.open(p) as im:
                self.assertEqual(im.getpixel((0,0)),(255,255,255))
                self.assertEqual(im.getpixel((1,0)),(215,215,215))
            m=G.product_manifest('ecmwf',RUN,valid,'ecmwf_ifs025',{})
            f=dict(file=p.name,variable='sigwx',logical_model='ecmwf',units='',
                   init_utc=m['init_utc'],valid_utc=m['valid_utc'],lead_hours=24,
                   nominal_resolution='28 km',field_source_domain='ecmwf_ifs025',
                   source_grid=[720,361],source_grid_origin=[-180,-90],source_grid_spacing=[.5,.5],
                   palette='sigwx',input_variables=['precipitation'],calculation='diagnostic',
                   interval_start_utc=t(21).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   interval_end_utc=m['valid_utc'],interval_hours=3,clear_value=-1,
                   phase_basis='native snowfall water equivalent',
                   precipitation_basis='native backward sum; raw model rate; not DEM corrected',
                   sha256=hashlib.sha256(p.read_bytes()).hexdigest(),**stats)
            self.assertEqual(verify_manifest_field('ecmwf','sigwx',f,m,d)[0],p.read_bytes())
            f['interval_hours']=6
            with self.assertRaisesRegex(ValueError,'interval'):verify_manifest_field('ecmwf','sigwx',f,m,d)
if __name__=='__main__':unittest.main()
