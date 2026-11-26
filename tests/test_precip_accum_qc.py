import unittest
import numpy as np
from precip_accum_qc import advance_total, window_total

class TestPrecipAccum(unittest.TestCase):
    def test_first_interval_zero_is_valid_missing_is_not(self):
        np.testing.assert_allclose(advance_total(None,[0,2,np.nan],first_interval=True),[0,2,np.nan],equal_nan=True)
    def test_missing_cell_does_not_become_dry(self):
        np.testing.assert_allclose(advance_total([1,2,3],[2,np.nan,0]),[3,np.nan,3],equal_nan=True)
        np.testing.assert_allclose(advance_total([3,np.nan,3],[1,1,1]),[4,np.nan,4],equal_nan=True)
    def test_late_start_and_time_gap(self):
        self.assertTrue(np.isnan(advance_total(None,[1,0])).all())
        self.assertTrue(np.isnan(advance_total([1,2],[3,4],contiguous=False)).all())
    def test_official_total_recovers_missing_intervals(self):
        np.testing.assert_allclose(advance_total([1,2],[3,4],contiguous=False,official=[8,np.nan]),[8,np.nan],equal_nan=True)
    def test_partial_official_preserves_valid_independent_sum(self):
        np.testing.assert_allclose(advance_total([1,2],[3,4],official=[8,np.nan]),[8,6],equal_nan=True)
    def test_invalid_and_tiny_negative_roundoff(self):
        np.testing.assert_allclose(advance_total(None,[np.inf,-1,-0.00001],first_interval=True),[np.nan,np.nan,0],equal_nan=True)
    def test_masked_input(self):
        np.testing.assert_allclose(advance_total(None,np.ma.array([2,3],mask=[0,1]),first_interval=True),[2,np.nan],equal_nan=True)
    def test_mismatched_shape(self):
        self.assertTrue(np.isnan(advance_total([1,2],[3])).all())
        self.assertIsNone(window_total([1,2],[1]))
    def test_window_reset_and_missing_endpoints(self):
        np.testing.assert_allclose(window_total([5,3,2,np.nan,0],[2,4,np.nan,1,0]),[3,np.nan,np.nan,np.nan,0],equal_nan=True)

if __name__ == '__main__':
    unittest.main()
