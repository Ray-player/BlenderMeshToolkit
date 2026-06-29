"""
test_coordinate.py — coordinate.py 模块单元测试

测试覆盖：round_list, matrix_rows, compose_matrix, serialize_*,
CoordinateConverter 全部静态方法, round-trip 一致性, 引擎注册表。
"""

import sys
import os
import unittest
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401

from SimpleBleModlePlugin.coordinate import (
    round_list,
    matrix_rows,
    compose_matrix,
    serialize_blender_transform,
    serialize_ue5_transform,
    CoordinateConverter,
)
from mathutils import Matrix, Vector, Quaternion


class TestRoundList(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(round_list([1.234567, 2.345678, 3.456789], 4),
                         [1.2346, 2.3457, 3.4568])

    def test_integers(self):
        self.assertEqual(round_list([1.0, 2.0, 3.0], 2), [1.0, 2.0, 3.0])

    def test_negative(self):
        self.assertEqual(round_list([-1.234567, -2.345678], 4), [-1.2346, -2.3457])

    def test_empty(self):
        self.assertEqual(round_list([], 4), [])

    def test_default_digits(self):
        self.assertEqual(round_list([1.12345678]), [1.123457])


class TestMatrixRows(unittest.TestCase):
    def test_identity(self):
        m = Matrix.Identity(4)
        rows = matrix_rows(m, 4)
        for i in range(4):
            for j in range(4):
                self.assertEqual(rows[i][j], 1.0 if i == j else 0.0)


class TestComposeMatrix(unittest.TestCase):
    def test_identity(self):
        m = compose_matrix(Vector((0, 0, 0)), Quaternion((1, 0, 0, 0)), Vector((1, 1, 1)))
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(m[i][j], 1.0 if i == j else 0.0, places=4)

    def test_translation_only(self):
        m = compose_matrix(Vector((5, 10, 15)), Quaternion((1, 0, 0, 0)), Vector((1, 1, 1)))
        self.assertAlmostEqual(m[0][3], 5, places=4)
        self.assertAlmostEqual(m[1][3], 10, places=4)
        self.assertAlmostEqual(m[2][3], 15, places=4)


class TestSerializeBlenderTransform(unittest.TestCase):
    def test_identity(self):
        result = serialize_blender_transform(Matrix.Identity(4))
        self.assertEqual(result["location"], [0.0, 0.0, 0.0])
        self.assertEqual(result["scale"], [1.0, 1.0, 1.0])


class TestCoordinateConverterRegistration(unittest.TestCase):
    def setUp(self):
        self._original = dict(CoordinateConverter.ENGINE_PRESETS)

    def tearDown(self):
        CoordinateConverter.ENGINE_PRESETS = self._original

    def test_default_presets(self):
        self.assertIn("BLENDER", CoordinateConverter.ENGINE_PRESETS)
        self.assertIn("UE5", CoordinateConverter.ENGINE_PRESETS)

    def test_get_ue5(self):
        p = CoordinateConverter.get_converter("UE5")
        self.assertEqual(p["unit_scale"], 100.0)
        self.assertEqual(p["axis_map"], (1, 0, 2))

    def test_get_blender(self):
        p = CoordinateConverter.get_converter("BLENDER")
        self.assertEqual(p["unit_scale"], 1.0)
        self.assertEqual(p["axis_map"], (0, 1, 2))

    def test_unknown_fallback(self):
        p = CoordinateConverter.get_converter("NonExistent")
        self.assertEqual(p["axis_map"], (0, 1, 2))

    def test_register_new(self):
        CoordinateConverter.register_engine("Test", {
            "up": "Y", "handedness": "right", "unit_scale": 1.0, "axis_map": (2, 0, 1)})
        self.assertEqual(CoordinateConverter.get_converter("Test")["axis_map"], (2, 0, 1))


class TestBlenderLocToUE5(unittest.TestCase):
    def test_origin(self):
        self.assertEqual(CoordinateConverter.blender_loc_to_ue5(0, 0, 0), [0.0, 0.0, 0.0])

    def test_unit_x(self):
        self.assertEqual(CoordinateConverter.blender_loc_to_ue5(1.0, 0.0, 0.0), [0.0, 100.0, 0.0])

    def test_unit_y(self):
        self.assertEqual(CoordinateConverter.blender_loc_to_ue5(0.0, 1.0, 0.0), [100.0, 0.0, 0.0])

    def test_unit_z(self):
        self.assertEqual(CoordinateConverter.blender_loc_to_ue5(0.0, 0.0, 1.0), [0.0, 0.0, 100.0])

    def test_negative(self):
        self.assertEqual(CoordinateConverter.blender_loc_to_ue5(-1.0, -2.0, -3.0),
                         [-200.0, -100.0, -300.0])


class TestBlenderQuatToUE5(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(CoordinateConverter.blender_quat_to_ue5(1.0, 0.0, 0.0, 0.0),
                         [1.0, 0.0, 0.0, 0.0])

    def test_axis_swap(self):
        self.assertEqual(CoordinateConverter.blender_quat_to_ue5(0.5, 0.1, 0.2, 0.3),
                         [0.5, 0.2, 0.1, 0.3])


class TestBlenderScaleToUE5(unittest.TestCase):
    def test_uniform(self):
        self.assertEqual(CoordinateConverter.blender_scale_to_ue5(1.0, 1.0, 1.0), [1.0, 1.0, 1.0])

    def test_swap(self):
        self.assertEqual(CoordinateConverter.blender_scale_to_ue5(2.0, 3.0, 4.0), [3.0, 2.0, 4.0])

    def test_negative(self):
        self.assertEqual(CoordinateConverter.blender_scale_to_ue5(-1.0, 1.0, 1.0), [1.0, -1.0, 1.0])


class TestConvertLocation(unittest.TestCase):
    def test_same_engine(self):
        self.assertEqual(CoordinateConverter.convert_location([1.0, 2.0, 3.0], "BLENDER", "BLENDER"),
                         [1.0, 2.0, 3.0])

    def test_bl_to_ue5(self):
        self.assertEqual(CoordinateConverter.convert_location([1.0, 0.0, 0.0], "BLENDER", "UE5"),
                         [0.0, 100.0, 0.0])

    def test_round_trip_bl_ue5(self):
        original = [1.0, 2.0, 3.0]
        ue5 = CoordinateConverter.convert_location(original, "BLENDER", "UE5")
        back = CoordinateConverter.convert_location(ue5, "UE5", "BLENDER")
        for a, b in zip(original, back):
            self.assertAlmostEqual(a, b, places=2)


class TestConvertRotation(unittest.TestCase):
    def test_same_engine(self):
        self.assertEqual(CoordinateConverter.convert_rotation([0.5, 0.5, 0.5, 0.5], "BLENDER", "BLENDER"),
                         [0.5, 0.5, 0.5, 0.5])

    def test_identity_bl_to_ue5(self):
        self.assertEqual(CoordinateConverter.convert_rotation([1.0, 0.0, 0.0, 0.0], "BLENDER", "UE5"),
                         [1.0, 0.0, 0.0, 0.0])

    def test_bl_to_ue5_swap(self):
        """BLENDER→UE5 正确交换 X↔Y 分量。"""
        result = CoordinateConverter.convert_rotation([0.5, 0.1, 0.2, 0.3], "BLENDER", "UE5")
        self.assertEqual(result, [0.5, 0.2, 0.1, 0.3])

    @unittest.expectedFailure
    def test_round_trip_bl_ue5_to_bl(self):
        """BUG-001: convert_rotation() 通用路径不处理逆向转换。
        BLENDER→UE5→BLENDER 应恢复原值，但当前失败。
        """
        original = [0.7071, 0.7071, 0.0, 0.0]
        ue5 = CoordinateConverter.convert_rotation(original, "BLENDER", "UE5")
        back = CoordinateConverter.convert_rotation(ue5, "UE5", "BLENDER")
        for a, b in zip(original, back):
            self.assertAlmostEqual(a, b, places=3)


class TestConvertScale(unittest.TestCase):
    def test_same_engine(self):
        self.assertEqual(CoordinateConverter.convert_scale([2.0, 3.0, 4.0], "BLENDER", "BLENDER"),
                         [2.0, 3.0, 4.0])

    def test_bl_to_ue5(self):
        self.assertEqual(CoordinateConverter.convert_scale([2.0, 3.0, 4.0], "BLENDER", "UE5"),
                         [3.0, 2.0, 4.0])

    @unittest.expectedFailure
    def test_round_trip_bl_ue5_to_bl(self):
        """BUG-002: convert_scale() 通用路径不处理逆向转换。
        BLENDER→UE5→BLENDER 应恢复原值，但当前失败。
        """
        original = [2.5, 1.5, 3.0]
        ue5 = CoordinateConverter.convert_scale(original, "BLENDER", "UE5")
        back = CoordinateConverter.convert_scale(ue5, "UE5", "BLENDER")
        for a, b in zip(original, back):
            self.assertAlmostEqual(a, b, places=4)


class TestConvertMatrix(unittest.TestCase):
    def test_identity_same_engine(self):
        m = Matrix.Identity(4)
        result = CoordinateConverter.convert_matrix(m, "BLENDER", "BLENDER")
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(result[i][j], 1.0 if i == j else 0.0, places=4)

    def test_round_trip(self):
        m = compose_matrix(Vector((3, 5, 7)), Quaternion((0.9239, 0, 0, 0.3827)), Vector((1, 1, 1)))
        ue5_m = CoordinateConverter.convert_matrix(m, "BLENDER", "UE5")
        back_m = CoordinateConverter.convert_matrix(ue5_m, "UE5", "BLENDER")
        loc, _, _ = back_m.decompose()
        self.assertAlmostEqual(loc.x, 3, places=1)
        self.assertAlmostEqual(loc.y, 5, places=1)
        self.assertAlmostEqual(loc.z, 7, places=1)


class TestSerializeUE5Transform(unittest.TestCase):
    def test_identity(self):
        result = serialize_ue5_transform(Matrix.Identity(4))
        self.assertEqual(result["location"], [0.0, 0.0, 0.0])
        self.assertEqual(result["scale"], [1.0, 1.0, 1.0])


class TestCoordinateSystemProperties(unittest.TestCase):
    def test_ue5_left_handed(self):
        self.assertEqual(CoordinateConverter.get_converter("UE5")["handedness"], "left")

    def test_blender_right_handed(self):
        self.assertEqual(CoordinateConverter.get_converter("BLENDER")["handedness"], "right")

    def test_axis_map_is_permutation(self):
        for engine in ("BLENDER", "UE5"):
            self.assertEqual(sorted(CoordinateConverter.get_converter(engine)["axis_map"]), [0, 1, 2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
