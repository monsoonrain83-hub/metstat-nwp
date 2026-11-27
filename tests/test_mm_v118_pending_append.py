"""Current-run immutable append regression; no host requests."""
import unittest
from publish_world_host import pending_plan,PublishError

RUN='2026112700';VALID='2026112800'
def rec(p='cape',run=RUN,sha='a'*64):
    f=f'world/{p}_{VALID}.webp'
    return dict(model='ecmwf',run=run,file=f,destination=f'online/data/nwp/ecmwf/{run}/{f}',meta={'sha256':sha})
def plan(*rows):
    return dict(records=list(rows),manifest='online/data/manifest.json',deploy=False,deferred=[])
def manifest(*rows,run=RUN):
    return dict(models={'ecmwf':{'run':run}},items=list(rows))
def item(p='cape',sha='a'*64,r='world'):
    return dict(m='ecmwf',r=r,p=p,v=VALID,g={'sha256':sha})

class Append(unittest.TestCase):
    def test_same_hash_no_rewrite(self):
        p,c=pending_plan(plan(rec()),manifest(item()))
        self.assertEqual(p['records'],[]);self.assertEqual(c['already_present'],1)
    def test_changed_hash_keep_existing(self):
        p,c=pending_plan(plan(rec()),manifest(item(sha='b'*64)))
        self.assertFalse(p['records']);self.assertEqual(c['immutable_conflicts'],1)
    def test_missing_hash_keep_existing(self):
        p,c=pending_plan(plan(rec()),manifest(item(sha=None)))
        self.assertFalse(p['records']);self.assertEqual(c['immutable_conflicts'],1)
    def test_only_regional_frame_does_not_hide_world(self):
        p,c=pending_plan(plan(rec()),manifest(item(r='me')))
        self.assertEqual(len(p['records']),1)
    def test_mixed_new_existing(self):
        p,c=pending_plan(plan(rec(),rec('ki')),manifest(item()))
        self.assertEqual(p['records'],[rec('ki')])
    def test_rotated_run_deferred(self):
        p,c=pending_plan(plan(rec()),manifest(run='2026112706'))
        self.assertFalse(p['records']);self.assertEqual(c['stale_frames'],1)
    def test_duplicate_existing_fails(self):
        with self.assertRaises(PublishError):
            pending_plan(plan(rec()),manifest(item(),item()))
    def test_path_change_fails(self):
        r=rec();r['destination']='world/cape.webp'
        with self.assertRaises(PublishError):
            pending_plan(plan(r),manifest())
if __name__=='__main__':unittest.main()
