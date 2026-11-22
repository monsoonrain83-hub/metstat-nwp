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

    def attach_fields(self, root, model, fields):
        p = root / model / 'manifest.json'
        obj = json.loads(p.read_text(encoding='utf8'))
        obj['fields'] = {
            param: {'field_source_domain': source}
            for param, source in fields.items()
        }
        p.write_text(json.dumps(obj), encoding='utf8')

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


    def test_same_cycle_cannot_downgrade_ecmwf_9km_to_28km(self):
        with tempfile.TemporaryDirectory() as td:
            current, candidate = Path(td)/'old', Path(td)/'new'
            self.setup_models(current, candidate)
            self.write(candidate, 'ecmwf', '2026-11-21T12:00:00Z')
            self.attach_fields(current, 'ecmwf', {'t2m': 'ecmwf_ifs'})
            self.attach_fields(candidate, 'ecmwf', {'t2m': 'ecmwf_ifs025'})
            with self.assertRaisesRegex(RuntimeError, 'resolution downgrade'):
                check_candidate(current, candidate)

    def test_same_cycle_hires_upgrade_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            current, candidate = Path(td)/'old', Path(td)/'new'
            self.setup_models(current, candidate)
            self.write(candidate, 'ecmwf', '2026-11-21T12:00:00Z')
            self.attach_fields(current, 'ecmwf', {'t2m': 'ecmwf_ifs025'})
            self.attach_fields(candidate, 'ecmwf', {'t2m': 'ecmwf_ifs'})
            self.assertTrue(check_candidate(current, candidate))

    def test_same_cycle_gfs_13km_cannot_be_overwritten_by_28km(self):
        with tempfile.TemporaryDirectory() as td:
            current, candidate = Path(td)/'old', Path(td)/'new'
            self.setup_models(current, candidate)
            self.write(candidate, 'gfs', '2026-11-21T12:00:00Z')
            self.attach_fields(current, 'gfs', {'z500': 'ncep_gfs013'})
            self.attach_fields(candidate, 'gfs', {'z500': 'ncep_gfs025'})
            with self.assertRaisesRegex(RuntimeError, 'resolution downgrade'):
                check_candidate(current, candidate)

    def test_newer_cycle_can_use_real_coarse_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            current, candidate = Path(td)/'old', Path(td)/'new'
            self.setup_models(current, candidate)
            self.attach_fields(current, 'ecmwf', {'t2m': 'ecmwf_ifs'})
            self.attach_fields(candidate, 'ecmwf', {'t2m': 'ecmwf_ifs025'})
            self.assertTrue(check_candidate(current, candidate))

    def test_newer_cycle_cannot_silently_drop_existing_field(self):
        with tempfile.TemporaryDirectory() as td:
            current, candidate = Path(td)/'old', Path(td)/'new'
            self.setup_models(current, candidate)
            self.attach_fields(current, 'ecmwf', {
                't2m': 'ecmwf_ifs', 'z500': 'ecmwf_ifs025'})
            self.attach_fields(candidate, 'ecmwf', {'t2m': 'ecmwf_ifs'})
            with self.assertRaisesRegex(RuntimeError, 'loss of published fields'):
                check_candidate(current, candidate)

    def test_unknown_domain_blocks_same_cycle_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            current, candidate = Path(td)/'old', Path(td)/'new'
            self.setup_models(current, candidate)
            self.write(candidate, 'ecmwf', '2026-11-21T12:00:00Z')
            self.attach_fields(current, 'ecmwf', {'t2m': 'ecmwf_ifs'})
            self.attach_fields(candidate, 'ecmwf', {'t2m': 'unverified_domain'})
            with self.assertRaisesRegex(ValueError, 'unverified source'):
                check_candidate(current, candidate)


if __name__ == "__main__":
    unittest.main()
