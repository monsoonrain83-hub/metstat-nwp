"""V117: host-pinned GDPS no longer depends on Open-Meteo discovery."""
import tempfile, unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import global_nwp_stage as G

RUN=datetime(2026,11,26,12,tzinfo=timezone.utc)

class PinnedGem(unittest.TestCase):
    def test_official_all_fields_no_intermediary_initialization(self):
        with tempfile.TemporaryDirectory() as td, \
                patch.object(G,'official_gem_products',return_value=({p:{'field_source_domain':'msc_gdps_official','width':2400,'height':1201} for p in G.FIELDS},'unused')) as official, \
                patch.object(G.N,'S3Source',side_effect=RuntimeError('intermediary unavailable')) as source:
            m=G.acquire('gem',Path(td),24,RUN)
            official.assert_called_once()
            self.assertEqual(official.call_args.args[:2],(RUN,RUN+timedelta(hours=24)))
            source.assert_not_called()
            self.assertEqual(set(m['fields']),set(G.FIELDS))
    def test_partial_official_survives_intermediary_failure(self):
        with tempfile.TemporaryDirectory() as td, \
                patch.object(G,'official_gem_products',return_value=({'t2m':{'field_source_domain':'msc_gdps_official','width':2400,'height':1201}},'no remaining fields')) as official, \
                patch.object(G.N,'S3Source',side_effect=RuntimeError('intermediary unavailable')) as source:
            m=G.acquire('gem',Path(td),48,RUN)
            source.assert_called_once()
            self.assertEqual(official.call_args.args[:2],(RUN,RUN+timedelta(hours=48)))
            self.assertEqual(set(m['fields']),{'t2m'})
    def test_no_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td, \
                patch.object(G,'official_gem_products',return_value=({},'missing')), \
                patch.object(G.N,'S3Source',side_effect=RuntimeError('intermediary unavailable')):
            with self.assertRaisesRegex(RuntimeError,'no valid global arrays'):
                G.acquire('gem',Path(td),24,RUN)
            self.assertFalse((Path(td)/'manifest.json').exists())

if __name__=='__main__':unittest.main()
