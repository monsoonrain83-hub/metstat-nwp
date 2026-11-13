# -*- coding: utf-8 -*-
"""Regression: do not discard fields while mandatory ECMWF/GFS data is absent."""
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import MethodType, SimpleNamespace

from mm_maps import MMCombiner


class TestPendingFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = datetime(2026, 11, 13, 0, tzinfo=timezone.utc)
        self.key = ('iran', 'p6', self.run, self.run + timedelta(hours=6))
        self.source = os.path.join(self.tmp.name, 'gfs.npz')
        with open(self.source, 'wb') as handle:
            handle.write(b'field')
        self.calls = []
        self.combiner = MMCombiner.__new__(MMCombiner)
        obj = self.combiner
        obj.idx = {self.key: {'gfs': self.source}}
        obj.done = set()
        obj.lock = threading.Lock()
        obj.prog = {}
        obj.t_log = time.time()
        obj.cnt = {}
        obj.eng = SimpleNamespace(up=SimpleNamespace(wait=lambda: None,
                                                      call=lambda *a, **k: None))
        obj.nm = SimpleNamespace(log=lambda *args: None)

    def test_missing_core_is_not_deleted_or_marked_done(self):
        obj = self.combiner
        obj.decide = MethodType(lambda s, k, final=False: {'gfs': 'gfs'}, obj)
        obj.make = MethodType(lambda s, k, pick: self.calls.append(k) or 1, obj)
        obj.tick(final=True)  # even at shutdown, missing ECMWF must not count as success
        self.assertNotIn(self.key, obj.done)
        self.assertTrue(os.path.exists(self.source))
        self.assertEqual(self.calls, [])

    def test_render_exception_keeps_fields_for_retry(self):
        obj = self.combiner
        obj.decide = MethodType(lambda s, k, final=False: {'gfs': 'gfs', 'ecmwf': 'ecmwf9'}, obj)
        def broken(s, k, pick):
            raise RuntimeError('temporary render failure')
        obj.make = MethodType(broken, obj)
        obj.tick()
        self.assertNotIn(self.key, obj.done)
        self.assertTrue(os.path.exists(self.source))

    def test_success_marks_done_and_removes_fields(self):
        obj = self.combiner
        obj.decide = MethodType(lambda s, k, final=False: {'gfs': 'gfs', 'ecmwf': 'ecmwf9'}, obj)
        obj.make = MethodType(lambda s, k, pick: 1, obj)
        obj.tick()
        self.assertIn(self.key, obj.done)
        self.assertFalse(os.path.exists(self.source))


if __name__ == '__main__':
    unittest.main()
