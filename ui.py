"""
ui.py — UI 面板与操作符定义

Blender Mesh Toolkit 的所有 Panel 和 Operator 注册。
"""

import os
import json
import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .logger import log, info, warn, error, get_log_lines, clear_log
from .mesh_core import MeshMerger, MeshMergeResult
from .export_core import ExportPipeline
from .config import (
    DEFAULT_LOC_THRESHOLD,
    DEFAULT_ROT_THRESHOLD,
    DEFAULT_ANCHOR_NAME,
    MAX_ASSET_NAME_LENGTH,
    NAMING_MODES,
    ENGINE_ITEMS,
    PRECISION_MODES,
)

from . import register_class, unregister_class


# ═══════════════════════════════════════════
#  偏好设置辅助
# ═══════════════════════════════════════════

def _get_prefs(context=None):
    """获取 addon preferences。"""
    if context is None:
        context = bpy.context
    prefs = context.preferences.addons.get(__name__.rsplit('.', 1)[0])
    if prefs is not None:
        return prefs.preferences
    return None


# ═══════════════════════════════════════════
#  Operator: Share Mesh Data
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_ShareMesh(bpy.types.Operator):
    """将选中对象的网格数据共享为活动对象的网格体"""
    bl_idname = "mesh_toolkit.share_mesh_data"
    bl_label = "共享网格数据"
    bl_description = "将其他选中网格对象切换为共享活动对象的网格数据，通过 Kabsch 算法补偿枢轴差异"
    bl_options = {'REGISTER', 'UNDO'}

    force_compensation: BoolProperty(
        name="强制补偿",
        description="忽略阈值限制，对所有拓扑匹配对象强制应用枢轴补偿",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        """至少选中 2 个 MESH 对象 + 有活动对象时可用。"""
        if context.active_object is None:
            return False
        if context.active_object.type != 'MESH':
            return False
        mesh_count = sum(1 for obj in context.selected_objects
                         if obj.type == 'MESH')
        return mesh_count >= 2

    def invoke(self, context, event):
        """
        invoke 阶段：检查强制补偿条件，若枢轴差异 >45° 则弹出确认对话框。
        """
        prefs = _get_prefs(context)
        if prefs is None:
            return self.execute(context)

        force = self.force_compensation or prefs.force_compensation_enabled
        if not force:
            return self.execute(context)

        # 检查是否有差异 >45° 的对象
        master_obj = context.active_object
        selected = [obj for obj in context.selected_objects
                    if obj.type == 'MESH' and obj != master_obj]
        master_mesh = master_obj.data

        from .mesh_core import _kabsch_index_aligned, USE_NUMPY
        import math

        large_diffs = []
        for obj in selected:
            if obj.data == master_mesh:
                continue
            if len(obj.data.vertices) != len(master_mesh.vertices):
                continue
            try:
                master_verts = [[v.co.x, v.co.y, v.co.z]
                                for v in master_mesh.vertices]
                old_verts = [[v.co.x, v.co.y, v.co.z]
                             for v in obj.data.vertices]
                R, _ = _kabsch_index_aligned(master_verts, old_verts)
                if USE_NUMPY:
                    import numpy as np
                    trace = float(np.clip((np.trace(R) - 1) / 2, -1, 1))
                    angle_deg = float(np.degrees(np.arccos(trace)))
                else:
                    trace = max(-1.0, min(1.0,
                        (R[0][0] + R[1][1] + R[2][2] - 1) / 2))
                    angle_deg = math.degrees(math.acos(trace))
                if angle_deg > 45:
                    large_diffs.append((obj.name, angle_deg))
            except Exception:
                pass

        if large_diffs:
            # 弹出确认对话框
            names = ", ".join(
                f"{name}({angle:.0f}°)" for name, angle in large_diffs[:5])
            if len(large_diffs) > 5:
                names += f" 等{len(large_diffs)}个对象"
            warn(f"强制补偿警告: 以下对象枢轴差异 >45°: {names}")
            # 使用 invoke_confirm 弹出确认对话框，用户确认后自动调用 execute()
            return context.window_manager.invoke_confirm(self, event)

        return self.execute(context)

    def execute(self, context):
        """执行共享网格数据操作。"""
        prefs = _get_prefs(context)
        if prefs is None:
            pos_thresh = DEFAULT_LOC_THRESHOLD
            rot_thresh = DEFAULT_ROT_THRESHOLD
            force = self.force_compensation
        else:
            pos_thresh = prefs.pos_threshold
            rot_thresh = prefs.rot_threshold
            force = (self.force_compensation
                     or prefs.force_compensation_enabled)

        merger = MeshMerger(
            pos_threshold=pos_thresh,
            rot_threshold=rot_thresh,
            force_compensation=force,
        )

        result = merger.merge_selected(force=force)

        # 汇总
        info(f"完成: 重分配{result.reassigned}个, "
             f"旋转补偿{result.rot_compensated}个, "
             f"位移补偿{result.pos_compensated}个, "
             f"跳过{result.skipped}个, "
             f"错误{result.errors}个, "
             f"清理孤立{result.orphans_removed}个")

        return {'FINISHED'}


# ═══════════════════════════════════════════
#  Operator: Clean Orphan Data
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_CleanOrphans(bpy.types.Operator):
    """清理场景中无引用的孤立网格数据"""
    bl_idname = "mesh_toolkit.clean_orphan_data"
    bl_label = "清理孤立数据"
    bl_description = "清理场景中所有 users==0 的孤立网格数据块"
    bl_description = "删除场景中所有未被任何对象引用的孤立 mesh data 块"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """无视选中的对象，总是可用（清理全局孤立数据）。"""
        return True

    def execute(self, context):
        """执行清理操作。"""
        removed = MeshMerger.clean_orphans()
        if removed == 0:
            info("未发现孤立 mesh data")
        self.report({'INFO'}, f"已清理 {removed} 个孤立 mesh data 块")
        return {'FINISHED'}


# ═══════════════════════════════════════════
#  Operator: Normalize Mesh Names
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_NormalizeNames(bpy.types.Operator):
    """按正则表达式规范化所有 mesh data 名称"""
    bl_idname = "mesh_toolkit.normalize_mesh_names"
    bl_label = "规范化命名"
    bl_description = "按自定义正则表达式去除 mesh data 名称中的匹配部分"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        prefs = _get_prefs(context)
        pattern = prefs.normalize_pattern if prefs else r"__[0-9].*$"
        renamed = MeshMerger.normalize_all_names(pattern)
        if renamed == 0:
            info("所有 mesh data 名称已符合规范")
        self.report({'INFO'}, f"已规范化 {renamed} 个 mesh data 名称")
        return {'FINISHED'}


# ═══════════════════════════════════════════
#  Operator: Export Pipeline
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_ExportPipeline(bpy.types.Operator):
    """执行 GLB + Manifest 导出管线"""

    bl_idname = "mesh_toolkit.export_pipeline"
    bl_label = "导出"
    bl_description = ("扫描场景 → 导出 GLB 几何文件 → "
                      "生成 Manifest JSON 元数据清单")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """场景中至少存在一个 MESH 对象时可用。"""
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                return True
        return False

    def execute(self, context):
        """执行导出管线。"""
        prefs = _get_prefs(context)

        if prefs is None:
            anchor_name = DEFAULT_ANCHOR_NAME
            include_hidden = False
            naming_mode = "HASH_PREFIX"
            max_name_length = MAX_ASSET_NAME_LENGTH
            precision_mode = "LOSSLESS"
            export_yup = True
            export_dir = ""
            target_engine = "UE5"
        else:
            anchor_name = prefs.anchor_name
            include_hidden = prefs.include_hidden
            naming_mode = prefs.naming_mode
            max_name_length = prefs.max_name_length
            precision_mode = prefs.precision_mode
            export_yup = prefs.export_yup
            export_dir = prefs.export_dir
            target_engine = prefs.target_engine

        pipeline = ExportPipeline(
            anchor_name=anchor_name,
            include_hidden=include_hidden,
            naming_mode=naming_mode,
            max_name_length=max_name_length,
            precision_mode=precision_mode,
            export_yup=export_yup,
            export_dir=export_dir,
            target_engine=target_engine,
        )

        success, manifest = pipeline.run()
        if success:
            self.report({'INFO'}, "导出完成")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "导出失败，请查看日志")
            return {'CANCELLED'}


# ═══════════════════════════════════════════
#  Operator: Clear Log
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_ClearLog(bpy.types.Operator):
    """清空日志缓冲区"""

    bl_idname = "mesh_toolkit.clear_log"
    bl_label = "清空日志"
    bl_description = "清空日志面板中的所有条目"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        clear_log()
        return {'FINISHED'}


# ═══════════════════════════════════════════
#  Operator: Share Mesh by JSON
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_JsonShareMesh(bpy.types.Operator, ImportHelper):
    """按外部 JSON 文件指定的分组批量共享网格数据"""
    bl_idname = "mesh_toolkit.json_share_mesh"
    bl_label = "按 JSON 数据共享网格"
    bl_description = "读取 JSON 分组配置，按 source→members 关系批量共享网格数据"
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper 自动提供 filepath 属性
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        """解析 JSON 并逐组执行网格共享。"""
        filepath = self.filepath
        if not filepath or not os.path.isfile(filepath):
            self.report({'ERROR'}, "无效的文件路径")
            return {'CANCELLED'}

        # 读取 JSON
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self.report({'ERROR'}, f"JSON 解析失败: {e}")
            error(f"JSON 解析失败: {e}")
            return {'CANCELLED'}

        # 验证结构
        groups = data.get("groups")
        if not groups or not isinstance(groups, list):
            self.report({'ERROR'}, "JSON 格式错误: 缺少 'groups' 数组")
            error("JSON 格式错误: 缺少 'groups' 数组")
            return {'CANCELLED'}

        # 获取阈值
        prefs = _get_prefs(context)
        if prefs is None:
            pos_thresh = DEFAULT_LOC_THRESHOLD
            rot_thresh = DEFAULT_ROT_THRESHOLD
            force = False
        else:
            pos_thresh = prefs.pos_threshold
            rot_thresh = prefs.rot_threshold
            force = prefs.force_compensation_enabled

        merger = MeshMerger(
            pos_threshold=pos_thresh,
            rot_threshold=rot_thresh,
            force_compensation=force,
        )

        total_groups = len(groups)
        ok_groups = 0
        skip_groups = 0
        total_reassigned = 0

        info(f"开始按 JSON 分组共享网格: {total_groups} 组")

        for idx, group in enumerate(groups, 1):
            source_name = group.get("source", "")
            member_names = group.get("members", [])

            if not source_name or not member_names:
                warn(f"[组 {idx}/{total_groups}] 跳过: source 或 members 为空")
                skip_groups += 1
                continue

            # 查找 source 对象
            source_obj = bpy.data.objects.get(source_name)
            if source_obj is None or source_obj.type != 'MESH':
                warn(f"[组 {idx}/{total_groups}] 跳过: 源对象 '{source_name}' 不存在或非 MESH")
                skip_groups += 1
                continue

            # 收集有效的 member 对象
            member_objs = []
            for mn in member_names:
                obj = bpy.data.objects.get(mn)
                if obj is None or obj.type != 'MESH':
                    warn(f"[组 {idx}/{total_groups}] 成员 '{mn}' 不存在或非 MESH，已忽略")
                    continue
                if obj == source_obj:
                    warn(f"[组 {idx}/{total_groups}] 成员 '{mn}' 与源对象相同，已忽略")
                    continue
                if obj.data == source_obj.data:
                    info(f"[组 {idx}/{total_groups}] 成员 '{mn}' 已共享源网格，跳过")
                    continue
                member_objs.append(obj)

            if not member_objs:
                info(f"[组 {idx}/{total_groups}] 组 '{source_name}' 无有效成员")
                skip_groups += 1
                continue

            # 选中 source + members，执行合并
            bpy.ops.object.select_all(action='DESELECT')
            source_obj.select_set(True)
            for obj in member_objs:
                obj.select_set(True)
            context.view_layer.objects.active = source_obj

            result = merger.merge_selected(force=force)
            total_reassigned += result.reassigned
            ok_groups += 1

            info(f"[组 {idx}/{total_groups}] '{source_name}' → "
                 f"重分配{result.reassigned}, 补偿旋转{result.rot_compensated}, "
                 f"补偿位移{result.pos_compensated}")

        # 汇总
        summary_msg = (
            f"JSON 批量共享完成: {ok_groups}/{total_groups} 组成功, "
            f"重分配 {total_reassigned} 个对象, "
            f"跳过 {skip_groups} 组"
        )
        info(summary_msg)
        self.report({'INFO'}, summary_msg)
        return {'FINISHED'}


# ═══════════════════════════════════════════
#  Operator: Create Anchor
# ═══════════════════════════════════════════

class MESHTOOLKIT_OT_CreateAnchor(bpy.types.Operator):
    """在原点创建锚点空对象"""
    bl_idname = "mesh_toolkit.create_anchor"
    bl_label = "创建锚点"
    bl_description = "在世界原点根据配置的锚点名称创建纯轴空对象"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = _get_prefs(context)
        anchor_name = prefs.anchor_name if prefs else DEFAULT_ANCHOR_NAME

        # 检查是否已存在同名对象
        existing = bpy.data.objects.get(anchor_name)
        if existing:
            info(f"锚点 \"{anchor_name}\" 已存在，选中它")
            bpy.ops.object.select_all(action='DESELECT')
            existing.select_set(True)
            context.view_layer.objects.active = existing
            return {'FINISHED'}

        # 创建空对象
        bpy.ops.object.empty_add(
            type='PLAIN_AXES',
            location=(0, 0, 0),
        )
        anchor = context.active_object
        anchor.name = anchor_name
        anchor.empty_display_type = 'PLAIN_AXES'
        anchor.empty_display_size = 1.0

        info(f"锚点 \"{anchor_name}\" 已在原点创建")
        return {'FINISHED'}


# ═══════════════════════════════════════════
#  Panel: Main
# ═══════════════════════════════════════════

class MESHTOOLKIT_PT_MainPanel(bpy.types.Panel):
    """Mesh Toolkit 主面板 — N 面板 Tab"""

    bl_label = "Mesh Toolkit"
    bl_idname = "MESHTOOLKIT_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mesh Toolkit"

    def draw(self, context):
        """无需在父面板绘制内容，子面板承载所有 UI。"""
        pass


# ═══════════════════════════════════════════
#  Panel: Mesh Management
# ═══════════════════════════════════════════

class MESHTOOLKIT_PT_MeshManagement(bpy.types.Panel):
    """网格管理子面板"""

    bl_label = "网格管理"
    bl_idname = "MESHTOOLKIT_PT_MeshManagement"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mesh Toolkit"
    bl_parent_id = "MESHTOOLKIT_PT_MainPanel"

    def draw(self, context):
        layout = self.layout
        prefs = _get_prefs(context)

        # ── Share Mesh Data ──
        box = layout.box()
        box.label(text="共享网格数据", icon='MESH_DATA')

        row = box.row(align=True)
        op = row.operator("mesh_toolkit.share_mesh_data",
                           text="共享网格数据",
                           icon='LINKED')

        if prefs is not None:
            op.force_compensation = prefs.force_compensation_enabled
            box.prop(prefs, "force_compensation_enabled",
                     text="强制补偿")

            # 阈值滑块
            col = box.column(align=True)
            col.prop(prefs, "pos_threshold", text="位置阈值",
                     slider=True)
            col.prop(prefs, "rot_threshold", text="旋转阈值",
                     slider=True)

        # ── 实用工具 ──
        box = layout.box()
        box.label(text="实用工具", icon='TOOL_SETTINGS')

        row = box.row(align=True)
        row.operator("mesh_toolkit.clean_orphan_data",
                      text="清理孤立数据",
                      icon='TRASH')

        # JSON 批量共享
        row = box.row(align=True)
        row.operator("mesh_toolkit.json_share_mesh",
                      text="按 JSON 数据共享网格",
                      icon='FILE_SCRIPT')

        # 规范化命名正则输入
        if prefs is not None:
            box.prop(prefs, "normalize_pattern",
                     text="匹配正则",
                     icon='SORTALPHA')
        row = box.row(align=True)
        row.operator("mesh_toolkit.normalize_mesh_names",
                      text="规范化命名",
                      icon='SORTALPHA')


# ═══════════════════════════════════════════
#  Panel: Export Pipeline
# ═══════════════════════════════════════════

class MESHTOOLKIT_PT_ExportPipeline(bpy.types.Panel):
    """导出管线子面板"""

    bl_label = "导出管线"
    bl_idname = "MESHTOOLKIT_PT_ExportPipeline"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mesh Toolkit"
    bl_parent_id = "MESHTOOLKIT_PT_MainPanel"

    def draw(self, context):
        layout = self.layout
        prefs = _get_prefs(context)

        # ── 导出设置 ──
        box = layout.box()
        box.label(text="导出设置", icon='EXPORT')

        if prefs is not None:
            col = box.column(align=True)
            col.prop(prefs, "target_engine", text="目标引擎")
            col.prop(prefs, "anchor_name", text="锚点名称")

            # 锚点创建按钮
            row = col.row(align=True)
            row.operator("mesh_toolkit.create_anchor",
                          text="创建锚点",
                          icon='EMPTY_AXIS')

            col.prop(prefs, "export_dir", text="导出目录")
            col.prop(prefs, "naming_mode", text="命名模式")
            col.prop(prefs, "precision_mode", text="压缩精度")
            col.prop(prefs, "export_yup", text="glTF Y-Up")
            col.prop(prefs, "include_hidden", text="包含隐藏对象")

        # ── 导出按钮 ──
        box = layout.box()
        row = box.row(align=True)
        row.scale_y = 2.0
        row.operator("mesh_toolkit.export_pipeline",
                      text="导出 GLB + Manifest",
                      icon='EXPORT')


# ═══════════════════════════════════════════
#  Panel: Log
# ═══════════════════════════════════════════

class MESHTOOLKIT_PT_Log(bpy.types.Panel):
    """日志子面板"""

    bl_label = "日志"
    bl_idname = "MESHTOOLKIT_PT_Log"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mesh Toolkit"
    bl_parent_id = "MESHTOOLKIT_PT_MainPanel"

    def draw(self, context):
        layout = self.layout

        # ── 日志区域 ──
        box = layout.box()
        log_lines = get_log_lines(20)
        if log_lines:
            col = box.column(align=True)
            col.scale_y = 0.6
            for line in log_lines:
                col.label(text=line[-120:])
        else:
            box.label(text="(日志为空)", icon='INFO')

        # ── 清空按钮 ──
        row = layout.row(align=True)
        row.operator("mesh_toolkit.clear_log",
                      text="Clear Log",
                      icon='X')


# ═══════════════════════════════════════════
#  注册列表 (供 __init__.py 使用)
# ═══════════════════════════════════════════

_UI_CLASSES = [
    # Operators
    MESHTOOLKIT_OT_ShareMesh,
    MESHTOOLKIT_OT_JsonShareMesh,
    MESHTOOLKIT_OT_CleanOrphans,
    MESHTOOLKIT_OT_NormalizeNames,
    MESHTOOLKIT_OT_ExportPipeline,
    MESHTOOLKIT_OT_ClearLog,
    MESHTOOLKIT_OT_CreateAnchor,
    # Panels
    MESHTOOLKIT_PT_MainPanel,
    MESHTOOLKIT_PT_MeshManagement,
    MESHTOOLKIT_PT_ExportPipeline,
    MESHTOOLKIT_PT_Log,
]


def ui_register():
    """注册所有 UI 类。由 __init__.py 在 register() 中调用。"""
    for cls in _UI_CLASSES:
        register_class(cls)


def ui_unregister():
    """注销所有 UI 类。由 __init__.py 在 unregister() 中调用。"""
    for cls in reversed(_UI_CLASSES):
        unregister_class(cls)
