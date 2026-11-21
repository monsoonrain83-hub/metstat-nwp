"""Offline regression for ARPEGE scope; no model download or upload."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "nwp_maps.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)

class ArpegePolicyTests(unittest.TestCase):
    def test_model_and_source_present(self):
        self.assertIn("'arpege': dict(", SRC)
        self.assertIn("meteofrance_arpege_world", SRC)
        self.assertIn("os.environ.get('NWP_DROP_MODELS', 'none')", SRC)

    def test_parameter_allowlist_and_region_gate(self):
        gates = [n for n in ast.walk(TREE) if isinstance(n, ast.If) and
                 "mkey == 'arpege'" in ast.unparse(n.test)]
        self.assertEqual(len(gates), 1)
        self.assertIn("rk != 'me'", ast.unparse(gates[0].test))
        for pid in ("p24", "pacc", "t2m", "z500"):
            self.assertIn(repr(pid), ast.unparse(gates[0].test))
        self.assertTrue(any(isinstance(n, ast.Continue) for n in ast.walk(gates[0])))

    def test_only_expected_parameters_activated(self):
        self.assertIn("models=I_ECA + ['arpege']", SRC)
        self.assertIn("models=I_EC + ['arpege']", SRC)
        self.assertIn("'p24'", SRC)

if __name__ == "__main__":
    unittest.main()
