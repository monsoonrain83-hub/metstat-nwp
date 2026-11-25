"""Exercise the actual inline extraction code from apply-bundle.yml, offline."""
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/apply-bundle.yml"
CODE = textwrap.dedent(WORKFLOW.read_text().split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])

class BundleGateTests(unittest.TestCase):
    def exercise(self, entries, setup=None):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            if setup:
                setup(root)
            with zipfile.ZipFile(root / "bundle_test.zip", "w") as z:
                for name, value in entries:
                    z.writestr(name, value)
            code = CODE.replace("/tmp/applied.txt", str(root / "applied.txt"))
            run = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True)
            return run.returncode, (root / "good.py").exists()

    def test_valid(self):
        self.assertEqual(self.exercise([("good.py", "x = 1")]), (0, True))

    def test_reject_entire_bundle_before_write(self):
        for name in ("../bad.py", ".github/bad.yml", "nwp_upload.php", "bad file.py", "/bad.py", "x\\bad.py"):
            with self.subTest(name=name):
                status, wrote = self.exercise([("good.py", "x=1"), (name, "x=2")])
                self.assertNotEqual(status, 0)
                self.assertFalse(wrote)

    def test_symlink_parent(self):
        def setup(root):
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
        status, wrote = self.exercise([("good.py","x=1"),("link/bad.py","x=2")], setup)
        self.assertNotEqual(status, 0)
        self.assertFalse(wrote)

if __name__ == "__main__":
    unittest.main()
