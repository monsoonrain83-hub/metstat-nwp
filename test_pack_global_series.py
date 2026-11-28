"""Offline storage transaction tests with real WebP fixtures (not forecast evidence)."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

from pack_global_series import publish
from pack_global_products import EXPECTED_UNITS

FIELDS = sorted(EXPECTED_UNITS)
VARS = {"t2m": "temperature_2m", "z500": "geopotential_height_500hPa",
        "mslp": "pressure_msl"}


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "store"
        self.model = self.root / "gfs"
        self.run = datetime(2026, 11, 27, tzinfo=timezone.utc)
        self.plan = [24, 360]
        self.cap = 20 * 1024 * 1024
        image = Image.new("RGB", (720, 361))
        image.putdata([((x * 7 + y) % 256, (x + y * 3) % 256, y % 256)
                       for y in range(361) for x in range(720)])
        path = self.base / "fixture.webp"
        image.save(path, format="WEBP", lossless=True)
        self.raster = path.read_bytes()
        self.assertGreater(len(self.raster), 100)

    def source(self, n):
        run = self.run + timedelta(hours=12*n)
        src = self.base / ("src" + str(n))
        src.mkdir()
        leads = {}
        for h in self.plan:
            folder = src / f"f{h:03d}"
            folder.mkdir()
            valid = run + timedelta(hours=h)
            fields = {}
            for p in FIELDS:
                name = f"gfs_{p}_{valid:%Y%m%d%H}.webp"
                (folder / name).write_bytes(self.raster)
                fields[p] = {"file": name, "variable": VARS[p],
                    "logical_model": "gfs", "init_utc": stamp(run), "valid_utc": stamp(valid),
                    "lead_hours": h, "units": EXPECTED_UNITS[p], "field_source_domain": "ncep_gfs025",
                    "nominal_resolution": "28 km", "width": 720, "height": 361,
                    "source_grid": [720, 361], "source_grid_origin": [-180,-90],
                    "source_grid_spacing": [.5,.5], "finite_fraction": 1,
                    "sha256": hashlib.sha256(self.raster).hexdigest()}
            dump(folder / "manifest.json", {"schema": 2, "model": "gfs",
                "full_globe": True, "mock": False, "bbox_wgs84": [-180,-90,180,90],
                "projection": "EPSG:4326 equirectangular", "longitude_orientation": "west_to_east",
                "latitude_orientation": "north_to_south", "init_utc": stamp(run),
                "valid_utc": stamp(valid), "fields": fields})
            leads[str(h)] = {"status": "available", "available_fields": FIELDS,
                "missing_fields": [], "manifest": f"f{h:03d}/manifest.json"}
        dump(src / "series.json", {"schema": 1, "model": "gfs", "complete": True,
            "init_utc": stamp(run), "requested_leads": self.plan, "leads": leads})
        return src

    def put(self, src, cap=None):
        return publish(src,self.root,"gfs",self.plan,self.cap if cap is None else cap)

    def pointer(self):
        return (self.model / "catalog.json").read_bytes()

    def test_two_runs_after_third_success_only(self):
        a = self.put(self.source(0))
        permanent = self.root / "permanent"
        permanent.mkdir()
        (permanent / "keep").touch()
        unknown = self.model / "unmanaged"
        unknown.mkdir()
        b = self.put(self.source(1))
        self.assertEqual(b["runs"], [b["latest"], a["latest"]])
        c = self.put(self.source(2))
        self.assertEqual(c["runs"], [c["latest"], b["latest"]])
        self.assertFalse((self.model / a["latest"]).exists())
        self.assertTrue((self.model / b["latest"]).is_dir())
        self.assertTrue((permanent / "keep").exists())
        self.assertTrue(unknown.exists())
        self.assertEqual((self.model / c["latest"] / "f360/t2m.webp").read_bytes(), self.raster)

    def test_corrupt_new_run_leaves_catalog_and_old_runs(self):
        a = self.put(self.source(0))
        b = self.put(self.source(1))
        before = self.pointer()
        src = self.source(2)
        frame = next((src / "f360").glob("*.webp"))
        frame.write_bytes(self.raster[:-1] + bytes([self.raster[-1] ^ 1]))
        with self.assertRaises(ValueError):
            self.put(src)
        self.assertEqual(self.pointer(), before)
        for r in (a["latest"],b["latest"]):
            self.assertTrue((self.model/r).exists())
        self.assertFalse(list(self.model.glob(".incoming-*")))

    def test_low_budget_never_prunes_previous(self):
        self.put(self.source(0))
        before = self.pointer()
        with self.assertRaises(RuntimeError):
            self.put(self.source(1), cap=1)
        self.assertEqual(self.pointer(),before)

    def test_incomplete_plan_rejected(self):
        src = self.source(0)
        plan = json.loads((src/"series.json").read_text())
        plan["requested_leads"] = [24]
        del plan["leads"]["360"]
        dump(src/"series.json",plan)
        with self.assertRaisesRegex(ValueError,"lead inventory"):
            self.put(src)

    def test_older_cycle_cannot_replace_latest(self):
        self.put(self.source(1))
        before = self.pointer()
        with self.assertRaisesRegex(ValueError,"not newer"):
            self.put(self.source(0))
        self.assertEqual(self.pointer(),before)

    def test_wrong_variable_rejected(self):
        src = self.source(0)
        path = src/"f024/manifest.json"
        man = json.loads(path.read_text())
        man["fields"]["t2m"]["variable"]="pressure_msl"
        dump(path,man)
        with self.assertRaisesRegex(ValueError,"physical variable"):
            self.put(src)

    def test_symlink_raster_rejected(self):
        src = self.source(0)
        path = next((src/"f024").glob("*.webp"))
        target = self.base/"outside.webp"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,"invalid raster"):
            self.put(src)

    def test_decode_dimensions_mismatch_rejected(self):
        src = self.source(0)
        path = src/"f024/manifest.json"
        man = json.loads(path.read_text())
        f = man["fields"]["t2m"]
        f.update(width=1440, source_grid=[1440,361], source_grid_spacing=[.25,.5])
        dump(path,man)
        with self.assertRaisesRegex(ValueError,"dimensions"):
            self.put(src)


if __name__ == "__main__":
    unittest.main()
