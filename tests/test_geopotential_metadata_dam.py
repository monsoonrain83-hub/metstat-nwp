"""Guard height anomaly map metadata: calculated values are decametres, not decimetres."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TestGeopotentialAnomalyUnits(unittest.TestCase):
    def test_model_labels_are_decametres(self):
        src = (ROOT / 'nwp_maps.py').read_text(encoding='utf-8')
        for p in ('z500a', 'z700a', 'z850a'):
            with self.subTest(parameter=p):
                line = next((s for s in src.splitlines() if s.lstrip().startswith("'"+p+"': dict(")), None)
                self.assertIsNotNone(line, p)
                self.assertIn("unit='dam'", line)
                self.assertIn('snapshot, dam)', line)
                self.assertNotIn("unit='dm'", line)

    def test_ensemble_z500_anomaly_is_decametres(self):
        src = (ROOT / 'ens_maps.py').read_text(encoding='utf-8')
        line = next((s for s in src.splitlines() if s.lstrip().startswith("'z500a': (")), None)
        self.assertIsNotNone(line)
        self.assertIn("'dam'", line)

if __name__ == '__main__':
    unittest.main()
