"""V107 offline convection formula, geometry and publication tests."""
import hashlib,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
import global_nwp_stage as G
import world_convection as C
import nwp_maps as N
from pack_global_products import verify_manifest_field,CONVECTION_UNITS

def a(x):return np.full((2,3),x,np.float32)
def validate(src,v):
    if not isinstance(v,np.ndarray) or v.shape!=(2,3):raise ValueError('bad grid')
    return v
def fields():
    d={'cape':a(850),'convective_inhibition':a(-50),'surface_pressure':a(1010),
       'temperature_2m':a(25),'relative_humidity_2m':a(70),
       'wind_u_component_10m':a(1),'wind_v_component_10m':a(2)}
    for p,t in [(925,20),(850,15),(700,5),(500,-20)]:
        d[f'temperature_{p}hPa']=a(t);d[f'relative_humidity_{p}hPa']=a(70)
        d[f'wind_u_component_{p}hPa']=a(10 if p==500 else 4)
        d[f'wind_v_component_{p}hPa']=a(15 if p==500 else 7)
    return d
class Convection(unittest.TestCase):
    def setUp(self):self.src=SimpleNamespace(hsurf=lambda:a(0));self.d=fields()
    def derive(self,selected=None):return C.derive('ecmwf',self.src,self.d,validate,selected)
    def test_every_product_all_five_families(self):
        for model in C.MODELS:
            result=C.derive(model,self.src,self.d,validate)
            self.assertEqual(set(result),set(C.PRODUCTS))
            self.assertTrue(all(np.isfinite(v).all() for v,_ in result.values()))
        self.assertEqual({k:v[0] for k,v in C.PRODUCTS.items()},{k:CONVECTION_UNITS[k] for k in C.PRODUCTS})
    def test_new_models_excluded(self):
        for m in ('aifs','aigfs','graphcast','arpege','jma','cma','kim'):
            with self.assertRaises(ValueError):C.derive(m,self.src,self.d,validate)
    def test_existing_k_gdi_and_tt(self):
        T={p:self.d[f'temperature_{p}hPa'] for p in C.LEVELS}
        R={p:self.d[f'relative_humidity_{p}hPa'] for p in C.LEVELS}
        out=self.derive()
        np.testing.assert_allclose(out['ki'][0],N.k_index(T,R))
        np.testing.assert_allclose(out['si'][0],N.soaring_index(T,R))
        np.testing.assert_allclose(out['gdi'][0],N.gdi(T,R,self.d['surface_pressure']))
        np.testing.assert_allclose(out['tt'][0],T[850]+N.td_from_rh(T[850],R[850])-2*T[500])
    def test_ko_and_sweat_match_existing_secondary_formulas(self):
        import secondary as sec
        f=dict(t2=self.d['temperature_2m'],rh2=self.d['relative_humidity_2m'],ps=self.d['surface_pressure'])
        for p in (850,700,500):
            f[f't{p}']=self.d[f'temperature_{p}hPa'];f[f'rh{p}']=self.d[f'relative_humidity_{p}hPa']
        for p in (850,500):
            for c in ('u','v'):f[f'{c}{p}']=self.d[f'wind_{c}_component_{p}hPa']
        expected=sec.indices(f);out=self.derive({'ko','swt'})
        np.testing.assert_allclose(out['ko'][0],expected['ko'])
        np.testing.assert_allclose(out['swt'][0],expected['sweat'])
        del self.d['wind_v_component_850hPa']
        self.assertNotIn('swt',self.derive({'swt'}))
    def test_bad_grid_and_no_synthetic_zero(self):
        del self.d['relative_humidity_700hPa']
        self.d['cape']=np.ones((4,5))
        out=self.derive()
        self.assertNotIn('ki',out);self.assertNotIn('gdi',out);self.assertNotIn('cape',out)
        self.assertIn('tt',out)
    def test_mask_below_ground(self):
        self.d['surface_pressure'][0,0]=800
        out=self.derive()
        self.assertTrue(np.isnan(out['ki'][0][0,0]))
        self.assertTrue(np.isnan(out['gdi'][0][0,0]))
        self.assertTrue(np.isfinite(out['lr75'][0][0,0]))
        self.assertTrue(np.isfinite(out['cape'][0][0,0]))
    def test_pressure_approximation_explicit(self):
        del self.d['surface_pressure'];self.d['pressure_msl']=a(1010)
        self.assertIn('approximation',self.derive({'ki'})['ki'][1]['surface_pressure_basis'])
    def test_native_cin_sign_not_guessed(self):
        self.d['convective_inhibition']=a(50)
        self.assertNotIn('cin',self.derive({'cin'}))
    def test_native_li_preferred(self):
        self.d['lifted_index']=a(-4)
        value,meta=self.derive({'li'})['li']
        np.testing.assert_array_equal(value,a(-4));self.assertEqual(meta['calculation'],'native Open-Meteo field')
    def test_palette_bytes_and_provenance_gate(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);run=datetime(2026,11,26,tzinfo=timezone.utc);valid=run+timedelta(hours=24)
            p=d/'ecmwf_cape_2026112700.webp';arr=np.random.default_rng(107).uniform(0,4000,(361,720)).astype(np.float32);arr[-1,0]=850
            stats=G.render_convection(arr,'cape',p)
            with Image.open(p) as im:
                scale=N.styles.SC['cape'];i=np.digitize(850,scale['edges'][1:-1])
                self.assertEqual(im.getpixel((0,0)),N.styles.hex2rgb(scale['colors'][i]))
            m=G.product_manifest('ecmwf',run,valid,'ecmwf_ifs025',{})
            f=dict(file=p.name,variable='cape',logical_model='ecmwf',units='J/kg',
              init_utc=m['init_utc'],valid_utc=m['valid_utc'],lead_hours=24,
              nominal_resolution='28 km',field_source_domain='ecmwf_ifs025',
              source_grid=[720,361],source_grid_origin=[-180,-90],source_grid_spacing=[.5,.5],
              palette='cape',input_variables=['cape'],calculation='native Open-Meteo field',
              sha256=hashlib.sha256(p.read_bytes()).hexdigest(),**stats)
            self.assertEqual(verify_manifest_field('ecmwf','cape',f,m,d)[0],p.read_bytes())
            del f['calculation']
            with self.assertRaisesRegex(ValueError,'provenance'):verify_manifest_field('ecmwf','cape',f,m,d)
if __name__=='__main__':unittest.main()
