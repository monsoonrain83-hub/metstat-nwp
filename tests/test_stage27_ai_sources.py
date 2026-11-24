import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from ai_model_sources import (
    aifs_request, aigfs_url, aigfs_byte_range, has_grib_record,
    matching_aigfs_records, probe_aigfs, stage_aigfs_grib, validate,
)
from nwp_unified_resolution import select_frame_source

RUN = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
INDEX = ("1:0:d=2026112312:HGT:500 mb:12 hour fcst:\n"
         "2:50:d=2026112312:TMP:850 mb:12 hour fcst:\n"
         "3:90:d=2026112312:APCP:surface:6-12 hour acc fcst:\n")


class Stage27Sources(unittest.TestCase):
    def test_noaa_path_for_actual_product(self):
        self.assertEqual(
            aigfs_url(RUN, 12, "z500"),
            "https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigfs/prod/"
            "aigfs.20261123/12/model/atmos/grib2/aigfs.t12z.pres.f012.grib2.idx")

    def test_no_false_level_or_variable(self):
        self.assertTrue(has_grib_record(INDEX, "z500"))
        self.assertTrue(has_grib_record(INDEX, "precipitation"))
        self.assertFalse(has_grib_record("1:0:d=2026112312:HGT:700 mb:12 hour fcst:", "z500"))
        self.assertFalse(has_grib_record("1:0:d=2026112312:APCP:500 mb:12 hour fcst:", "precipitation"))

    def test_probe_reads_index_only(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def geturl(self): return aigfs_url(RUN, 12, "z500")
            def read(self, n): return INDEX.encode()
        with patch("ai_model_sources.urlopen", return_value=Response()) as fetch:
            result = probe_aigfs(RUN, 12, "z500")
        self.assertTrue(result["verified_index"])
        self.assertTrue(fetch.call_args.args[0].full_url.endswith(".idx"))

    def test_run_and_lead_validation(self):
        for value in (-6, 5, 366, 390):
            with self.assertRaises(ValueError):
                validate(RUN, value, "aifs")
        with self.assertRaises(ValueError):
            validate(RUN.replace(tzinfo=None), 24, "aigfs")
        with self.assertRaises(ValueError):
            validate(RUN.replace(minute=30), 24, "aifs")

    def test_aifs_exact_params(self):
        self.assertEqual(aifs_request(RUN, 360, "z500")["levelist"], 500)
        self.assertEqual(aifs_request(RUN, 24, "precipitation")["param"], "tp")

    def test_ecmwf_9_to_28_at_240(self):
        def present(domain, variable, run, valid):
            h = int((valid - run).total_seconds() // 3600)
            return domain == "ecmwf_ifs025" or (domain == "ecmwf_ifs" and h <= 240)
        for lead in (0, 120, 240, 246, 360):
            choice = select_frame_source("ecmwf", "geopotential_height_500hPa",
                                         RUN, RUN + timedelta(hours=lead), present)
            self.assertEqual(choice.domain, "ecmwf_ifs" if lead <= 240 else "ecmwf_ifs025")

    def test_missing_z200_is_from_lower_res(self):
        choice = select_frame_source(
            "ecmwf", "geopotential_height_200hPa", RUN,
            RUN + timedelta(hours=144), lambda dom, *args: dom == "ecmwf_ifs025")
        self.assertEqual(choice.domain, "ecmwf_ifs025")

    def test_gfs_source_priority(self):
        for lead in (6, 240, 384):
            choice = select_frame_source(
                "gfs", "wind_u_component_200hPa", RUN,
                RUN + timedelta(hours=lead),
                lambda dom, *args: dom == "ncep_gfs025" or lead <= 240)
            self.assertEqual(choice.domain, "ncep_gfs013" if lead <= 240 else "ncep_gfs025")

    def test_fail_closed_for_missing_and_short_cycle(self):
        self.assertIsNone(select_frame_source(
            "ecmwf", "z500", RUN, RUN + timedelta(hours=24), lambda *a: False))
        r = RUN.replace(hour=6)
        self.assertIsNone(select_frame_source(
            "ecmwf", "z500", r, r + timedelta(hours=360), lambda *a: True))


    def test_aigfs_duplicate_precipitation_is_ambiguous(self):
        duplicated = (
            "1:0:d=2026112312:APCP:surface:6-12 hour acc fcst:\n"
            "2:26:d=2026112312:APCP:surface:6-12 hour acc fcst:\n")
        self.assertFalse(has_grib_record(duplicated, "precipitation", RUN, 12))
        self.assertEqual(len(matching_aigfs_records(
            duplicated, "precipitation", RUN, 12)), 2)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            aigfs_byte_range(duplicated, RUN, 12, "precipitation")

    def test_aigfs_cycle_forecast_window_and_parameter_exact(self):
        self.assertTrue(has_grib_record(INDEX, "z500", RUN, 12))
        self.assertTrue(has_grib_record(INDEX, "precipitation", RUN, 12))
        self.assertFalse(has_grib_record(INDEX, "precipitation", RUN, 6))
        self.assertFalse(has_grib_record(INDEX, "z500", RUN, 6))
        self.assertFalse(has_grib_record(INDEX, "z500", RUN.replace(hour=0), 12))
        self.assertFalse(has_grib_record(INDEX, "precipitation", RUN, 0))

    def test_aigfs_range_exact_boundaries(self):
        self.assertEqual(aigfs_byte_range(INDEX, RUN, 12, "z500"), (0, 49))
        with self.assertRaisesRegex(ValueError, "cannot bound"):
            aigfs_byte_range(INDEX, RUN, 12, "precipitation")
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            aigfs_byte_range("1:50:d=2026112312:HGT:500 mb:12 hour fcst:\n"
                             "2:40:d=2026112312:TMP:500 mb:12 hour fcst:\n",
                             RUN, 12, "z500")

    def test_aigfs_bounded_download_staged_only(self):
        header = b"GRIB" + b"\x00\x00\x00\x02" + (24).to_bytes(8, "big")
        raw = header + b"DATA" + b"7777"
        index = "1:0:d=2026112312:HGT:500 mb:12 hour fcst:\n" + (
            "2:24:d=2026112312:TMP:500 mb:12 hour fcst:\n")
        url = aigfs_url(RUN, 12, "z500")
        class Response:
            def __init__(self, target, payload, status=200, headers=None):
                self.target = target
                self.payload = payload
                self.status = status
                self.headers = headers or {}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def geturl(self): return self.target
            def read(self, n): return self.payload[:n]
        responses = [Response(url, index.encode("ascii")),
                     Response(url[:-4], raw, 206, {"Content-Range": "bytes 0-23/100"})]
        with TemporaryDirectory() as tmp:
            with patch("ai_model_sources.urlopen", side_effect=responses) as fetch:
                output = stage_aigfs_grib(RUN, 12, "z500", Path(tmp))
            self.assertEqual(output.read_bytes(), raw)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args.args[0].headers["Range"], "bytes=0-23")
            info = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(info["source_run_time"], RUN.isoformat())
            self.assertEqual(info["state"], "staged_only_requires_field_and_geometry_qc")
            self.assertFalse(info["published"])
            with self.assertRaises(FileExistsError):
                stage_aigfs_grib(RUN, 12, "z500", Path(tmp))

    def test_range_http_200_refused_even_with_grib_bytes(self):
        raw = b"GRIB" + b"\x00\x00\x00\x02" + (24).to_bytes(8, "big") + b"DATA7777"
        index = ("1:0:d=2026112312:HGT:500 mb:12 hour fcst:\n"
                 "2:24:d=2026112312:TMP:500 mb:12 hour fcst:\n")
        url = aigfs_url(RUN, 12, "z500")
        class Resp:
            def __init__(self, target, data):
                self.target, self.data = target, data
                self.status, self.headers = 200, {}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def geturl(self): return self.target
            def read(self, n): return self.data[:n]
        with TemporaryDirectory() as tmp:
            with patch("ai_model_sources.urlopen", side_effect=[
                    Resp(url, index.encode()), Resp(url[:-4], raw)]):
                with self.assertRaisesRegex(ValueError, "ignored bounded Range"):
                    stage_aigfs_grib(RUN, 12, "z500", Path(tmp))
            self.assertEqual(list(Path(tmp).glob("*")), [])


if __name__ == "__main__":
    unittest.main()
