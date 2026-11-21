"""Guard height anomaly map metadata: calculated values are decametres, not decimetres."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class TestGeopotentialAnomalyUnits(unittest.TestCase):
    def test_model_labels_are_decametres(self):
        src=(ROOT/'nwp_maps.py').read_text(encoding='utf-8')
        for p in ('z500a','z700a','z850a'):
            with self.subTest(parameter=p):
                line=next((s for s in src.splitlines() if re.match(r'^\\s*\''+p+r'\': dict\\(',s)),None)
                self.assertIsNotNone(line,p)
                self.assertIn("unit='dam'",line)
                self.assertIn('snapshot, dam)',line)
                self.assertNotIn("unit='dm'",line)
    def test_ensemble_z500_anomaly_is_decametres(self):
        s=(ROOT/'ens_maps.py').read_text(encoding='utf-8')
        self.assertRegex(s,r"'z500a':\\s*\\([^\\n]*'dam'")

if __name__=='__main__': unittest.main()
