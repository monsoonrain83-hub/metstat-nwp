"""Offline tests for safe publication of regenerated METAR/SYNOP stations."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import obs_station_publish as p


def fixture():
    return {"generated": "2026-11-20T00:00:00Z", "n": 2, "n_active": 1, "stations": [
        {"id": "OIII", "lat": 35.69, "lon": 51.31, "active": True},
        {"id": "40718", "lat": 37.47, "lon": 49.46, "active": False}
    ]}


class PublishSafety(unittest.TestCase):
    def check(self, data):
        return p.check_payload(json.dumps(data).encode("utf-8"))

    def test_valid_registry(self):
        self.assertEqual(self.check(fixture()), (2, 1))

    def test_duplicate_ids_rejected(self):
        data = fixture()
        data["stations"][1]["id"] = "OIII"
        with self.assertRaises(ValueError): self.check(data)

    def test_active_count_rejected(self):
        data = fixture()
        data["n_active"] = 0
        with self.assertRaises(ValueError): self.check(data)

    def test_invalid_coordinates_rejected(self):
        data = fixture()
        data["stations"][0]["lat"] = 999
        with self.assertRaises(ValueError): self.check(data)

    def test_broken_schema_rejected(self):
        with self.assertRaises(ValueError): self.check({"n": 1, "n_active": 0, "stations": "broken"})

    def test_dry_run_never_calls_git(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "data/obs/stations.json"
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps(fixture()), encoding="utf-8")
            with patch.object(p, "git", side_effect=AssertionError("No git command allowed")):
                self.assertEqual(p.main(["--checkout", td]), 0)

    def test_non_main_ref_cannot_publish(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "data/obs/stations.json"
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps(fixture()), encoding="utf-8")
            with patch.dict("os.environ", {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/test"}):
                with patch.object(p, "git", side_effect=AssertionError("No git command allowed")):
                    with self.assertRaises(RuntimeError):
                        p.main(["--checkout", td, "--commit"])


if __name__ == "__main__":
    unittest.main()
