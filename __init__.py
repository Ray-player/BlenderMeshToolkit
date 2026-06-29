"""Mesh Toolkit — Blender addon for mesh sharing + GLB/Manifest export"""

# ── bl_info 必须为纯字面量（Blender AST 解析要求）──
bl_info = {
    "name":        "Mesh Toolkit",
    "author":      "Mesh Toolkit Team",
    "version":     (1, 0, 0),
    "blender":     (4, 0, 0),
    "location":    "3D View > N Panel > Mesh Toolkit",
    "description": "Mesh data sharing with Kabsch compensation + GLB/Manifest export for UE5",
    "category":    "Mesh",
    "support":     "COMMUNITY",
}

import bpy
from bpy.props import (
    FloatProperty,
    BoolProperty,
    EnumProperty,
    StringProperty,
    IntProperty,
)

from .config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_LOC_THRESHOLD,
    DEFAULT_ROT_THRESHOLD,
    MAX_ASSET_NAME_LENGTH,
    DEFAULT_ANCHOR_NAME,
    DEFAULT_NORMALIZE_PATTERN,
    NAMING_MODES,
    ENGINE_ITEMS,
    PRECISION_MODES,
)
from .logger import log, info


# ═══════════════════════════════════════════
#  AddonPreferences
# ═══════════════════════════════════════════

class MeshToolkitPreferences(bpy.types.AddonPreferences):
    """Blender Mesh Toolkit 持久化偏好设置。

    所有阈值、导出目录、命名策略等参数均可在此配置，
    设置值通过 Blender 偏好系统自动持久化。
    """

    bl_idname = __name__

    # ── 阈值 ──
    pos_threshold: FloatProperty(
        name="位置补偿阈值 (m)",
        description="位置差异超过此阈值时触发枢轴补偿",
        default=DEFAULT_LOC_THRESHOLD,
        min=0.0,
        max=1.0,
        precision=6,
        step=0.0001,
    )

    rot_threshold: FloatProperty(
        name="旋转补偿阈值 (rad)",
        description="旋转差异超过此阈值时触发枢轴补偿",
        default=DEFAULT_ROT_THRESHOLD,
        min=0.0,
        max=3.14159,
        precision=6,
        step=0.001,
    )

    # ── 强制补偿 ──
    force_compensation_enabled: BoolProperty(
        name="强制补偿",
        description="忽略阈值，对所有拓扑匹配的对象强制应用枢轴补偿",
        default=False,
    )

    # ── 目标引擎 ──
    target_engine: EnumProperty(
        name="目标引擎",
        description="导出坐标转换的目标引擎",
        items=ENGINE_ITEMS,
        default="UE5",
    )

    # ── 导出目录 ──
    export_dir: StringProperty(
        name="导出目录",
        description="GLB + Manifest 文件的输出目录（留空使用场景文件旁 Exports 目录）",
        subtype='DIR_PATH',
        default="",
    )

    # ── 命名模式 ──
    naming_mode: EnumProperty(
        name="资产命名模式",
        description="StaticMesh 资产命名策略",
        items=NAMING_MODES,
        default="HASH_PREFIX",
    )

    # ── 精度模式 ──
    precision_mode: EnumProperty(
        name="精度模式",
        description="GLB 导出精度 / Draco 压缩级别",
        items=PRECISION_MODES,
        default="LOSSLESS",
    )

    # ── 锚点名称 ──
    anchor_name: StringProperty(
        name="锚点对象名称",
        description="场景统一参考锚点对象名",
        default=DEFAULT_ANCHOR_NAME,
    )

    # ── 资产名称最大长度 ──
    max_name_length: IntProperty(
        name="资产名最大长度",
        description="StaticMesh 资产名最大字符数（超出将智能截断）",
        default=MAX_ASSET_NAME_LENGTH,
        min=10,
        max=200,
    )

    # ── 规范化命名正则 ──
    normalize_pattern: StringProperty(
        name="规范化正则",
        description="用于规范化 mesh data 名称的正则表达式，匹配部分将被删除",
        default=DEFAULT_NORMALIZE_PATTERN,
    )

    # ── 导出 Y-Up ──
    export_yup: BoolProperty(
        name="glTF Y-Up",
        description="启用 glTF 导出时的 Y-Up 坐标系转换",
        default=True,
    )

    # ── 包含隐藏对象 ──
    include_hidden: BoolProperty(
        name="包含隐藏对象",
        description="导出时是否包含隐藏的 Mesh 对象",
        default=False,
    )

    def draw(self, context):
        """绘制 Preferences UI。"""
        layout = self.layout
        layout.use_property_split = True

        # ── 阈值 ──
        box = layout.box()
        box.label(text="合并阈值", icon='MODIFIER_DATA')
        col = box.column(align=True)
        col.prop(self, "pos_threshold")
        col.prop(self, "rot_threshold")
        col.prop(self, "force_compensation_enabled")

        # ── 导出 ──
        box = layout.box()
        box.label(text="导出设置", icon='EXPORT')
        col = box.column(align=True)
        col.prop(self, "target_engine")
        col.prop(self, "export_dir")
        col.prop(self, "anchor_name")
        col.prop(self, "export_yup")
        col.prop(self, "include_hidden")

        # ── 命名 ──
        box = layout.box()
        box.label(text="资产命名", icon='SORTALPHA')
        col = box.column(align=True)
        col.prop(self, "naming_mode")
        col.prop(self, "precision_mode")
        col.prop(self, "max_name_length")


# ═══════════════════════════════════════════
#  注册 / 注销
# ═══════════════════════════════════════════

# 注册列表 — 由 ui.py 中的类补全
_registry: list = [
    MeshToolkitPreferences,
]


def register():
    """注册所有 Blender 类（Panel / Operator / Preferences）。"""
    # 注册 Preferences
    for cls in _registry:
        bpy.utils.register_class(cls)

    # 注册 UI（延迟导入避免循环依赖）
    from .ui import ui_register
    ui_register()

    info(f"{APP_NAME} v{APP_VERSION} 已注册")


def unregister():
    """注销所有 Blender 类。"""
    # 注销 UI
    from .ui import ui_unregister
    ui_unregister()

    # 注销 Preferences
    for cls in reversed(_registry):
        bpy.utils.unregister_class(cls)

    info(f"{APP_NAME} v{APP_VERSION} 已注销")


def register_class(cls):
    """供 ui.py 调用的注册辅助：注册类并追加到注册列表。"""
    bpy.utils.register_class(cls)
    if cls not in _registry:
        _registry.append(cls)


def unregister_class(cls):
    """供 ui.py 调用的注销辅助：注销类并从注册列表移除。"""
    bpy.utils.unregister_class(cls)
    if cls in _registry:
        _registry.remove(cls)
