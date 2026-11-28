"""Verified world publication must preserve provenance and reject invalid sources."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import global_nwp_stage as g
from pack_global_products import package


class WorldPackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base / 'download'
        self.dest = self.base / 'published'
        self.run = datetime(2026, 11, 21, 0, tzinfo=timezone.utc)
        self.valid = self.run + timedelta(hours=24)
        self.manifests = {}
        native = {
            'ecmwf': 'ecmwf_ifs025',
            'gfs': 'ncep_gfs025',
            'gem': 'cmc_gem_gdps_15km',
            'icon': 'dwd_icon',
            'ukmo': 'ukmo_global_deterministic_10km',
        }
        for model, domain in native.items():
            folder = self.src / ('world-' + model)
            folder.mkdir(parents=True)
            name = f'{model}_t2m_{self.valid:%Y%m%d%H}.webp'
            path = folder / name
            values = np.tile(np.linspace(260, 300, 720, dtype=np.float32),
                             (361, 1))
            stats = g.render(values, 't2m', path)
            field = {
                'file': name, 'variable': 'temperature_2m',
                'logical_model': model,
                'units': '°C', 'nominal_resolution': {'ecmwf':'28 km','gfs':'28 km','gem':'15 km','icon':'13 km','ukmo':'10 km'}[model],
                'field_source_domain': domain,
                'init_utc': self.run.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'valid_utc': self.valid.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'lead_hours': 24,
                'source_grid': [720, 361],
                'source_grid_origin': [-180, -90],
                'source_grid_spacing': [0.5, 0.5],
                'source_grid_bbox_centers_wgs84': [-180, -90, 179.5, 90],
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                **stats,
            }
            manifest = g.product_manifest(
                model, self.run, self.valid, domain, {'t2m': field})
            self.manifests[model] = manifest
            self.write_manifest(model)

    def write_manifest(self, model):
        path = self.src / ('world-' + model) / 'manifest.json'
        path.write_text(json.dumps(self.manifests[model]),
                        encoding='utf-8')

    def test_valid_real_webp_passes_through_without_change(self):
        result = package(self.src, self.dest)
        self.assertFalse(result['complete'])
        self.assertTrue(result['models_complete'])
        self.assertEqual(result['coverage']['missing_fields']['gem'], ['mslp', 'z500'])
        self.assertEqual(result['coverage']['lead_hours_by_model']['gfs'], [24])
        self.assertEqual(set(result['models']), {'gfs', 'ecmwf', 'gem', 'icon', 'ukmo'})
        for model in result['models']:
            original = (self.src / ('world-' + model) /
                        self.manifests[model]['fields']['t2m']['file']).read_bytes()
            published = (self.dest / model / 't2m.webp').read_bytes()
            self.assertEqual(published, original)
            self.assertEqual(result['models'][model]['fields']['t2m']['sha256'],
                             hashlib.sha256(published).hexdigest())

    def test_ukmo_licence_is_sharealike_and_grid_is_not_mislabeled(self):
        result = package(self.src, self.dest)
        self.assertIn('CC BY-SA 4.0', result['models']['ukmo']['source_license'])
        self.manifests['ukmo']['fields']['t2m']['nominal_resolution'] = '15 km'
        self.write_manifest('ukmo')
        with self.assertRaisesRegex(ValueError, 'resolution label mismatch'):
            package(self.src, self.dest)

    def test_tampered_raster_rejected(self):
        path = self.src / 'world-gfs' / self.manifests['gfs']['fields']['t2m']['file']
        data = bytearray(path.read_bytes())
        data[-10] ^= 15
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            package(self.src, self.dest)

    def test_untrusted_path_rejected_before_open(self):
        self.manifests['ecmwf']['fields']['t2m']['file'] = '../../secret.webp'
        self.write_manifest('ecmwf')
        with self.assertRaisesRegex(ValueError, 'unexpected raster filename'):
            package(self.src, self.dest)

    def test_regional_origin_cannot_claim_globe(self):
        self.manifests['ecmwf']['fields']['t2m']['source_grid_origin'] = [30, -90]
        self.write_manifest('ecmwf')
        with self.assertRaisesRegex(ValueError, 'not global'):
            package(self.src, self.dest)

    def test_wrong_cycle_or_lead_cannot_publish(self):
        self.manifests['ecmwf']['fields']['t2m']['lead_hours'] = 25
        self.write_manifest('ecmwf')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            package(self.src, self.dest)

    def test_wrong_model_field_cannot_be_attributed_to_ecmwf(self):
        self.manifests['ecmwf']['fields']['t2m']['field_source_domain'] = 'ncep_gfs013'
        self.write_manifest('ecmwf')
        with self.assertRaisesRegex(ValueError, 'source differs'):
            package(self.src, self.dest)

    def test_truncated_webp_rejected_even_with_matching_checksum(self):
        field = self.manifests['ecmwf']['fields']['t2m']
        path = self.src / 'world-ecmwf' / field['file']
        path.write_bytes(path.read_bytes()[:-4])
        field['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_manifest('ecmwf')
        with self.assertRaisesRegex(ValueError, 'truncated WebP'):
            package(self.src, self.dest)

    def test_legacy_manifest_without_provenance_rejected(self):
        self.manifests['ecmwf']['schema'] = 1
        self.write_manifest('ecmwf')
        with self.assertRaisesRegex(ValueError, 'schema-2'):
            package(self.src, self.dest)


if __name__ == '__main__':
    unittest.main()
