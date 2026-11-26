import unittest
import numpy as np
from mm_field_qc import prepare_field, validate_blend_payloads, MultiModelFieldError
from mm_maps import MMCombiner

class TestMMCellQC(unittest.TestCase):
    def setUp(self):
        self.mm = MMCombiner.__new__(MMCombiner)
        self.w = {'ecmwf': .6, 'gfs': .3, 'gem': .1}
        self.a = {'ecmwf': np.array([[10.,10.,np.nan],[10.,0.,10.]]),
                  'gfs': np.array([[20.,20.,20.],[np.nan,0.,20.]]),
                  'gem': np.array([[40.,np.nan,40.],[40.,0.,40.]])}

    def test_cell_weights_and_missingness(self):
        out = self.mm.combine('w', self.w, self.a, 'p24')
        np.testing.assert_allclose(out, [[16.,14.,np.nan],[np.nan,0.,16.]], equal_nan=True)

    def test_categorical_missing_core_is_not_class_zero(self):
        a = {'ecmwf': np.array([[2.,np.nan],[2.,2.]]),
             'gfs': np.array([[1.,1.],[np.nan,1.]]),
             'gem': np.ones((2,2))}
        np.testing.assert_allclose(self.mm.combine('w', self.w, a, 'sigwx'),
                                   [[2.,np.nan],[np.nan,2.]], equal_nan=True)

    def test_reject_wrong_nominal_weight(self):
        with self.assertRaises(MultiModelFieldError):
            self.mm.combine('w', {'ecmwf':.5,'gfs':.4,'gem':.1}, self.a, 'p24')

    def test_zero_precipitation_is_valid(self):
        self.assertEqual(prepare_field(np.zeros((3,3))).sum(), 0.)

    def test_invalid_fields(self):
        for a in (np.ones((1,2)), np.full((3,3), np.nan), np.full((3,3), np.inf), np.ones((3,3,3))):
            with self.subTest(shape=a.shape):
                with self.assertRaises(MultiModelFieldError):
                    prepare_field(a)

    def test_mismatched_grids_and_optional_wind(self):
        for payload in ({'ecmwf':{'f':np.ones((2,2))},'gfs':{'f':np.ones((3,2))}},
                        {'ecmwf':{'f':np.ones((2,2)),'bu':np.ones((3,2))}}):
            with self.assertRaises(MultiModelFieldError):
                validate_blend_payloads(payload)

    def test_sparse_warning_not_treated_as_empty(self):
        a=np.full((20,20),np.nan);a[1,1]=3
        with self.assertRaises(MultiModelFieldError):
            prepare_field(a)
        self.assertEqual(prepare_field(a,min_fraction=0)[1,1],3)

    def test_masked_values_remain_missing(self):
        a=np.ma.array(np.ones((2,2)),mask=[[0,1],[0,0]])
        self.assertTrue(np.isnan(prepare_field(a)[0,1]))

if __name__ == '__main__':
    unittest.main()
