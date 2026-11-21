"""Daily multimodel policy: 00/12Z only, maximum lead +180h."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "mm_maps.py").read_text(encoding="utf-8"))

class DailyMMPolicyTests(unittest.TestCase):
    def test_horizon_all_parameters(self):
        func = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "max_anomaly_lead")
        self.assertEqual(len(func.body), 2 if isinstance(func.body[0], ast.Expr) else 1)
        self.assertEqual(func.body[-1].value.value, 180)

    def test_sink_requires_00_or_12_utc(self):
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "MMCombiner")
        sink = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "sink")
        self.assertIn("run.hour not in (0, 12)", ast.unparse(sink))
        self.assertIn("max_anomaly_lead(pid)", ast.unparse(sink))

    def test_decide_enforces_horizon(self):
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "MMCombiner")
        decide = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "decide")
        self.assertIn("max_anomaly_lead(pid)", ast.unparse(decide))

if __name__ == "__main__":
    unittest.main()
