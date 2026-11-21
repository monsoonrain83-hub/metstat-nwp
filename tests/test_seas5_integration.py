"""Offline regression: SEAS5 completed-cycle cache and optional anomaly fallback."""
import datetime as dt
import sys
import types
import unittest
from unittest.mock import Mock, patch
import numpy as np
import seas5_maps as seas


class FixedDate(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 20)


class TestSeas5CycleIntegration(unittest.TestCase):
    def test_host_only_reuses_complete_cycle(self):
        for status, expected in (
            ("complete", "2026100100"), ("building", None),
            ("pending", None), ("error", None), (None, None)
        ):
            with self.subTest(status=status), patch("requests.get") as get:
                get.return_value.json.return_value = {
                    "models": {"ecmwfseas": {"run": "2026100100", "status": status}}
                }
                self.assertEqual(
                    seas.host_run("https://example.invalid/online", "ecmwfseas"), expected
                )

    def execute(self, hosted, retrieve_callback):
        """No CDS/network/renderer/host: inspect effect of main's decision logic."""
        fake_cds = types.ModuleType("cdsapi")
        fake_cds.Client = Mock(return_value=object())
        payload = np.ones((6, 2, 2))
        with (
            patch.object(sys, "argv", ["seas5_maps.py", "--host", "https://example.invalid/online"]),
            patch.object(seas.dt, "date", FixedDate),
            patch.object(seas.N, "Uploader"),
            patch.object(seas, "host_run", side_effect=hosted),
            patch.object(seas, "retrieve", side_effect=retrieve_callback) as retrieve,
            patch.object(seas, "read_cds", return_value=(
                payload, np.array([40.0, 41.0]), np.array([30.0, 29.0]),
                list(range(6)), "K",
            )),
            patch.object(seas, "convert", side_effect=lambda name, a, units: a),
            patch.object(seas, "publish") as publish,
            patch.dict(sys.modules, {"cdsapi": fake_cds}),
        ):
            rc = seas.main()
            outputs = [
                (tuple(call.args[1].keys()), call.args[4])
                for call in publish.call_args_list
            ]
            return rc, retrieve.call_args_list[:], outputs

    def test_current_complete_does_not_download(self):
        rc, calls, out = self.execute(["2026110100", "2026110100"], RuntimeError("not ready"))
        self.assertEqual((rc, len(calls), len(out)), (0, 0, 0))

    def test_fallback_previous_complete_does_not_duplicate_publish(self):
        rc, calls, out = self.execute(["2026100100", "2026100100"], RuntimeError("not ready"))
        self.assertEqual((rc, len(calls), len(out)), (0, 1, 0))

    def test_missing_base_product_never_publishes_partial_data(self):
        def missing_precip(client, variable, y, m, path, **kwargs):
            if variable == seas.VARS["tpara"][0]:
                raise RuntimeError("precipitation missing")
        rc, calls, out = self.execute(["2026100100", "2026100100"], missing_precip)
        self.assertEqual(rc, 0)
        self.assertEqual(len(out), 0)
        self.assertEqual(len(calls), 2)

    def test_incomplete_previous_cycle_is_retried(self):
        rc, calls, out = self.execute(["2026100100", None], RuntimeError("not ready"))
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(out), 0)

    def test_optional_products_missing_keep_both_original_products(self):
        def optional_missing(client, variable, y, m, path, **kwargs):
            if variable in (seas.VARS["mslpa"][0], seas.VARS["z500a"][0]):
                raise RuntimeError("optional CDS dataset unavailable")
        rc, calls, out = self.execute([None, None], optional_missing)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0][0]), {"t2a", "tpara"})
        self.assertEqual(out[0][1], "2026110100")

    def test_all_products_produce_single_full_cycle(self):
        rc, calls, out = self.execute([None, None], lambda *a, **kw: None)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0][0]), set(seas.VARS))
        self.assertEqual(out[0][1], "2026110100")


if __name__ == "__main__":
    unittest.main()
