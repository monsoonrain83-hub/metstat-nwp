# -*- coding: utf-8 -*-
"""Offline checks for optional verified EC46 weekly pressure anomaly.
No internet, API keys or host publication are used.
"""
import unittest
from unittest.mock import patch
import wk_maps as wk


class FakeUploader:
    def __init__(self):
        self.begins = []
        self.files = []
        self.ends = []

    def call(self, action, js=None):
        if action == 'begin':
            self.begins.append(js)
            return {'have': []}
        if action == 'end':
            self.ends.append(js)
        return {}

    def put(self, model, run, path, content, metadata):
        self.files.append((model, run, path, metadata))

    def wait(self):
        pass


class Ec46WeeklyPressureAnomalyTest(unittest.TestCase):
    def test_mock_contract_without_optional_field_unchanged(self):
        v = wk.ec_weekly(mock=True)
        self.assertEqual(len(v), 5)
        self.assertEqual(v[3].shape, v[4].shape)

    def test_optional_pressure_grid_is_signed(self):
        v = wk.ec_weekly(mock=True, include_mslp=True)
        self.assertEqual(len(v), 6)
        self.assertEqual(v[3].shape, v[5].shape)
        self.assertLess(float(v[5].min()), 0)
        self.assertGreater(float(v[5].max()), 0)

    def test_publish_only_when_optional_data_exists(self):
        for enabled, count in [(False, 12), (True, 18)]:
            with self.subTest(enabled=enabled):
                up = FakeUploader()
                result = wk.ec_weekly(mock=True, include_mslp=enabled)
                with patch.object(wk.L, 'regrid', side_effect=lambda x, lon, lat: x), \
                     patch.object(wk.N, 'render_me', return_value=(b'mock-webp', None)):
                    n = wk.make_weekly(up, 'ecwk', result, None)
                self.assertEqual(n, count)
                self.assertEqual(len(up.files), count)
                self.assertEqual(len(up.ends), 1)
                params = up.begins[0]['params']
                self.assertEqual('wslpa' in params, enabled)
                self.assertIn('en', params['wta'])
                self.assertIn('en', params['wpa'])
                if enabled:
                    self.assertEqual(params['wslpa']['unit'], 'hPa')
                    self.assertEqual(sum('/wslpa_' in x[2] for x in up.files), 6)


if __name__ == '__main__':
    unittest.main()
