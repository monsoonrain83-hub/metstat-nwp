"""Offline regression for EC46 batching, without importing render dependencies."""
import ast
import time
import unittest
from pathlib import Path

source = Path(__file__).with_name('wk_maps.py')
node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
            if isinstance(n, ast.FunctionDef) and n.name == '_ec46_batches')
ns = {'time': time}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), ns)
batches = ns['_ec46_batches']

class Clock:
    def __init__(self): self.now = 0
    def clock(self): return self.now
    def sleep(self, delay): self.now += delay

class TestAdaptiveBatches(unittest.TestCase):
    def run_case(self, total, response, deadline=1800):
        clock, calls = Clock(), []
        def fetch(start, count):
            calls.append((start, count))
            return response(start, count, clock)
        return batches(total, fetch, deadline, clock.clock, clock.sleep), calls

    def test_healthy_batches_unchanged(self):
        result, calls = self.run_case(23, lambda s,n,c: (list(range(s,s+n)),False))
        self.assertEqual(result, (list(range(23)),23,False))
        self.assertEqual(calls, [(0,10),(10,10),(20,3)])

    def test_repeated_large_failures_adapt_preserving_all_points(self):
        def response(s,n,c):
            if n > 5:
                c.sleep(120)
                return None,False
            return list(range(s,s+n)),False
        result,calls = self.run_case(40,response,deadline=300)
        self.assertEqual(result,(list(range(40)),40,False))
        self.assertEqual([x for x in calls if x[1]>5],[(0,10),(10,10)])
        self.assertEqual(len(calls),10)

    def test_one_failure_does_not_adapt(self):
        result,calls = self.run_case(30,lambda s,n,c: (None,False) if (s,n)==(0,10) else (list(range(s,s+n)),False))
        self.assertEqual(result,(list(range(30)),30,False))
        self.assertIn((20,10),calls)

    def test_rate_limit_stops_immediately(self):
        result,calls=self.run_case(30,lambda s,n,c: (None,True) if s==10 else (list(range(s,s+n)),False))
        self.assertEqual(result,(None,10,True))
        self.assertEqual(calls,[(0,10),(10,10)])

    def test_incomplete_singleton_never_publishes(self):
        result,_=self.run_case(11,lambda s,n,c: (None,False) if s==10 else (list(range(s,s+n)),False))
        self.assertEqual(result,(None,10,False))

    def test_deadline_rejects_partial_data(self):
        result,calls=self.run_case(30,lambda s,n,c: (list(range(s,s+n)),False),deadline=4)
        self.assertEqual(result,(None,10,False))
        self.assertEqual(calls,[(0,10)])

if __name__ == '__main__': unittest.main()
