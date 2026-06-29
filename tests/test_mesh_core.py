"""
test_mesh_core.py — mesh_core.py 模块单元测试

测试覆盖：_jacobi_svd_3x3, _kabsch_index_aligned (numpy 路径),
MeshMergeResult, 已知变换验证。

注意：纯 Python Jacobi SVD (_jacobi_svd_3x3) 仅对对称矩阵正确，
通用矩阵的 Kabsch 需 numpy 路径。纯 Python 回退路径的 bug 已报告。
"""

import sys
import os
import unittest
import math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401

import SimpleBleModlePlugin.mesh_core as mesh_core
from SimpleBleModlePlugin.mesh_core import (
    _jacobi_svd_3x3,
    _kabsch_index_aligned,
    MeshMergeResult,
)


# ── 辅助：生成非共线、良好分布的点集 ──
def make_well_distributed_verts(n=10, seed=42):
    """生成 n 个非共线、满秩的 3D 点集。"""
    rng = np.random.RandomState(seed)
    verts = rng.randn(n, 3).astype(np.float64) * 3.0
    # 确保至少 2 个不同方向有方差
    verts[:, 0] += np.arange(n, dtype=np.float64) * 0.5
    return verts.tolist()


def apply_transform(verts, angle_deg, axis, offset):
    """对点集应用绕指定轴的旋转 + 平移。"""
    theta = math.radians(angle_deg)
    c, s = math.cos(theta), math.sin(theta)
    verts_np = np.array(verts, dtype=np.float64)

    if axis == 'z':
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
    elif axis == 'y':
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
    elif axis == 'x':
        R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
    else:
        raise ValueError(f"Unknown axis: {axis}")

    t = np.array(offset, dtype=np.float64)
    transformed = (R @ verts_np.T).T + t
    return transformed.tolist()


class TestJacobiSVD(unittest.TestCase):
    """纯 Python Jacobi SVD 测试。

    已知限制：当前实现对非对称矩阵不正确 (BUG-003)。
    以下仅测试对称/对角矩阵的正确行为。
    """

    def test_identity_svd(self):
        """恒等矩阵 SVD 正确。"""
        A = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        U, S, Vt = _jacobi_svd_3x3(A)
        for s in S:
            self.assertAlmostEqual(s, 1.0, places=4)

    def test_diagonal_scale(self):
        """对角矩阵 SVD 正确。"""
        A = [[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 5.0]]
        U, S, Vt = _jacobi_svd_3x3(A)
        S_sorted = sorted(S, reverse=True)
        self.assertAlmostEqual(S_sorted[0], 5.0, places=4)

    @unittest.expectedFailure
    def test_symmetric_matrix_svd(self):
        """BUG-003: Jacobi SVD 对对称矩阵也错误。
        应产生正确的 SVD 重建，但当前失败。
        """
        A = [[4.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 2.0]]
        U, S, Vt = _jacobi_svd_3x3(A)
        A_rec = [[sum(U[i][k]*S[k]*Vt[k][j] for k in range(3))
                  for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(A[i][j], A_rec[i][j], places=3)

    def test_singular_values_non_negative(self):
        """奇异值非负。"""
        A = [[1.5, 0.2, -0.3], [0.4, 2.1, 0.1], [-0.2, 0.3, 1.8]]
        U, S, Vt = _jacobi_svd_3x3(A)
        for s in S:
            self.assertGreaterEqual(s, 0.0)


class TestKabschNumpy(unittest.TestCase):
    """Kabsch 算法测试（numpy 路径 — 主要路径）。"""

    def setUp(self):
        self._orig = mesh_core.USE_NUMPY
        mesh_core.USE_NUMPY = True

    def tearDown(self):
        mesh_core.USE_NUMPY = self._orig

    def test_identity_well_distributed(self):
        """相同点集（良好分布）→ 恒等变换。"""
        verts = make_well_distributed_verts(10, seed=1)
        R, t = _kabsch_index_aligned(verts, verts)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(float(R[i][j]), 1.0 if i == j else 0.0, places=4)
        for i in range(3):
            self.assertAlmostEqual(float(t[i]), 0.0, places=4)

    def test_pure_translation(self):
        """纯平移（已知平移量）。"""
        verts = make_well_distributed_verts(6, seed=2)
        offset = [5.0, -3.0, 2.0]
        slave = [[v[0]+offset[0], v[1]+offset[1], v[2]+offset[2]] for v in verts]
        R, t = _kabsch_index_aligned(verts, slave)
        for i in range(3):
            self.assertAlmostEqual(float(t[i]), offset[i], places=4)

    def test_pure_rotation_90_z(self):
        """绕 Z 轴 90° 旋转。"""
        verts = make_well_distributed_verts(6, seed=3)
        slave = apply_transform(verts, 90, 'z', [0, 0, 0])
        R, t = _kabsch_index_aligned(verts, slave)
        theta = math.radians(90)
        c, s = math.cos(theta), math.sin(theta)
        expected = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(float(R[i][j]), expected[i][j], places=3)

    def test_combined_rotation_translation(self):
        """旋转 + 平移组合变换。"""
        verts = make_well_distributed_verts(8, seed=4)
        slave = apply_transform(verts, 30, 'z', [10.0, -5.0, 3.0])
        R, t = _kabsch_index_aligned(verts, slave)
        # 验证对齐精度
        for i in range(len(verts)):
            aligned = [
                float(R[0][0]*verts[i][0]+R[0][1]*verts[i][1]+R[0][2]*verts[i][2]+t[0]),
                float(R[1][0]*verts[i][0]+R[1][1]*verts[i][1]+R[1][2]*verts[i][2]+t[1]),
                float(R[2][0]*verts[i][0]+R[2][1]*verts[i][1]+R[2][2]*verts[i][2]+t[2]),
            ]
            for d in range(3):
                self.assertAlmostEqual(aligned[d], slave[i][d], places=3)

    def test_determinant_positive(self):
        """R 行列式为正（已修正反射）。"""
        verts = make_well_distributed_verts(8, seed=5)
        slave = apply_transform(verts, 45, 'y', [0.1, -0.1, 0.05])
        R, t = _kabsch_index_aligned(verts, slave)
        det = (float(R[0][0])*(float(R[1][1])*float(R[2][2])-float(R[1][2])*float(R[2][1]))
               - float(R[0][1])*(float(R[1][0])*float(R[2][2])-float(R[1][2])*float(R[2][0]))
               + float(R[0][2])*(float(R[1][0])*float(R[2][1])-float(R[1][1])*float(R[2][0])))
        self.assertGreater(det, -1e-8)

    def test_large_dataset(self):
        """100 点大数据集验证。"""
        verts = make_well_distributed_verts(100, seed=42)
        slave = apply_transform(verts, 45, 'z', [1.0, -2.0, 3.0])
        R, t = _kabsch_index_aligned(verts, slave)
        theta = math.radians(45)
        c, s = math.cos(theta), math.sin(theta)
        expected_R = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(float(R[i][j]), expected_R[i][j], places=3)
        self.assertAlmostEqual(float(t[0]), 1.0, places=3)
        self.assertAlmostEqual(float(t[1]), -2.0, places=3)
        self.assertAlmostEqual(float(t[2]), 3.0, places=3)


class TestKabschReflection(unittest.TestCase):
    """反射修正测试。"""

    def setUp(self):
        self._orig = mesh_core.USE_NUMPY
        mesh_core.USE_NUMPY = True

    def tearDown(self):
        mesh_core.USE_NUMPY = self._orig

    def test_reflection_corrected(self):
        """包含反射的点集 → Kabsch 修正为纯旋转。"""
        verts = make_well_distributed_verts(6, seed=7)
        # 添加镜像（X 翻转）
        slave = [[-v[0], v[1], v[2]] for v in verts]
        R, t = _kabsch_index_aligned(verts, slave)
        det = (float(R[0][0])*(float(R[1][1])*float(R[2][2])-float(R[1][2])*float(R[2][1]))
               - float(R[0][1])*(float(R[1][0])*float(R[2][2])-float(R[1][2])*float(R[2][0]))
               + float(R[0][2])*(float(R[1][0])*float(R[2][1])-float(R[1][1])*float(R[2][0])))
        self.assertGreater(det, -1e-8)


class TestMeshMergeResult(unittest.TestCase):
    """MeshMergeResult dataclass 测试。"""

    def test_defaults(self):
        r = MeshMergeResult()
        self.assertEqual(r.reassigned, 0)
        self.assertEqual(r.errors, 0)

    def test_to_dict(self):
        r = MeshMergeResult(reassigned=5, pos_compensated=2, orphans_removed=3,
                            error_details=[{"object_name": "x", "reason": "test"}])
        d = r.to_dict()
        self.assertEqual(d["reassigned"], 5)
        self.assertEqual(d["orphans_removed"], 3)
        self.assertEqual(len(d["error_details"]), 1)

    def test_to_dict_keys(self):
        d = MeshMergeResult().to_dict()
        expected = {"reassigned", "pos_compensated", "rot_compensated",
                    "skipped", "errors", "orphans_removed", "error_details"}
        self.assertEqual(set(d.keys()), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
