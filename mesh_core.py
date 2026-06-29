"""
mesh_core.py — 网格核心操作模块

拓扑验证、INDEX Kabsch 算法（numpy + 纯 Python SVD 回退）、
枢轴补偿、递归子集合并、孤立数据清理。
"""

import re
import math
from dataclasses import dataclass, field
from typing import Optional

import bpy
from mathutils import Matrix, Vector

from .logger import info, warn, error, summary as log_summary
from .naming import normalize_mesh_name
from .config import DEFAULT_LOC_THRESHOLD, DEFAULT_ROT_THRESHOLD

# ── numpy 可选导入 ──
try:
    import numpy as np
    USE_NUMPY = True
except ImportError:
    USE_NUMPY = False


# ═══════════════════════════════════════════
#  MergeResult
# ═══════════════════════════════════════════

@dataclass
class MeshMergeResult:
    """网格合并操作的结果统计。"""
    reassigned: int = 0
    pos_compensated: int = 0
    rot_compensated: int = 0
    skipped: int = 0
    errors: int = 0
    orphans_removed: int = 0
    error_details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为 dict，供日志/UI 使用。"""
        return {
            "reassigned":       self.reassigned,
            "pos_compensated":  self.pos_compensated,
            "rot_compensated":  self.rot_compensated,
            "skipped":          self.skipped,
            "errors":           self.errors,
            "orphans_removed":  self.orphans_removed,
            "error_details":    self.error_details,
        }


# ═══════════════════════════════════════════
#  纯 Python 3x3 Jacobi SVD（numpy 回退）
# ═══════════════════════════════════════════

def _jacobi_eigen_3x3(M: list[list[float]],
                      max_iter: int = 50) -> tuple[list[float], list[list[float]]]:
    """
    纯 Python 3×3 对称矩阵 Jacobi 特征分解。

    对对称矩阵 M 运行经典 Jacobi 对角化，返回特征值和特征向量。

    Args:
        M: 3×3 对称矩阵
        max_iter: 最大迭代次数

    Returns:
        (eigenvalues, eigenvectors) — 特征值列表(3,)降序、特征向量列矩阵(3×3)
    """
    # 复制 M 作为工作矩阵
    A = [[M[i][j] for j in range(3)] for i in range(3)]
    # V 初始为单位矩阵
    V = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]

    EPS = 1e-14

    for _ in range(max_iter):
        # 寻找绝对值最大的非对角线元素
        max_off = 0.0
        p, q = 0, 1
        for i in range(3):
            for j in range(i + 1, 3):
                if abs(A[i][j]) > max_off:
                    max_off = abs(A[i][j])
                    p, q = i, j

        if max_off < EPS:
            break

        # 计算 Jacobi 旋转角
        diff = A[p][p] - A[q][q]
        if abs(diff) > EPS:
            phi = 0.5 * math.atan2(2.0 * A[p][q], diff)
        else:
            phi = math.pi / 4.0

        c = math.cos(phi)
        s = math.sin(phi)

        # 更新 A：行旋转
        for k in range(3):
            a_pk = A[p][k]
            a_qk = A[q][k]
            A[p][k] = c * a_pk - s * a_qk
            A[q][k] = s * a_pk + c * a_qk

        # 更新 A：列旋转（对称）
        for k in range(3):
            a_kp = A[k][p]
            a_kq = A[k][q]
            A[k][p] = c * a_kp - s * a_kq
            A[k][q] = s * a_kp + c * a_kq

        # 更新特征向量矩阵 V
        for k in range(3):
            v_kp = V[k][p]
            v_kq = V[k][q]
            V[k][p] = c * v_kp - s * v_kq
            V[k][q] = s * v_kp + c * v_kq

    # 提取特征值（对角线）
    evals = [A[i][i] for i in range(3)]

    # 按特征值降序重排
    order = sorted(range(3), key=lambda i: abs(evals[i]), reverse=True)
    evals_sorted = [evals[i] for i in order]
    evecs_sorted = [[V[j][i] for i in order] for j in range(3)]

    return evals_sorted, evecs_sorted


def _jacobi_svd_3x3(A_mat: list[list[float]]) -> tuple[
    list[list[float]], list[float], list[list[float]]
]:
    """
    纯 Python 实现的 3×3 SVD，通过 A^T·A 特征分解。

    用于 numpy 不可用时的 Kabsch 计算回退。
    算法：对对称矩阵 A^T·A 做 Jacobi 特征分解得到 V 和 Σ²，
    再由 U_i = A·V_i / σ_i 构造 U。

    Args:
        A_mat: 3×3 矩阵

    Returns:
        (U, S, Vt) — U(3×3), 奇异值列表(3,), Vt(3×3)
    """
    EPS = 1e-14

    # 计算 A^T @ A
    ATA = [[0.0, 0.0, 0.0] for _ in range(3)]
    for i in range(3):
        for j in range(3):
            s = 0.0
            for k in range(3):
                s += A_mat[k][i] * A_mat[k][j]
            ATA[i][j] = s

    # Jacobi 特征分解 A^T A = V Σ² V^T
    evals, V = _jacobi_eigen_3x3(ATA)

    # 奇异值 = sqrt(特征值)，钳制非负
    S = [math.sqrt(max(0.0, evals[i])) for i in range(3)]

    # 构造 U 矩阵：U_i = A @ V_i / σ_i
    U = [[0.0, 0.0, 0.0] for _ in range(3)]
    for i in range(3):
        if S[i] > EPS:
            for r in range(3):
                acc = 0.0
                for k in range(3):
                    acc += A_mat[r][k] * V[k][i]
                U[r][i] = acc / S[i]
        else:
            # 零奇异值 → 与已算列正交的单位向量
            for r in range(3):
                U[r][i] = 1.0 if r == i else 0.0
            for j in range(i):
                dot = sum(U[r][j] * U[r][i] for r in range(3))
                for r in range(3):
                    U[r][i] -= dot * U[r][j]
            norm = math.sqrt(sum(U[r][i] ** 2 for r in range(3)))
            if norm > EPS:
                for r in range(3):
                    U[r][i] /= norm

    # 构建 Vt
    Vt = [[V[j][i] for j in range(3)] for i in range(3)]

    return U, S, Vt


def _pure_python_svd(H: list[list[float]]) -> tuple:
    """
    纯 Python SVD 入口，返回类似 numpy.linalg.svd 的结果。
    """
    U, S, Vt = _jacobi_svd_3x3(H)
    return U, S, Vt


# ═══════════════════════════════════════════
#  Kabsch 算法
# ═══════════════════════════════════════════

def _kabsch_index_aligned(
    master_verts: "list[list[float]]",
    slave_verts: "list[list[float]]",
) -> tuple:
    """
    顶点索引对应 Kabsch（同源拓扑专用）。

    寻找 (R, t) 满足: R @ master_verts[i] + t ≈ slave_verts[i]

    Args:
        master_verts: N×3 主网格顶点数组
        slave_verts:  N×3 从属网格顶点数组

    Returns:
        (R, t) — R (3×3), t (3,) 使得变换后 master_verts 对齐 slave_verts
    """
    if USE_NUMPY:
        src = np.array(master_verts, dtype=np.float64)
        tgt = np.array(slave_verts, dtype=np.float64)

        src_c = np.mean(src, axis=0)
        tgt_c = np.mean(tgt, axis=0)

        S_mat = src - src_c
        T_mat = tgt - tgt_c

        H_mat = S_mat.T @ T_mat  # (3×3)
        U_mat, _, Vt_mat = np.linalg.svd(H_mat)

        R_mat = Vt_mat.T @ U_mat.T
        if np.linalg.det(R_mat) < 0:  # 反射修正
            Vt_mat[2, :] *= -1
            R_mat = Vt_mat.T @ U_mat.T

        t_vec = tgt_c - R_mat @ src_c
        return R_mat, t_vec

    else:
        # 纯 Python 路径
        n = len(master_verts)
        src_c = [0.0, 0.0, 0.0]
        tgt_c = [0.0, 0.0, 0.0]
        for i in range(n):
            for d in range(3):
                src_c[d] += master_verts[i][d]
                tgt_c[d] += slave_verts[i][d]
        inv_n = 1.0 / n
        for d in range(3):
            src_c[d] *= inv_n
            tgt_c[d] *= inv_n

        S_mat = [[master_verts[i][d] - src_c[d] for d in range(3)]
                 for i in range(n)]
        T_mat = [[slave_verts[i][d] - tgt_c[d] for d in range(3)]
                 for i in range(n)]

        # H = S^T @ T (3×3)
        H = [[0.0, 0.0, 0.0] for _ in range(3)]
        for i in range(3):
            for j in range(3):
                total = 0.0
                for k in range(n):
                    total += S_mat[k][i] * T_mat[k][j]
                H[i][j] = total

        U, _, Vt = _pure_python_svd(H)

        # R = Vt^T @ U^T
        R = [[0.0, 0.0, 0.0] for _ in range(3)]
        for i in range(3):
            for j in range(3):
                total = 0.0
                for k in range(3):
                    total += Vt[k][i] * U[j][k]
                R[i][j] = total

        # 行列式
        det = (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1])
               - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
               + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))
        if det < 0:
            Vt[2][0] *= -1
            Vt[2][1] *= -1
            Vt[2][2] *= -1
            for i in range(3):
                for j in range(3):
                    total = 0.0
                    for k in range(3):
                        total += Vt[k][i] * U[j][k]
                    R[i][j] = total

        t = [0.0, 0.0, 0.0]
        for d in range(3):
            t[d] = tgt_c[d] - (R[d][0] * src_c[0] + R[d][1] * src_c[1]
                               + R[d][2] * src_c[2])

        # 返回类似 numpy 的形状
        return R, t


# ═══════════════════════════════════════════
#  MeshMerger（二次修改：仅添加注册方法）
# ═══════════════════════════════════════════

class MeshMerger:
    """网格数据共享合并器。

    将多个拓扑一致的对象切换为共享同一 mesh data，
    通过 INDEX Kabsch 补偿枢轴差异。
    """

    def __init__(self,
                 pos_threshold: float = DEFAULT_LOC_THRESHOLD,
                 rot_threshold: float = DEFAULT_ROT_THRESHOLD,
                 force_compensation: bool = False):
        """
        Args:
            pos_threshold: 位置补偿阈值 (m)
            rot_threshold: 旋转补偿阈值 (rad)
            force_compensation: 是否强制补偿（忽略阈值）
        """
        self.pos_threshold = pos_threshold
        self.rot_threshold = rot_threshold
        self.force_compensation = force_compensation

    # ── 拓扑验证 ──

    @staticmethod
    def _triangle_count(mesh) -> int:
        """统计三角形数（兼容 tris + quads/ngons）。"""
        count = 0
        for p in mesh.polygons:
            count += len(p.vertices) - 2
        return count

    @staticmethod
    def _validate_topology(mesh_a, mesh_b) -> bool:
        """
        验证两个 mesh data 拓扑是否一致。

        条件：顶点数相同（INDEX 对齐模式下即保证拓扑一致，
        三角形数可作为额外检查但不强制）。
        """
        return len(mesh_a.vertices) == len(mesh_b.vertices)

    # ── 枢轴补偿 ──

    def _compensate_pivot(self, obj: "bpy.types.Object",
                          R, t) -> None:
        """
        应用枢轴补偿：将 obj 的 world matrix 乘以补偿变换。

        构造 4×4 补偿矩阵 M_comp:
          将 master 局部空间顶点映射到 slave 局部空间顶点。
          obj.matrix_world = obj.matrix_world @ M_comp

        Args:
            obj: 待补偿的对象
            R: 3×3 旋转矩阵
            t: 3×1 平移向量
        """
        M = Matrix.Identity(4)
        for i in range(3):
            for j in range(3):
                M[i][j] = R[i][j] if USE_NUMPY else R[i][j]
        if USE_NUMPY:
            for i in range(3):
                M[i][3] = float(t[i])
        else:
            for i in range(3):
                M[i][3] = t[i]

        obj.matrix_world = obj.matrix_world @ M

    # ── 孤立数据清理 ──

    @staticmethod
    def _clean_orphans(orphan_names: list[str]) -> int:
        """
        删除 users == 0 的 mesh data block。

        Returns:
            删除的 mesh data 数量
        """
        removed = 0
        for name in orphan_names:
            m = bpy.data.meshes.get(name)
            if m is not None and m.users == 0:
                bpy.data.meshes.remove(m)
                removed += 1
        return removed

    @staticmethod
    def clean_orphans() -> int:
        """
        扫描整个场景，清理所有 users == 0 的 mesh data。

        Returns:
            清理的 mesh data 数量
        """
        removed = 0
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
                removed += 1
        info(f"孤立数据清理完成: {removed} 个 mesh data 块已删除")
        return removed

    # ── 名称规范化 ──

    @staticmethod
    def normalize_all_names(pattern: str = None) -> int:
        """
        规范化所有 mesh data 名称，按正则表达式去除匹配部分。

        Args:
            pattern: 正则表达式，默认 r'__[0-9].*$'

        Returns:
            改名的 mesh data 数量
        """
        renamed = 0
        for mesh in bpy.data.meshes:
            old_name = mesh.name
            new_name = normalize_mesh_name(old_name, pattern)
            if new_name != old_name:
                mesh.name = new_name
                renamed += 1
        info(f"名称规范化完成: {renamed} 个 mesh data 已改名")
        return renamed

    # ── 递归子集合并 ──

    @staticmethod
    def _find_topology_subset(objects: list["bpy.types.Object"],
                              master_mesh) -> list["bpy.types.Object"]:
        """
        找出与 master_mesh 拓扑一致的对象子集。
        """
        compat = []
        for obj in objects:
            if obj.data and len(obj.data.vertices) == len(master_mesh.vertices):
                compat.append(obj)
        return compat

    def _recursive_merge_incompat(
        self,
        incompat_list: list["bpy.types.Object"],
        force: bool,
    ) -> "MeshMergeResult":
        """
        对拓扑不一致的对象进行一级递归合并。

        在 incompat_list 中寻找两两拓扑一致的子集，
        各自进行合并。仅一级递归，不再对子子集展开。

        Args:
            incompat_list: 与 master 拓扑不一致的对象列表
            force: 是否强制补偿

        Returns:
            MeshMergeResult 汇总结果
        """
        result = MeshMergeResult()
        processed: set[str] = set()

        for i, obj_a in enumerate(incompat_list):
            if obj_a.name in processed:
                continue
            if obj_a.data is None:
                continue

            # 找出与 obj_a 拓扑一致的其他对象
            group = [obj_a]
            processed.add(obj_a.name)
            for j, obj_b in enumerate(incompat_list):
                if j <= i:
                    continue
                if obj_b.name in processed:
                    continue
                if obj_b.data is None:
                    continue
                if self._validate_topology(obj_a.data, obj_b.data):
                    group.append(obj_b)
                    processed.add(obj_b.name)

            if len(group) < 2:
                continue

            # 以 group[0] 为 master 进行合并
            sub_result = self._merge_group(group, group[0], force)
            result.reassigned += sub_result.reassigned
            result.pos_compensated += sub_result.pos_compensated
            result.rot_compensated += sub_result.rot_compensated
            result.skipped += sub_result.skipped
            result.errors += sub_result.errors
            result.error_details.extend(sub_result.error_details)

        return result

    # ── 单组合并 ──

    def _merge_group(
        self,
        objects: list["bpy.types.Object"],
        master_obj: "bpy.types.Object",
        force: bool,
    ) -> MeshMergeResult:
        """
        将 objects 中的所有非 master 对象切换为共享 master 的 mesh data。

        Returns:
            MeshMergeResult
        """
        result = MeshMergeResult()
        master_mesh = master_obj.data

        master_verts = [[v.co.x, v.co.y, v.co.z]
                        for v in master_mesh.vertices]
        master_tris = self._triangle_count(master_mesh)

        # 包围盒信息
        bb_min = [min(v[d] for v in master_verts) for d in range(3)]
        bb_max = [max(v[d] for v in master_verts) for d in range(3)]
        bb_size = [bb_max[d] - bb_min[d] for d in range(3)]

        info(f"主网格体: {master_obj.name} | "
             f"顶点: {len(master_mesh.vertices):,}v / "
             f"三角形: {master_tris:,}tris | "
             f"包围盒: {bb_size[0]:.2f}x{bb_size[1]:.2f}x{bb_size[2]:.2f}")

        others = [obj for obj in objects if obj != master_obj]
        orphan_names = []

        for idx, obj in enumerate(others):
            old_mesh = obj.data

            # 已共享同一网格体
            if old_mesh == master_mesh:
                result.skipped += 1
                info(f"[{idx+1}/{len(others)}] 跳过 {obj.name} — 已共享同一网格体")
                continue

            # 拓扑验证
            if len(old_mesh.vertices) != len(master_mesh.vertices):
                detail = {
                    "object_name": obj.name,
                    "reason": (f"顶点数不匹配 "
                               f"({len(old_mesh.vertices)}v vs "
                               f"{len(master_mesh.vertices)}v)"),
                }
                result.error_details.append(detail)
                result.errors += 1
                warn(f"[{idx+1}/{len(others)}] 跳过 {obj.name} — "
                     f"顶点数不匹配 ({len(old_mesh.vertices)}v vs "
                     f"{len(master_mesh.vertices)}v)")
                continue

            # Kabsch 对齐
            old_verts = [[v.co.x, v.co.y, v.co.z]
                         for v in old_mesh.vertices]

            try:
                R, t = _kabsch_index_aligned(master_verts, old_verts)
            except Exception as e:
                detail = {
                    "object_name": obj.name,
                    "reason": f"Kabsch 失败: {e}",
                }
                result.error_details.append(detail)
                result.errors += 1
                error(f"[{idx+1}/{len(others)}] 错误 {obj.name} — Kabsch 失败: {e}")
                continue

            # 评估变换幅度
            if USE_NUMPY:
                I3 = np.eye(3)
                rot_mag = float(np.linalg.norm(R - I3, ord='fro'))
                pos_mag = float(np.linalg.norm(t))
                trace = float(np.clip((np.trace(R) - 1) / 2, -1, 1))
                angle_deg = float(np.degrees(np.arccos(trace)))
            else:
                rot_mag = math.sqrt(
                    sum((R[i][j] - (1.0 if i == j else 0.0)) ** 2
                        for i in range(3) for j in range(3))
                )
                pos_mag = math.sqrt(t[0]**2 + t[1]**2 + t[2]**2)
                trace = max(-1.0, min(1.0,
                    (R[0][0] + R[1][1] + R[2][2] - 1) / 2))
                angle_deg = math.degrees(math.acos(trace))

            needs_comp = (
                (rot_mag > self.rot_threshold) or
                (pos_mag > self.pos_threshold)
            )
            effective_force = force or self.force_compensation

            # 无补偿情况
            if not needs_comp:
                obj.data = master_mesh
                result.reassigned += 1
                if old_mesh.users == 0:
                    orphan_names.append(old_mesh.name)
                info(f"[{idx+1}/{len(others)}] 直接 {obj.name} "
                     f"(rot={rot_mag*1e3:.1f}mrad pos={pos_mag*1e3:.1f}mm)")
                continue

            # 超阈值且非强制 → 跳过
            if not effective_force:
                detail = {
                    "object_name": obj.name,
                    "reason": (f"超阈值: rot={angle_deg:.1f}° "
                               f"pos={pos_mag*1e3:.1f}mm"),
                }
                result.error_details.append(detail)
                result.skipped += 1
                warn(f"[{idx+1}/{len(others)}] 跳过 {obj.name} — "
                     f"超阈值 (rot={angle_deg:.1f}° pos={pos_mag*1e3:.1f}mm)")
                continue

            # 强制补偿
            self._compensate_pivot(obj, R, t)

            reasons = []
            if rot_mag > self.rot_threshold:
                result.rot_compensated += 1
                reasons.append(f"旋转{angle_deg:.1f}°")
            if pos_mag > self.pos_threshold:
                result.pos_compensated += 1
                reasons.append(f"位移{pos_mag*1e3:.1f}mm")

            tag = "OK" if angle_deg < 15 else ("WARN" if angle_deg < 45 else "LARGE")

            obj.data = master_mesh
            result.reassigned += 1

            if old_mesh.users == 0:
                orphan_names.append(old_mesh.name)

            info(f"[{idx+1}/{len(others)}] [{tag}] {obj.name} → "
                 f"{'+'.join(reasons)}")

        # 清理孤立数据
        removed = self._clean_orphans(orphan_names)
        result.orphans_removed += removed

        # 规范化 master 名称
        old_name = master_mesh.name
        new_name = normalize_mesh_name(old_name)
        if new_name != old_name and new_name.strip():
            master_mesh.name = new_name
            info(f"共享网格体重命名: '{old_name}' → '{new_name}'")

        return result

    # ── 主入口 ──

    def merge_selected(self, force: bool = False) -> MeshMergeResult:
        """
        主合并流程：将选中的多个 Mesh 对象共享活动对象的 mesh data。

        Args:
            force: 强制补偿（覆盖 self.force_compensation）

        Returns:
            MeshMergeResult 汇总结果
        """
        selected = [obj for obj in bpy.context.selected_objects
                    if obj.type == 'MESH']
        active = bpy.context.active_object

        if active is None or active.type != 'MESH':
            error("请选中一个 MESH 对象作为活动对象（最后选中）")
            return MeshMergeResult(errors=1, error_details=[
                {"object_name": "N/A", "reason": "无有效活动对象"}
            ])

        if len(selected) < 2:
            error("需要至少选中 2 个 Mesh 对象")
            return MeshMergeResult(errors=1, error_details=[
                {"object_name": "N/A", "reason": "选中对象不足 2 个"}
            ])

        if active not in selected:
            error("活动对象必须在选中列表中")
            return MeshMergeResult(errors=1, error_details=[
                {"object_name": "N/A", "reason": "活动对象不在选中列表中"}
            ])

        effective_force = force or self.force_compensation
        master_obj = active
        master_mesh = master_obj.data

        others = [obj for obj in selected if obj != active]

        # 分组：拓扑一致 vs 不一致
        compat_list = []
        incompat_list = []
        already_shared = []

        for obj in others:
            if obj.data == master_mesh:
                already_shared.append(obj)
            elif self._validate_topology(master_mesh, obj.data):
                compat_list.append(obj)
            else:
                incompat_list.append(obj)

        # 合并拓扑一致组
        info(f"开始合并: master={master_obj.name}, "
             f"一致={len(compat_list)}, 不一致={len(incompat_list)}, "
             f"已共享={len(already_shared)}")

        result = self._merge_group(
            [master_obj] + compat_list, master_obj, effective_force)

        # 处理已共享对象
        already_result = MeshMergeResult()
        for obj in already_shared:
            already_result.skipped += 1
            info(f"跳过 {obj.name} — 已共享同一网格体")
        result.skipped += already_result.skipped

        # 递归合并拓扑不一致组（一级递归）
        if incompat_list:
            info(f"尝试递归合并 {len(incompat_list)} 个拓扑不一致对象...")
            recur_result = self._recursive_merge_incompat(
                incompat_list, effective_force)
            result.reassigned += recur_result.reassigned
            result.pos_compensated += recur_result.pos_compensated
            result.rot_compensated += recur_result.rot_compensated
            result.skipped += recur_result.skipped
            result.errors += recur_result.errors
            result.error_details.extend(recur_result.error_details)

        # 汇总输出
        log_summary(result.to_dict())
        return result
