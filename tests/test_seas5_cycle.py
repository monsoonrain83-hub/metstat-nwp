"""Regression tests for SEAS monthly publishing: cache, completeness and fallback."""
import datetime as datetime_module
import sys
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import seas5_maps as seas


class FixedDate(datetime_module.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 20)


class Seas5CycleTests(unittest.TestCase):
    def test_completed_host_run_is_reusable(self):
        with patch("requests.get") as get:
            get.return_value.json.return_value = {
                "models": {"ecmwfseas": {"run": "2026100100", "status": "complete"}}
            }
            self.assertEqual(seas.host_run("https://example.invalid/online", "ecmwfseas"), "2026100100")

    def test_incomplete_host_run_is_not_reusable(self):
        for status in ("building", "pending", "error", None):
            with self.subTest(status=status), patch("requests.get") as get:
                get.return_value.json.return_value = {
                    "models": {"ecmwfseas": {"run": "2026100100", "status": status}}
                }
                self.assertIsNone(seas.host_run("https://example.invalid/online", "ecmwfseas"))

    def _execute(self, have, retrieve_side_effect):
        fake_cds = types.ModuleType("cdsapi")
        fake_cds.Client = Mock(return_value=object())
        with (
            patch.object(sys, "argv", ["seas5_maps.py", "--host", "https://example.invalid/online"]),
            patch.object(seas.dt, "date", FixedDate),
            patch.object(seas.N, "Uploader"),
            patch.object(seas, "host_run", side_effect=have),
            patch.object(seas, "retrieve", side_effect=retrieve_side_effect) as retrieve,
            patch.object(seas, "read_cds") as read_cds,
            patch.object(seas, "convert") as convert,
            patch.object(seas, "publish") as publish,
            patch.dict(sys.modules, {"cdsapi": fake_cds}),
        ):
            read_cds.return_value = (
                np.ones((6, 2, 2)), np.array([40, 41]), np.array([30, 29]),
                list(range(6)), "K"
            )
            convert.return_value = np.ones((6, 2, 2))
            result = seas.main()
            return result, retrieve.call_count, publish.call_count

    def test_current_published_does_not_download_again(self):
        result, retrieved, published = self._execute(
            ["2026110100", "2026110100"], RuntimeError("not ready")
        )
        self.assertEqual((result, retrieved, published), (0, 0, 0))

    def test_current_not_ready_skips_already_published_previous_cycle(self):
        result, retrieved, published = self._execute(
            ["2026100100", "2026100100"], RuntimeError("not ready")
        )
        self.assertEqual((result, retrieved, published), (0, 1, 0))

    def test_previous_incomplete_retries_previous_cycle(self):
        result, retrieved, published = self._execute(
            ["2026100100", None], RuntimeError("not ready")
        )
        self.assertEqual((result, retrieved, published), (0, 2, 0))

    def test_missing_temperature_or_precipitation_never_publishes_partial_cycle(self):
        def retrieve(c, cds_var, y, m, path):
            if cds_var == seas.VARS["tpara"][0]:
                raise RuntimeError("precipitation missing")
        result, retrieved, published = self._execute(
            ["2026100100", "2026100100"], retrieve
        )
        self.assertEqual((result, retrieved, published), (0, 2, 0))


if __name__ == "__main__":
    unittest.main()
