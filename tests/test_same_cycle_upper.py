"""Pressure-level fallback must never mix forecast initialization cycles."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "nwp_maps.py").read_text(encoding="utf-8"))

class SameCycleUpperTests(unittest.TestCase):
    def test_upper_source_reads_only_current_run(self):
        engine = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "Engine")
        step = next(n for n in engine.body if isinstance(n, ast.FunctionDef) and n.name == "step")
        blocks = [n for n in ast.walk(step) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "name == 'upper'"
                  and any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                          and x.func.attr == "read" for x in ast.walk(n))]
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        calls = [n for n in ast.walk(block) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr in ("read", "exists")]
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(isinstance(c.args[0], ast.Name) and c.args[0].id == "run"
                            for c in calls))
        self.assertFalse(any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Sub)
                             for n in ast.walk(block)))

if __name__ == "__main__":
    unittest.main()
