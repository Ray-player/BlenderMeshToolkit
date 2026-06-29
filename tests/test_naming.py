"""
test_naming.py — naming.py 模块单元测试

测试覆盖：sanitize_ue5_name 边界输入、short_mesh_id 稳定性、
4种命名模式、辅助函数。
"""

import sys
import os
import unittest
import hashlib

# 确保 tests 包可导入并触发 __init__.py（安装 mocks + 预加载源模块）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401

from SimpleBleModlePlugin.naming import (
    sanitize_ue5_name,
    short_mesh_id,
    normalize_mesh_name,
    generate_mesh_asset_name,
    _classify_segment_chars,
    _segment_deletion_score,
    _remove_long_digit_segments,
    _shorten_prefix_by_priority,
    _truncate_with_word_priority,
    _build_shortid_prefix_name,
    LONG_DIGIT_THRESHOLD,
)


class TestSanitizeUE5Name(unittest.TestCase):
    """UE5 合规命名测试。"""

    def test_preserves_simple_ascii(self):
        self.assertEqual(sanitize_ue5_name("Cube"), "Cube")
        self.assertEqual(sanitize_ue5_name("SM_Cube_01"), "SM_Cube_01")

    def test_strips_illegal_chars(self):
        self.assertEqual(sanitize_ue5_name("Cube(1)"), "Cube1")
        # ASCII brackets stripped, Chinese chars preserved
        self.assertEqual(sanitize_ue5_name("Obj[副本]"), "Obj副本")
        self.assertEqual(sanitize_ue5_name('Obj"test"'), "Objtest")
        self.assertEqual(sanitize_ue5_name("Obj'test'"), "Objtest")
        self.assertEqual(sanitize_ue5_name("Obj「名称」"), "Obj名称")
        self.assertEqual(sanitize_ue5_name("Obj《name》"), "Objname")

    def test_replaces_separators(self):
        self.assertEqual(sanitize_ue5_name("Cube.Test"), "Cube_Test")
        self.assertEqual(sanitize_ue5_name("A*B?C"), "A_B_C")
        self.assertEqual(sanitize_ue5_name("file|path"), "file_path")
        self.assertEqual(sanitize_ue5_name("a/b\\c"), "a_b_c")
        self.assertEqual(sanitize_ue5_name("a,b;c"), "a_b_c")
        self.assertEqual(sanitize_ue5_name("a@b#c$d"), "a_b_c_d")
        self.assertEqual(sanitize_ue5_name("a b c"), "a_b_c")
        self.assertEqual(sanitize_ue5_name("a:b"), "a_b")
        self.assertEqual(sanitize_ue5_name("中国·北京"), "中国_北京")

    def test_collapses_double_underscores(self):
        self.assertEqual(sanitize_ue5_name("A__B"), "A_B")
        self.assertEqual(sanitize_ue5_name("A____B"), "A_B")
        self.assertEqual(sanitize_ue5_name("A.B.C"), "A_B_C")

    def test_strips_leading_trailing_underscores(self):
        self.assertEqual(sanitize_ue5_name("_Test_"), "Test")
        self.assertEqual(sanitize_ue5_name("___Test___"), "Test")
        self.assertEqual(sanitize_ue5_name("_"), "")

    def test_empty_string(self):
        self.assertEqual(sanitize_ue5_name(""), "")

    def test_only_illegal_chars(self):
        self.assertEqual(sanitize_ue5_name("()[]"), "")

    def test_only_underscores(self):
        self.assertEqual(sanitize_ue5_name("___"), "")

    def test_chinese_preserved(self):
        self.assertEqual(sanitize_ue5_name("立方体"), "立方体")

    def test_mixed_content(self):
        result = sanitize_ue5_name("SM_Wall(1).001*test")
        self.assertEqual(result, "SM_Wall1_001_test")


class TestShortMeshID(unittest.TestCase):
    """short_mesh_id() 稳定性测试。"""

    def test_deterministic(self):
        self.assertEqual(short_mesh_id("Cube"), short_mesh_id("Cube"))

    def test_different_inputs(self):
        self.assertNotEqual(short_mesh_id("Cube"), short_mesh_id("Sphere"))

    def test_format(self):
        sid = short_mesh_id("Cube")
        self.assertTrue(sid.startswith("M"))
        self.assertEqual(len(sid), 9)
        self.assertTrue(all(c in "0123456789abcdef" for c in sid[1:]))

    def test_matches_md5_prefix(self):
        name = "TestMeshName"
        expected = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]
        self.assertEqual(short_mesh_id(name), f"M{expected}")

    def test_empty_string(self):
        sid = short_mesh_id("")
        self.assertEqual(len(sid), 9)
        self.assertEqual(sid, f"M{hashlib.md5(b'').hexdigest()[:8]}")

    def test_unicode_input(self):
        sid = short_mesh_id("立方体")
        self.assertEqual(len(sid), 9)
        self.assertEqual(sid, f"M{hashlib.md5('立方体'.encode('utf-8')).hexdigest()[:8]}")


class TestNormalizeMeshName(unittest.TestCase):
    """normalize_mesh_name() 测试。"""

    def test_removes_double_underscore_suffix(self):
        self.assertEqual(normalize_mesh_name("Cube__001"), "Cube")
        self.assertEqual(normalize_mesh_name("Cube__123"), "Cube")

    def test_no_suffix_preserved(self):
        self.assertEqual(normalize_mesh_name("Cube"), "Cube")
        self.assertEqual(normalize_mesh_name("SM_Wall_01"), "SM_Wall_01")

    def test_empty_result_fallback(self):
        result = normalize_mesh_name("__123")
        self.assertEqual(result, "__123")


class TestGenerateMeshAssetName(unittest.TestCase):
    """generate_mesh_asset_name() 全部 4 种模式。"""

    def test_original_mode(self):
        name, sid = generate_mesh_asset_name("Cube", mode="ORIGINAL")
        self.assertTrue(name.startswith("SM_"))
        self.assertIn("Cube", name)

    def test_original_truncation(self):
        long_name = "A" * 200
        name, sid = generate_mesh_asset_name(long_name, mode="ORIGINAL", max_length=80)
        self.assertLessEqual(len(name), 80)

    def test_original_sanitizes(self):
        name, sid = generate_mesh_asset_name("Cube(1).Test", mode="ORIGINAL")
        self.assertEqual(name, "SM_Cube1_Test")

    def test_hash_mode(self):
        name, sid = generate_mesh_asset_name("MeshData", mode="HASH", glb_basename="SceneMeshes")
        self.assertTrue(name.startswith("SM_SceneMeshes_"))
        self.assertIn(sid, name)

    def test_hash_without_basename(self):
        name, sid = generate_mesh_asset_name("MyMesh", mode="HASH")
        self.assertTrue(name.startswith("SM_MyMesh_"))

    def test_prefix_hash_mode(self):
        name, sid = generate_mesh_asset_name("Wall_Segment", mode="HASH_PREFIX")
        self.assertTrue(name.startswith("SM_"))
        self.assertIn(sid, name)
        self.assertIn("Wall_Segment", name)

    def test_prefix_hash_truncation(self):
        long_prefix = "A_B_C_D_E_F_G_H_I_J_K_L_M_N_O_P_Q_R_S_T_U_V_W_X_Y_Z"
        name, sid = generate_mesh_asset_name(long_prefix, mode="HASH_PREFIX", max_length=80)
        self.assertLessEqual(len(name), 80)

    def test_shortid_prefix_default(self):
        name1, _ = generate_mesh_asset_name("Cube")
        name2, _ = generate_mesh_asset_name("Cube", mode="HASH_PREFIX")
        self.assertEqual(name1, name2)

    def test_shortid_prefix_empty_sanitized_fallback(self):
        name, sid = generate_mesh_asset_name("()[]", mode="HASH_PREFIX", glb_basename="Fallback")
        self.assertIn("Fallback", name)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError) as ctx:
            generate_mesh_asset_name("Cube", mode="INVALID_MODE")
        self.assertIn("未知的命名模式", str(ctx.exception))

    def test_max_length_all_modes(self):
        for mode in ("ORIGINAL", "HASH", "HASH_PREFIX"):
            name, _ = generate_mesh_asset_name(
                "Very_Long_Mesh_Name_Exceeds_Limits", mode=mode, max_length=30)
            self.assertLessEqual(len(name), 30, f"Mode={mode}")

    def test_returns_tuple(self):
        result = generate_mesh_asset_name("Cube")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], str)
        self.assertIsInstance(result[1], str)


class TestClassifySegmentChars(unittest.TestCase):
    def test_digits(self):
        d, e, c = _classify_segment_chars("12345")
        self.assertEqual((d, e, c), (5, 0, 0))

    def test_english(self):
        d, e, c = _classify_segment_chars("Hello")
        self.assertEqual((d, e, c), (0, 5, 0))

    def test_chinese(self):
        d, e, c = _classify_segment_chars("你好世界")
        self.assertEqual((d, e, c), (0, 0, 4))

    def test_mixed(self):
        d, e, c = _classify_segment_chars("abc123中文")
        self.assertEqual((d, e, c), (3, 3, 2))

    def test_empty(self):
        self.assertEqual(_classify_segment_chars(""), (0, 0, 0))


class TestSegmentDeletionScore(unittest.TestCase):
    def test_digits_higher_than_chinese(self):
        self.assertGreater(
            _segment_deletion_score("12345", 2, 5),
            _segment_deletion_score("中文", 2, 5))

    def test_head_higher_than_middle(self):
        self.assertGreater(
            _segment_deletion_score("A", 0, 6),
            _segment_deletion_score("B", 3, 6))


class TestRemoveLongDigitSegments(unittest.TestCase):
    def test_removes_long(self):
        long_num = "1" * (LONG_DIGIT_THRESHOLD + 1)
        result = _remove_long_digit_segments(f"A-{long_num}-B")
        self.assertNotIn(long_num, result)

    def test_keeps_short(self):
        short = "123456789"
        result = _remove_long_digit_segments(f"A-{short}-B")
        self.assertIn(short, result)


class TestShortenPrefixByPriority(unittest.TestCase):
    def test_no_shortening(self):
        # _shorten_prefix_by_priority splits on '-' and joins with '_'
        self.assertEqual(_shorten_prefix_by_priority("A-B-C", 100), "A_B_C")

    def test_single_segment(self):
        result = _shorten_prefix_by_priority("ABCDEFGHIJ", 5)
        self.assertEqual(len(result), 5)

    def test_removes_low_priority(self):
        # _shorten_prefix_by_priority splits on '-' (dash) not '_' (underscore)
        # Use dash-separated segments so the function can process them
        result = _shorten_prefix_by_priority(
            "12345678901-MainPart-Body-ExtraSegment", 30)
        # 长纯数字段 "12345678901" 评分最高 → 最先删除
        self.assertNotIn("12345678901", result)
        self.assertIn("MainPart", result)

    def test_within_max_length(self):
        result = _shorten_prefix_by_priority("A_B_C_D_E_F_G_H_I_J_K_L_M_N", 20)
        self.assertLessEqual(len(result), 20)


class TestTruncateWithWordPriority(unittest.TestCase):
    def test_no_truncation(self):
        self.assertEqual(_truncate_with_word_priority("Hello_World", 20), "Hello_World")

    def test_keeps_whole_words(self):
        result = _truncate_with_word_priority("AAA_BBB_CCC_DDD", 10)
        self.assertEqual(result, "AAA_BBB")

    def test_empty(self):
        self.assertEqual(_truncate_with_word_priority("", 10), "")


class TestBuildShortIDPrefixName(unittest.TestCase):
    def test_basic(self):
        name, sid = _build_shortid_prefix_name("Cube", 80)
        self.assertTrue(name.startswith("SM_"))
        self.assertIn(sid, name)
        self.assertIn("Cube", name)

    def test_very_short_max_length(self):
        name, sid = _build_shortid_prefix_name("VeryLongMeshName", 20)
        self.assertLessEqual(len(name), 20)

    def test_fallback_empty(self):
        name, sid = _build_shortid_prefix_name("()[]", 80, glb_basename="MyGLB")
        self.assertIn("MyGLB", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
