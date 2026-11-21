import json
import tempfile
import unittest
from pathlib import Path
from world_publish_freshness import check_candidate


class WorldFreshnessTests(unittest.TestCase):
    def write(self, root, model, cycle):
        p = root / model / "manifest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"model": model, "full_globe": True,
                                 "mock": False, "init_utc": cycle}), encoding="utf8")

    def setup_models(self, current, candidate):
        for m in ("gfs", "ecmwf", "gem"):
            self.write(current, m, "2026-11-21T12:00:00Z")
            self.write(candidate, m, "2026-11-21T18:00:00Z")

    def test_newer_cycles_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/"old",Path(td)/"new"
            self.setup_models(a,b)
            self.assertTrue(check_candidate(a,b))

    def test_equal_cycle_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/"old",Path(td)/"new"
            self.setup_models(a,b)
            self.write(b,"gem","2026-11-21T12:00:00Z")
            self.assertTrue(check_candidate(a,b))

    def test_single_stale_model_blocks_whole_publish(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/"old",Path(td)/"new"
            self.setup_models(a,b)
            self.write(b,"ecmwf","2026-11-21T00:00:00Z")
            with self.assertRaisesRegex(RuntimeError,"ecmwf.*stale"):
                check_candidate(a,b)

    def test_missing_current_model_allows_first_publish(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/"old",Path(td)/"new"
            self.setup_models(a,b)
            (a/"gfs"/"manifest.json").unlink()
            self.assertTrue(check_candidate(a,b))

    def test_malformed_existing_cycle_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/"old",Path(td)/"new"
            self.setup_models(a,b)
            self.write(a,"gem","invalid")
            with self.assertRaises(ValueError):
                check_candidate(a,b)

    def test_candidate_nonworld_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/"old",Path(td)/"new"
            self.setup_models(a,b)
            p=b/"gfs"/"manifest.json"
            obj=json.loads(p.read_text())
            obj["full_globe"]=False
            p.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):
                check_candidate(a,b)


if __name__ == "__main__":
    unittest.main()
