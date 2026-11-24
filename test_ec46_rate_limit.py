"""Offline contract tests for EC46 HTTP retry, without scientific dependencies."""
import ast
from pathlib import Path
import time
import unittest

tree = ast.parse(Path(__file__).with_name("wk_maps.py").read_text())
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_ec46_request")
ns = {"time": time, "SAPI": "https://example.invalid", "log": lambda *a: None}
exec(compile(ast.Module(body=[node], type_ignores=[]), "wk_maps.py", "exec"), ns)
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

if __name__ == "__main__":
    unittest.main()
