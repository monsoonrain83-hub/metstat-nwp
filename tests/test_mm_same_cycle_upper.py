"""Regression: optional GFS 0.25-degree pressure levels must match the 0.13-degree cycle."""
import unittest
from datetime import datetime, timedelta, timezone
from nwp_maps import read_same_cycle_upper


class FakeUpper:
    def __init__(self, available, result=None):
        self.available = available
        self.result = result if result is not None else {'geopotential_height_500hPa': 5580.0}
        self.checked = []
        self.read_calls = []

    def exists(self, run, valid):
        self.checked.append((run, valid))
        return (run, valid) in self.available

    def read(self, run, valid, names):
        self.read_calls.append((run, valid, names))
        return self.result


class UpperMustMatchCycleTests(unittest.TestCase):
    def setUp(self):
        self.run = datetime(2026, 11, 21, 0, tzinfo=timezone.utc)
        self.valid = self.run + timedelta(hours=24)
        self.fields = {'temperature_500hPa', 'geopotential_height_500hPa'}

    def test_no_silent_fallback_to_older_cycle(self):
        source = FakeUpper({(self.run - timedelta(hours=6), self.valid)})
        self.assertIsNone(read_same_cycle_upper(source, self.run, self.valid, self.fields))
        self.assertEqual(source.checked, [(self.run, self.valid)])
        self.assertEqual(source.read_calls, [])

    def test_same_cycle_data_are_read_with_sorted_field_names(self):
        source = FakeUpper({
            (self.run, self.valid),
            (self.run - timedelta(hours=6), self.valid),
        })
        self.assertIn('geopotential_height_500hPa',
                      read_same_cycle_upper(source, self.run, self.valid, self.fields))
        self.assertEqual(source.read_calls, [(
            self.run, self.valid, sorted(self.fields))])

    def test_malformed_upstream_response_fails_closed(self):
        source = FakeUpper({(self.run, self.valid)}, result=[])
        with self.assertRaisesRegex(ValueError, 'field dictionary'):
            read_same_cycle_upper(source, self.run, self.valid, self.fields)


if __name__ == '__main__':
    unittest.main()
