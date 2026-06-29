"""
config.py — 全局常量与配置定义

Blender Mesh Toolkit 的所有常量、预设、版本自适应参数集中管理。
"""

import bpy

# ── 应用元数据 ──
APP_NAME = "Mesh Toolkit"
APP_VERSION = "1.0.0"

# ── 默认阈值 ──
DEFAULT_LOC_THRESHOLD = 0.001    # 位置补偿阈值 (m)，超过 1mm 触发
DEFAULT_ROT_THRESHOLD = 0.015    # 旋转补偿阈值 (弧度)，约 0.86°

# ── UE5 单位缩放 ──
UE5_UNIT_SCALE = 100.0           # Blender 米 → UE5 厘米

# ── 命名 ──
MAX_ASSET_NAME_LENGTH = 80       # 资产名最大长度，避免 UE 导入时再截断

# ── 锚点 ──
DEFAULT_ANCHOR_NAME = "UE_Anchor"

# ── 命名规范化 ──
DEFAULT_NORMALIZE_PATTERN = r"__[0-9].*$"  # 去除 __数字... 后缀

# ── 默认导出目录 ──
DEFAULT_EXPORT_DIR = ""

# ── 命名模式枚举 ──
NAMING_MODES = [
    ("ORIGINAL",     "原始名称",     "原始 mesh data 名称经合规化后使用"),
    ("HASH",         "纯 Hash",      "基于 GLB 文件名 + MD5 短 ID"),
    ("HASH_PREFIX",  "Hash+名称",    "MD5 短 ID 前置 + 智能截断名称"),
]

# ── 精度模式枚举 ──
PRECISION_MODES = [
    ("LOSSLESS",   "无损 (Lossless)",      "关闭 Draco 压缩，保留完整精度"),
    ("SUPER_HIGH", "超高 (Super High)",    "Draco level 1"),
    ("HIGH",       "高 (High)",            "Draco level 4"),
    ("BALANCED",   "平衡 (Balanced)",      "Draco level 6"),
    ("AGGRESSIVE", "激进 (Aggressive)",    "Draco level 10"),
]

# ── 引擎枚举 ──
ENGINE_ITEMS = [
    ("UE5",   "Unreal Engine 5", "Z-up 左手系, 厘米"),
    ("Unity", "Unity",           "Y-up 左手系, 米"),
    ("Godot", "Godot",           "Y-up 右手系, 米"),
]

# ── Draco 压缩预设 ──
DRACO_PRESETS = {
    "LOSSLESS": {
        "enable": False,
    },
    "SUPER_HIGH": {
        "enable": True,
        "level": 1,
        "position": 18,
        "normal": 14,
        "texcoord": 16,
        "color": 10,
        "generic": 10,
    },
    "HIGH": {
        "enable": True,
        "level": 4,
        "position": 16,
        "normal": 12,
        "texcoord": 14,
        "color": 10,
        "generic": 10,
    },
    "BALANCED": {
        "enable": True,
        "level": 6,
        "position": 14,
        "normal": 10,
        "texcoord": 12,
        "color": 8,
        "generic": 8,
    },
    "AGGRESSIVE": {
        "enable": True,
        "level": 10,
        "position": 12,
        "normal": 8,
        "texcoord": 10,
        "color": 6,
        "generic": 6,
    },
}


def get_draco_param_names():
    """
    根据 Blender 版本返回正确的 Draco 导出参数名。

    Blender 4.0 / 4.1 / 4.2 之间 Draco 参数名有过调整，
    此函数在运行时检测 bpy.app.version 并返回对应的参数字典。
    """
    ver = bpy.app.version
    if ver >= (4, 2, 0):
        return {
            "enable":    "export_draco_mesh_compression_enable",
            "level":     "export_draco_mesh_compression_level",
            "position":  "export_draco_position_quantization",
            "normal":    "export_draco_normal_quantization",
            "texcoord":  "export_draco_texcoord_quantization",
            "color":     "export_draco_color_quantization",
            "generic":   "export_draco_generic_quantization",
        }
    elif ver >= (4, 1, 0):
        return {
            "enable":    "export_draco_mesh_compression_enable",
            "level":     "export_draco_mesh_compression_level",
            "position":  "export_draco_position_quantization",
            "normal":    "export_draco_normal_quantization",
            "texcoord":  "export_draco_texcoord_quantization",
            "color":     "export_draco_color_quantization",
            "generic":   "export_draco_generic_quantization",
        }
    else:
        # Blender 4.0.x
        return {
            "enable":    "export_draco_mesh_compression_enable",
            "level":     "export_draco_mesh_compression_level",
            "position":  "export_draco_position_quantization",
            "normal":    "export_draco_normal_quantization",
            "texcoord":  "export_draco_texcoord_quantization",
            "color":     "export_draco_color_quantization",
            "generic":   "export_draco_generic_quantization",
        }


# ── 引擎预设注册表 ──
# 每个引擎定义: up_axis, handedness, unit_scale, axis_map
# axis_map 表示 Blender (X,Y,Z) → 目标引擎轴的映射索引
ENGINE_REGISTRY = {
    "BLENDER": {
        "up":          "Z",
        "handedness":  "right",
        "unit_scale":   1.0,
        "axis_map":    (0, 1, 2),
    },
    "UE5": {
        "up":          "Z",
        "handedness":  "left",
        "unit_scale":   100.0,
        "axis_map":    (1, 0, 2),
    },
    "Unity": {
        "up":          "Y",
        "handedness":  "left",
        "unit_scale":   1.0,
        "axis_map":    (0, 2, 1),
    },
    "Godot": {
        "up":          "Y",
        "handedness":  "right",
        "unit_scale":   1.0,
        "axis_map":    (0, 2, 1),
    },
}


def get_engine_preset(engine_name: str) -> dict:
    """获取引擎预设，默认返回 UE5。"""
    return ENGINE_REGISTRY.get(engine_name, ENGINE_REGISTRY["UE5"])
