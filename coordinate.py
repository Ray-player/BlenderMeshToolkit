"""
coordinate.py — 坐标系转换模块

基于引擎预设注册表实现 Blender 坐标系与目标引擎坐标系的相互转换。
当前完整实现 UE5，Unity/Godot 预留扩展点。
"""

from mathutils import Matrix, Vector, Quaternion

from .config import ENGINE_REGISTRY, get_engine_preset


# ═══════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════

def round_list(values: list[float], digits: int = 6) -> list[float]:
    """对列表中的每个浮点数四舍五入到指定位数。"""
    return [round(v, digits) for v in values]


def matrix_rows(matrix: Matrix, digits: int = 6) -> list[list[float]]:
    """将 4x4 Matrix 序列化为嵌套列表。"""
    return [[round(matrix[r][c], digits) for c in range(4)] for r in range(4)]


def compose_matrix(location: Vector, rotation: Quaternion,
                   scale: Vector) -> Matrix:
    """从位置、旋转（四元数）、缩放构造 4x4 变换矩阵。"""
    return Matrix.LocRotScale(location, rotation, scale)


def serialize_blender_transform(matrix: Matrix) -> dict:
    """
    将 Blender 世界空间变换矩阵序列化为 dict。

    Returns:
        {"matrix": [[...]], "location": [...], "rotation_quaternion": [...], "scale": [...]}
    """
    loc, rot, sca = matrix.decompose()
    return {
        "matrix": matrix_rows(matrix),
        "location": round_list([loc.x, loc.y, loc.z], 4),
        "rotation_quaternion": round_list([rot.w, rot.x, rot.y, rot.z], 6),
        "scale": round_list([sca.x, sca.y, sca.z], 4),
    }


# ═══════════════════════════════════════════
#  CoordinateConverter
# ═══════════════════════════════════════════

class CoordinateConverter:
    """
    坐标系转换器（静态方法集合）。

    通过引擎预设注册表驱动坐标转换。
    新增引擎只需调用 register_engine() 注册预设即可。
    """

    ENGINE_PRESETS: dict = dict(ENGINE_REGISTRY)

    @staticmethod
    def register_engine(name: str, preset: dict) -> None:
        """
        注册新的引擎坐标系预设。

        Args:
            name: 引擎标识名
            preset: 预设字典，包含 up, handedness, unit_scale, axis_map
        """
        CoordinateConverter.ENGINE_PRESETS[name] = preset

    @staticmethod
    def get_converter(engine_name: str) -> dict:
        """获取引擎预设，不存在时返回 BLENDER（恒等）。"""
        return CoordinateConverter.ENGINE_PRESETS.get(
            engine_name,
            CoordinateConverter.ENGINE_PRESETS.get("BLENDER", {}),
        )

    @staticmethod
    def _convert_handedness(values: list[float],
                            src_handedness: str,
                            dst_handedness: str) -> list[float]:
        """
        处理坐标系手性翻转。
        BLENDER 右手系 → UE5 左手系需要反转 Y 分量。
        """
        if src_handedness == dst_handedness:
            return values[:]
        # 右手 → 左手：反转第二个映射分量
        result = values[:]
        if len(result) >= 2:
            result[1] = -result[1]
        return result

    @staticmethod
    def blender_loc_to_ue5(x: float, y: float, z: float) -> list[float]:
        """
        Blender 世界位置 → UE5 世界位置。

        Blender (X右, Y前, Z上) 右手系 米
          → 交换 X↔Y 并缩放
          → UE5 (X前, Y右, Z上) 左手系 厘米
        """
        preset = get_engine_preset("UE5")
        s = preset["unit_scale"]
        axis_map = preset["axis_map"]  # (1, 0, 2)
        blender = [x, y, z]
        mapped = [blender[axis_map[i]] * s for i in range(3)]
        return round_list(mapped, 4)

    @staticmethod
    def blender_quat_to_ue5(w: float, x: float, y: float,
                            z: float) -> list[float]:
        """
        Blender 四元数 → UE5 四元数。

        交换 x↔y 分量以匹配轴映射。
        """
        return round_list([w, y, x, z], 6)

    @staticmethod
    def blender_scale_to_ue5(sx: float, sy: float,
                              sz: float) -> list[float]:
        """
        Blender 缩放 → UE5 缩放。

        交换 X↔Y 分量以匹配轴映射。
        """
        return round_list([sy, sx, sz], 4)

    # ── Unity 转换 ──

    @staticmethod
    def blender_loc_to_unity(x: float, y: float, z: float) -> list[float]:
        """Blender Z-up RH → Unity Y-up LH (米)."""
        return [-round(x, 4), round(z, 4), -round(y, 4)]

    @staticmethod
    def blender_quat_to_unity(w: float, x: float, y: float,
                              z: float) -> list[float]:
        """Blender 四元数 → Unity 四元数 (w, x, -z, y)."""
        return round_list([w, x, -z, y], 6)

    @staticmethod
    def blender_scale_to_unity(sx: float, sy: float,
                               sz: float) -> list[float]:
        """Blender 缩放 → Unity 缩放 (sx, sz, sy)."""
        return round_list([sx, sz, sy], 4)

    # ── Godot 转换 ──

    @staticmethod
    def blender_loc_to_godot(x: float, y: float, z: float) -> list[float]:
        """Blender Z-up RH → Godot Y-up RH (米)."""
        return round_list([x, z, y], 4)

    @staticmethod
    def blender_quat_to_godot(w: float, x: float, y: float,
                              z: float) -> list[float]:
        """Blender 四元数 → Godot 四元数 (w, x, z, y)."""
        return round_list([w, x, z, y], 6)

    @staticmethod
    def blender_scale_to_godot(sx: float, sy: float,
                               sz: float) -> list[float]:
        """Blender 缩放 → Godot 缩放 (sx, sz, sy)."""
        return round_list([sx, sz, sy], 4)

    @staticmethod
    def convert_location(loc: list[float],
                         src: str = "BLENDER",
                         dst: str = "UE5") -> list[float]:
        """
        通用位置转换。

        Args:
            loc: [x, y, z] 源坐标系位置
            src: 源引擎名
            dst: 目标引擎名

        Returns:
            目标坐标系位置 [x, y, z]
        """
        if src == dst:
            return round_list(loc, 4)

        src_preset = CoordinateConverter.get_converter(src)
        dst_preset = CoordinateConverter.get_converter(dst)

        src_scale = src_preset.get("unit_scale", 1.0)
        dst_scale = dst_preset.get("unit_scale", 1.0)
        src_axis = src_preset.get("axis_map", (0, 1, 2))
        dst_axis = dst_preset.get("axis_map", (0, 1, 2))

        # 通过 BLENDER 坐标系中转
        # 第一步：从源 → BLENDER
        unit_ratio = src_scale
        in_bl = [loc[src_axis.index(i) if i in src_axis else i] / unit_ratio
                 for i in range(3)]

        # 第二步：从 BLENDER → 目标
        unit_ratio = dst_scale
        result = [in_bl[dst_axis[i]] * unit_ratio for i in range(3)]

        return round_list(result, 4)

    @staticmethod
    def convert_rotation(quat: list[float],
                         src: str = "BLENDER",
                         dst: str = "UE5") -> list[float]:
        """
        通用四元数旋转转换。

        Args:
            quat: [w, x, y, z] 源坐标系四元数
            src: 源引擎名
            dst: 目标引擎名

        Returns:
            目标坐标系四元数 [w, x, y, z]
        """
        if src == dst:
            return round_list(quat, 6)

        # fast path: BLENDER→UE5 交换 X↔Y
        if dst == "UE5" and src == "BLENDER":
            return CoordinateConverter.blender_quat_to_ue5(
                quat[0], quat[1], quat[2], quat[3])
        # fast path: UE5→BLENDER 逆向交换 Y↔X
        if dst == "BLENDER" and src == "UE5":
            return round_list([quat[0], quat[2], quat[1], quat[3]], 6)

        # fast path: BLENDER→Unity: (w, x, -z, y)
        if dst == "Unity" and src == "BLENDER":
            return CoordinateConverter.blender_quat_to_unity(
                quat[0], quat[1], quat[2], quat[3])
        # fast path: Unity→BLENDER: (w, x, z, -y)
        if dst == "BLENDER" and src == "Unity":
            return round_list([quat[0], quat[1], quat[2], -quat[3]], 6)

        # fast path: BLENDER→Godot: (w, x, z, y)
        if dst == "Godot" and src == "BLENDER":
            return CoordinateConverter.blender_quat_to_godot(
                quat[0], quat[1], quat[2], quat[3])
        # fast path: Godot→BLENDER: (w, x, z, y) 对称
        if dst == "BLENDER" and src == "Godot":
            return round_list([quat[0], quat[1], quat[2], quat[3]], 6)

        # 通用路径：通过 BLENDER 坐标中转（两步法）
        # Step 1: src → BLENDER
        src_preset = CoordinateConverter.get_converter(src)
        src_axis = src_preset.get("axis_map", (0, 1, 2))

        # 构建 src→BLENDER 的逆映射：src_axis[i] = blender_axis_idx
        # 逆: blender_comp[j] = src_comp[idx]  where idx is the blender axis in src
        inv_src_axis = [0, 0, 0]
        for bi in range(3):
            inv_src_axis[src_axis[bi]] = bi

        blender_quat = [quat[0]]
        for i in range(3):
            blender_quat.append(quat[inv_src_axis[i] + 1])

        # Step 2: BLENDER → dst
        dst_preset = CoordinateConverter.get_converter(dst)
        dst_axis = dst_preset.get("axis_map", (0, 1, 2))

        result = [blender_quat[0]]
        for i in range(3):
            result.append(blender_quat[dst_axis[i] + 1])

        return round_list(result, 6)

    @staticmethod
    def convert_scale(scale: list[float],
                      src: str = "BLENDER",
                      dst: str = "UE5") -> list[float]:
        """
        通用缩放转换。

        Args:
            scale: [sx, sy, sz] 源坐标系缩放
            src: 源引擎名
            dst: 目标引擎名

        Returns:
            目标坐标系缩放 [sx, sy, sz]
        """
        if src == dst:
            return round_list(scale, 4)

        # fast path: BLENDER→UE5 交换 X↔Y
        if dst == "UE5" and src == "BLENDER":
            return CoordinateConverter.blender_scale_to_ue5(
                scale[0], scale[1], scale[2])
        # fast path: UE5→BLENDER 逆向交换 Y↔X
        if dst == "BLENDER" and src == "UE5":
            return round_list([scale[1], scale[0], scale[2]], 4)

        # fast path: BLENDER→Unity: (sx, sz, sy)
        if dst == "Unity" and src == "BLENDER":
            return CoordinateConverter.blender_scale_to_unity(
                scale[0], scale[1], scale[2])
        # fast path: Unity→BLENDER: (sx, sz, sy) 对称
        if dst == "BLENDER" and src == "Unity":
            return round_list([scale[0], scale[2], scale[1]], 4)

        # fast path: BLENDER→Godot: (sx, sz, sy)
        if dst == "Godot" and src == "BLENDER":
            return CoordinateConverter.blender_scale_to_godot(
                scale[0], scale[1], scale[2])
        # fast path: Godot→BLENDER: (sx, sz, sy) 对称
        if dst == "BLENDER" and src == "Godot":
            return round_list([scale[0], scale[2], scale[1]], 4)

        # 通用路径：通过 BLENDER 坐标中转（两步法）
        # Step 1: src → BLENDER
        src_preset = CoordinateConverter.get_converter(src)
        src_axis = src_preset.get("axis_map", (0, 1, 2))

        inv_src_axis = [0, 0, 0]
        for bi in range(3):
            inv_src_axis[src_axis[bi]] = bi

        blender_scale = [scale[inv_src_axis[i]] for i in range(3)]

        # Step 2: BLENDER → dst
        dst_preset = CoordinateConverter.get_converter(dst)
        dst_axis = dst_preset.get("axis_map", (0, 1, 2))

        result = [blender_scale[dst_axis[i]] for i in range(3)]
        return round_list(result, 4)

    @staticmethod
    def convert_matrix(matrix: Matrix,
                       src: str = "BLENDER",
                       dst: str = "UE5") -> Matrix:
        """
        通用 4×4 变换矩阵转换。

        分解矩阵 → 分别转换 loc/quat/scale → 重新组合。

        Args:
            matrix: 源坐标系 4×4 变换矩阵
            src: 源引擎名
            dst: 目标引擎名

        Returns:
            目标坐标系 4×4 变换矩阵
        """
        loc, rot, sca = matrix.decompose()
        src_loc = [loc.x, loc.y, loc.z]
        src_quat = [rot.w, rot.x, rot.y, rot.z]
        src_scale = [sca.x, sca.y, sca.z]

        dst_loc = CoordinateConverter.convert_location(src_loc, src, dst)
        dst_quat = CoordinateConverter.convert_rotation(src_quat, src, dst)
        dst_scale = CoordinateConverter.convert_scale(src_scale, src, dst)

        new_loc = Vector(dst_loc)
        new_rot = Quaternion((dst_quat[0], dst_quat[1], dst_quat[2], dst_quat[3]))
        new_sca = Vector(dst_scale)

        return compose_matrix(new_loc, new_rot, new_sca)


def serialize_ue5_transform(matrix: Matrix) -> dict:
    """Blender 矩阵 → UE5 坐标系 dict（向后兼容）。"""
    return serialize_engine_transform(matrix, "UE5")


def serialize_engine_transform(matrix: Matrix, engine: str = "UE5") -> dict:
    """
    将 Blender 世界空间变换矩阵序列化为目标引擎坐标系的 dict。

    Args:
        matrix: Blender 4×4 变换矩阵
        engine: 目标引擎 ("UE5" / "Unity" / "Godot")

    Returns:
        {"location": [...], "rotation_quaternion": [...], "scale": [...]}
    """
    loc, rot, sca = matrix.decompose()
    src_loc = [loc.x, loc.y, loc.z]
    src_quat = [rot.w, rot.x, rot.y, rot.z]
    src_scale = [sca.x, sca.y, sca.z]

    return {
        "location": CoordinateConverter.convert_location(
            src_loc, "BLENDER", engine),
        "rotation_quaternion": CoordinateConverter.convert_rotation(
            src_quat, "BLENDER", engine),
        "scale": CoordinateConverter.convert_scale(
            src_scale, "BLENDER", engine),
    }
