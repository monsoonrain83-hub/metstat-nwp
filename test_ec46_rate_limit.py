"""Offline contract tests for EC46 HTTP retry, without scientific dependencies."""
import ast
from pathlib import Path
import time
import unittest

tree = ast.parse(Path(__file__).with_name("wk_maps.py").read_text())
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_ec46_request", "_ec46_batches"}]
ns = {"time": time, "SAPI": "https://example.invalid", "log": lambda *a: None}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "wk_maps.py", "exec"), ns)
request = ns["_ec46_request"]

class Response:
    text = ""
    def __init__(self, status, retry_after=""):
        self.status_code = status
        self.headers = {"Retry-After": retry_after}
    def json(self):
        return {"ok": True}

class RetryTests(unittest.TestCase):
    def check(self, responses, budget=900):
        now, waits, calls = [0], [], []
        def get(url, **kwargs):
            calls.append(kwargs)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        def sleep(delay):
            waits.append(delay)
            now[0] += delay
        result = request(get, {}, budget, clock=lambda: now[0], sleep=sleep)
        return result, waits, calls
    def test_success(self):
        result, waits, calls = self.check([Response(200)])
        self.assertEqual(result, ({"ok": True}, False))
        self.assertEqual(waits, [])
        self.assertEqual(len(calls), 1)
    def test_retry_after(self):
        result, waits, calls = self.check([Response(429, "90"), Response(200)])
        self.assertEqual(result, ({"ok": True}, False))
        self.assertEqual(waits, [90])
    def test_persistent_rate_limit(self):
        result, waits, calls = self.check([Response(429)] * 3)
        self.assertEqual(result, (None, True))
        self.assertEqual(waits, [65, 130])
        self.assertEqual(len(calls), 3)
    def test_budget(self):
        result, waits, calls = self.check([Response(429, "120")], budget=90)
        self.assertEqual(result, (None, True))
        self.assertEqual(waits, [])
    def test_bad_model(self):
        result, waits, calls = self.check([Response(400)])
        self.assertEqual(result, (None, False))
        self.assertEqual(waits, [])
    def test_transient_network(self):
        result, waits, calls = self.check([TimeoutError(), Response(200)])
        self.assertEqual(result, ({"ok": True}, False))
        self.assertEqual(waits, [4])

class AdaptiveGridTests(unittest.TestCase):
    def run_grid(self, total, fetch, budget=100):
        now = [0]
        def sleep(delay):
            now[0] += delay
        return ns["_ec46_batches"](total, fetch, budget, clock=lambda: now[0], sleep=sleep, batch_size=4)
    def test_only_failed_batch_is_subdivided(self):
        calls = []
        def fetch(start, count):
            calls.append((start, count))
            return (None, False) if (start, count) == (4, 4) else (list(range(start, start+count)), False)
        self.assertEqual(self.run_grid(10, fetch), (list(range(10)), 10, False))
        self.assertEqual(calls, [(0,4),(4,4),(4,2),(6,2),(8,2)])
    def test_rate_limit_stops_without_subdivision(self):
        calls = []
        def fetch(start, count):
            calls.append((start,count))
            return (None, True) if start == 4 else (list(range(count)), False)
        self.assertEqual(self.run_grid(8, fetch), (None,4,True))
        self.assertEqual(calls, [(0,4),(4,4)])
    def test_single_missing_coordinate_blocks_publication(self):
        def fetch(start, count):
            return (None,False) if start <= 5 < start+count else (list(range(start,start+count)),False)
        self.assertEqual(self.run_grid(8, fetch), (None,5,False))
    def test_short_response_is_not_accepted(self):
        def fetch(start,count):
            return ([start], False) if count > 1 else ([start],False)
        self.assertEqual(self.run_grid(8,fetch),(list(range(8)),8,False))
    def test_budget_never_returns_partial_grid(self):
        self.assertEqual(self.run_grid(8,lambda s,n:(list(range(s,s+n)),False),budget=1),(None,4,False))

if __name__ == "__main__":
    unittest.main()
