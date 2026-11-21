"""Guard against prematurely completing runs with only partial valid_times."""
import ast
from pathlib import Path
import unittest

TREE = ast.parse((Path(__file__).resolve().parents[1] / 'nwp_maps.py').read_text(encoding='utf-8'))

class RunCompletionTests(unittest.TestCase):
    def test_completion_requires_full_horizon(self):
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'Engine')
        tick = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'tick')
        exprs = [n.value for n in ast.walk(tick) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'complete' for t in n.targets)]
        self.assertEqual(len(exprs), 1)
        complete = compile(ast.Expression(exprs[0]), '<completion>', 'eval')
        def check(last, hz=384, source_complete=True, processed=True):
            from datetime import datetime, timedelta, timezone
            run = datetime(2026, 11, 21, tzinfo=timezone.utc)
            vts = [run + timedelta(hours=last)]
            st = type('State', (), {'done_i': 0 if processed else -1})()
            meta = {'completed': source_complete}
            available_horizon = last
            return eval(complete, {'st': st, 'vts': vts, 'meta': meta, 'available_horizon': available_horizon, 'hz': hz})
        self.assertFalse(check(336))
        self.assertFalse(check(384, source_complete=False))
        self.assertFalse(check(384, processed=False))
        self.assertTrue(check(384))
        self.assertTrue(check(240, hz=240))

if __name__ == '__main__': unittest.main()
