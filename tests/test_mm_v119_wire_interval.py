import unittest
from publish_world_host import wire_metadata,PublishError
class WireInterval(unittest.TestCase):
    def test_exact_enum(self):
        for h in (1.,3.,6.,1,3,6):
            m={'variable':'refl','interval_hours':h}
            result=wire_metadata(m)
            self.assertIs(type(result['interval_hours']),int)
            self.assertEqual(result['interval_hours'],h)
            self.assertIs(type(m['interval_hours']),type(h))
    def test_reject_non_native(self):
        for h in (1.5,2,True,'3',None):
            with self.assertRaises(PublishError):wire_metadata({'variable':'sigwx','interval_hours':h})
    def test_unchanged_other_product(self):
        m={'variable':'cape','lead_hours':24}
        self.assertEqual(wire_metadata(m),m)
if __name__=='__main__':unittest.main()
