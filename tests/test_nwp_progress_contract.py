"""Offline contract for model progress metadata consumed by the website."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PHP = (ROOT / 'nwp_upload.php').read_text(encoding='utf-8')
PY = (ROOT / 'nwp_maps.py').read_text(encoding='utf-8')

class NWPProgressContract(unittest.TestCase):
    def test_horizon_sent_from_model(self):
        self.assertIn("prov=M['prov'], horizon=hz", PY)
        self.assertIn("'horizon' => max(0, min(1000, (int)($inf['horizon'] ?? 0)))", PHP)

    def test_manifest_exposes_maxlead(self):
        self.assertIn("'maxlead' => (int)($S['maxlead'] ?? 0)", PHP)
        self.assertIn("$S['maxlead'] = max((int)($S['maxlead'] ?? 0), (int)($meta['s'] ?? 0))", PHP)

    def test_new_upload_reopens_stale_completed_run(self):
        self.assertIn("if (($S['status'] ?? '') === 'complete') { $S['status'] = 'downloading'; unset($S['ended']); }", PHP)

if __name__ == '__main__': unittest.main()
