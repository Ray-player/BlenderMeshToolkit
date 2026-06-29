"""
export_core.py — 导出管线核心模块

场景扫描 → GLB 导出 → Manifest JSON 构建 → 编排管线。
"""

import os
import json
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

import bpy
from mathutils import Matrix, Vector

from .config import (
    DRACO_PRESETS,
    UE5_UNIT_SCALE,
    DEFAULT_ANCHOR_NAME,
    MAX_ASSET_NAME_LENGTH,
    get_draco_param_names,
)
from .logger import info, warn, error
from .naming import generate_mesh_asset_name, short_mesh_id
from .coordinate import (
    serialize_blender_transform,
    serialize_ue5_transform,
    serialize_engine_transform,
    compose_matrix,
)

# ── 常量 ──
TEMP_COLLECTION_NAME = "_mesh_toolkit_export_temp_"


# ═══════════════════════════════════════════
#  MeshAsset
# ═══════════════════════════════════════════

@dataclass
class MeshAsset:
    """唯一 mesh data 的导出资产元数据。"""
    mesh_data_name: str
    short_id: str
    asset_name: str
    reference_obj: "bpy.types.Object"
    instance_count: int
    basis_matrix: Matrix
    material_names: list[str] = field(default_factory=list)
    material_count: int = 0


# ═══════════════════════════════════════════
#  ExportContext
# ═══════════════════════════════════════════

@dataclass
class ExportContext:
    """导出管线上下文，承载各阶段共享数据。"""
    mesh_objects: list["bpy.types.Object"] = field(default_factory=list)
    anchor_obj: Optional["bpy.types.Object"] = None
    anchor_matrix: Matrix = field(default_factory=lambda: Matrix.Identity(4))
    anchor_inverse: Matrix = field(default_factory=lambda: Matrix.Identity(4))
    mesh_assets: list[MeshAsset] = field(default_factory=list)
    mesh_assets_by_data: dict = field(default_factory=dict)
    bounding_box: dict = field(default_factory=dict)


# ═══════════════════════════════════════════
#  SceneScanner
# ═══════════════════════════════════════════

class SceneScanner:
    """
    场景扫描器：遍历场景中所有可导出的 Mesh 对象，
    按 mesh data 去重分组，构建 MeshAsset 列表和 ExportContext。
    """

    def __init__(self,
                 anchor_name: str = DEFAULT_ANCHOR_NAME,
                 include_hidden: bool = False,
                 naming_mode: str = "HASH_PREFIX",
                 max_name_length: int = MAX_ASSET_NAME_LENGTH,
                 glb_basename: str = ""):
        """
        Args:
            anchor_name: 锚点对象名称
            include_hidden: 是否包含隐藏对象
            naming_mode: 资产命名模式
            max_name_length: 资产名最大长度
            glb_basename: GLB 导出文件基名（HASH 模式使用）
        """
        self.anchor_name = anchor_name
        self.include_hidden = include_hidden
        self.naming_mode = naming_mode
        self.max_name_length = max_name_length
        self.glb_basename = glb_basename

    # ── 对象遍历 ──

    def iter_export_mesh_objects(self) -> list["bpy.types.Object"]:
        """获取所有可导出的 MESH 类型对象，按名称排序。"""
        objects = []
        for obj in bpy.data.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            if not self.include_hidden and not obj.visible_get():
                continue
            objects.append(obj)
        objects.sort(key=lambda item: item.name)
        return objects

    # ── 锚点定位 ──

    def find_anchor(self) -> Optional["bpy.types.Object"]:
        """查找场景中的统一锚点对象。"""
        if self.anchor_name:
            anchor = bpy.data.objects.get(self.anchor_name)
            if anchor is not None:
                return anchor
        return None

    # ── 分组 ──

    @staticmethod
    def _group_by_mesh_data(
        objects: list["bpy.types.Object"],
    ) -> dict[str, list["bpy.types.Object"]]:
        """按 obj.data.name 对对象进行分组。"""
        groups: dict[str, list["bpy.types.Object"]] = defaultdict(list)
        for obj in objects:
            groups[obj.data.name].append(obj)
        return dict(groups)

    # ── 构建 MeshAsset ──

    def _build_mesh_assets(
        self,
        groups: dict[str, list["bpy.types.Object"]],
        anchor_inverse: Matrix,
    ) -> tuple[list[MeshAsset], dict[str, MeshAsset]]:
        """
        为每个唯一 mesh data 构建 MeshAsset。

        Returns:
            (mesh_assets_list, mesh_assets_by_data_dict)
        """
        mesh_assets: list[MeshAsset] = []
        mesh_assets_by_data: dict[str, MeshAsset] = {}

        for mesh_data_name in sorted(groups.keys()):
            instances = sorted(groups[mesh_data_name],
                               key=lambda item: item.name)
            reference_obj = instances[0]
            asset_name, short_id_val = generate_mesh_asset_name(
                mesh_data_name,
                mode=self.naming_mode,
                max_length=self.max_name_length,
                glb_basename=self.glb_basename,
            )

            # 计算 basis_matrix：参考实例相对 Anchor 的旋转+缩放（不含平移）
            reference_anchor_matrix = (
                anchor_inverse @ reference_obj.matrix_world
            )
            ref_loc, ref_rot, ref_sca = reference_anchor_matrix.decompose()
            basis_matrix = compose_matrix(
                Vector((0.0, 0.0, 0.0)), ref_rot, ref_sca)

            material_names = []
            for slot in reference_obj.material_slots:
                if slot.material:
                    material_names.append(slot.material.name)

            asset = MeshAsset(
                mesh_data_name=mesh_data_name,
                short_id=short_id_val,
                asset_name=asset_name,
                reference_obj=reference_obj,
                instance_count=len(instances),
                basis_matrix=basis_matrix.copy(),
                material_names=material_names,
                material_count=len(material_names),
            )
            mesh_assets.append(asset)
            mesh_assets_by_data[mesh_data_name] = asset

        return mesh_assets, mesh_assets_by_data

    # ── 包围盒 ──

    @staticmethod
    def _compute_bounding_box(
        objects: list["bpy.types.Object"],
    ) -> dict:
        """计算世界空间包围盒。"""
        bbox_min = Vector((float('inf'), float('inf'), float('inf')))
        bbox_max = Vector((float('-inf'), float('-inf'), float('-inf')))

        for obj in objects:
            for v in obj.bound_box:
                wv = obj.matrix_world @ Vector(v)
                for i in range(3):
                    if wv[i] < bbox_min[i]:
                        bbox_min[i] = wv[i]
                    if wv[i] > bbox_max[i]:
                        bbox_max[i] = wv[i]

        size = bbox_max - bbox_min
        return {
            "min":  [round(bbox_min.x, 2), round(bbox_min.y, 2),
                     round(bbox_min.z, 2)],
            "max":  [round(bbox_max.x, 2), round(bbox_max.y, 2),
                     round(bbox_max.z, 2)],
            "size": [round(size.x, 2), round(size.y, 2), round(size.z, 2)],
        }

    # ── 主扫描流程 ──

    def scan(self) -> ExportContext:
        """执行完整场景扫描，返回 ExportContext。"""
        mesh_objects = self.iter_export_mesh_objects()
        anchor_obj = self.find_anchor()
        anchor_matrix = (anchor_obj.matrix_world.copy()
                         if anchor_obj else Matrix.Identity(4))
        anchor_inverse = anchor_matrix.inverted_safe()

        groups = self._group_by_mesh_data(mesh_objects)
        mesh_assets, mesh_assets_by_data = self._build_mesh_assets(
            groups, anchor_inverse)
        bounding_box = self._compute_bounding_box(mesh_objects)

        info(f"场景扫描完成: {len(mesh_objects)} 对象, "
             f"{len(mesh_assets)} 唯一 mesh data, "
             f"Anchor: {anchor_obj.name if anchor_obj else '无'}")

        return ExportContext(
            mesh_objects=mesh_objects,
            anchor_obj=anchor_obj,
            anchor_matrix=anchor_matrix,
            anchor_inverse=anchor_inverse,
            mesh_assets=mesh_assets,
            mesh_assets_by_data=mesh_assets_by_data,
            bounding_box=bounding_box,
        )


# ═══════════════════════════════════════════
#  GLBExporter
# ═══════════════════════════════════════════

class GLBExporter:
    """
    GLB 文件导出器。

    使用临时 Collection + Mesh Basis Bake 技术：
    1. 为每个唯一 mesh data 创建一份 clean copy
    2. 将 basis_matrix（旋转+缩放）bake 进顶点
    3. 临时对象放置在原点，隐藏原始对象
    4. 调用 Blender glTF 导出
    5. 恢复场景并清理临时资源
    """

    def __init__(self,
                 precision_mode: str = "LOSSLESS",
                 export_yup: bool = True,
                 export_dir: str = ""):
        """
        Args:
            precision_mode: Draco 精度模式
            export_yup: 是否启用 glTF Y-up
            export_dir: 导出目录
        """
        self.precision_mode = precision_mode
        self.export_yup = export_yup
        self.export_dir = export_dir

    def _create_temp_collection(self) -> "bpy.types.Collection":
        """创建临时 Collection 并链接到场景。"""
        temp_col = bpy.data.collections.new(TEMP_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(temp_col)
        return temp_col

    def _build_gltf_args(self, glb_path: str) -> dict:
        """构建 export_scene.gltf 的参数字典，含 Draco 版本自适应。"""
        preset = DRACO_PRESETS.get(self.precision_mode, DRACO_PRESETS["LOSSLESS"])

        gltf_kwargs = dict(
            filepath=glb_path,
            export_format='GLB',
            use_selection=True,
            export_apply=False,
            export_animations=False,
            export_morph=False,
            export_skins=False,
            export_materials='EXPORT',
            export_normals=True,
            export_texcoords=True,
            export_tangents=False,
            export_image_format='AUTO',
            export_texture_dir="",
            export_keep_originals=True,
            export_extras=True,
            export_yup=self.export_yup,
            export_cameras=False,
            export_lights=False,
        )

        if preset.get("enable", False):
            param_names = get_draco_param_names()
            gltf_kwargs[param_names["enable"]] = True
            gltf_kwargs[param_names["level"]] = preset["level"]
            gltf_kwargs[param_names["position"]] = preset["position"]
            gltf_kwargs[param_names["normal"]] = preset["normal"]
            gltf_kwargs[param_names["texcoord"]] = preset["texcoord"]
            gltf_kwargs[param_names["color"]] = preset["color"]
            gltf_kwargs[param_names["generic"]] = preset["generic"]
        else:
            param_names = get_draco_param_names()
            gltf_kwargs[param_names["enable"]] = False

        return gltf_kwargs

    def export(self, context: ExportContext,
               glb_filename: str = "meshes_anchor.glb") -> bool:
        """
        导出 GLB 文件。

        Args:
            context: 导出上下文
            glb_filename: GLB 文件名

        Returns:
            导出成功返回 True，失败返回 False
        """
        export_dir = self.export_dir or os.path.join(
            os.path.dirname(bpy.data.filepath or os.path.abspath(".")),
            "Exports")
        os.makedirs(export_dir, exist_ok=True)

        glb_path = os.path.join(export_dir, glb_filename)

        info("=" * 50)
        info(f"  [GLB 导出]  精度模式: {self.precision_mode}")
        info(f"  目标文件: {glb_path}")
        info(f"  场景对象数: {len(context.mesh_objects)}")
        info(f"  唯一网格数: {len(context.mesh_assets)}")
        info(f"  Anchor: {context.anchor_obj.name if context.anchor_obj else '无'}")

        temp_collection = self._create_temp_collection()
        temp_objects = []
        temp_meshes = []

        # 为每个 MeshAsset 创建临时 clean mesh
        for asset in context.mesh_assets:
            mesh_copy = asset.reference_obj.data.copy()
            # Bake basis_matrix（旋转+缩放）进顶点
            mesh_copy.transform(asset.basis_matrix)
            mesh_copy.update()

            temp_obj = bpy.data.objects.new(asset.asset_name, mesh_copy)
            temp_collection.objects.link(temp_obj)
            temp_obj.location = (0.0, 0.0, 0.0)
            temp_obj.rotation_euler = (0.0, 0.0, 0.0)
            temp_obj.scale = (1.0, 1.0, 1.0)

            temp_objects.append(temp_obj)
            temp_meshes.append(mesh_copy)

        # 隐藏原始对象
        hidden_originals = []
        for obj in context.mesh_objects:
            if obj.visible_get():
                obj.hide_set(True)
                hidden_originals.append(obj)

        try:
            # 选中所有临时对象
            bpy.ops.object.select_all(action='DESELECT')
            for obj in temp_objects:
                obj.select_set(True)
            if temp_objects:
                bpy.context.view_layer.objects.active = temp_objects[0]

            gltf_kwargs = self._build_gltf_args(glb_path)
            bpy.ops.export_scene.gltf(**gltf_kwargs)

        except Exception as e:
            error(f"GLB 导出失败: {e}")
            return False

        finally:
            # 恢复原始对象可见性
            for obj in hidden_originals:
                obj.hide_set(False)

            # 清理临时对象
            for obj in temp_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            for mesh in temp_meshes:
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            bpy.data.collections.remove(temp_collection)
            bpy.ops.object.select_all(action='DESELECT')

        file_size_mb = os.path.getsize(glb_path) / (1024 * 1024)
        info(f"  GLB 导出完成: {file_size_mb:.1f} MB")
        return True


# ═══════════════════════════════════════════
#  ManifestBuilder
# ═══════════════════════════════════════════

class ManifestBuilder:
    """
    Manifest JSON 构建器。

    生成包含以下内容的清单：
    - scene_anchor：场景统一参考
    - mesh_assets：唯一 mesh data 条目
    - objects：每个实例的坐标系转换信息
    - statistics：统计摘要
    - bounding_box：场景包围盒
    """

    def __init__(self,
                 naming_mode: str = "HASH_PREFIX",
                 precision_mode: str = "LOSSLESS",
                 export_yup: bool = True,
                 target_engine: str = "UE5"):
        """
        Args:
            naming_mode: 命名模式
            precision_mode: 精度模式
            export_yup: glTF Y-up 标志
            target_engine: 目标引擎名称
        """
        self.naming_mode = naming_mode
        self.precision_mode = precision_mode
        self.export_yup = export_yup
        self.target_engine = target_engine

    def _build_coordinate_info(self) -> dict:
        """根据目标引擎构建坐标系信息块。"""
        engine_specs = {
            "UE5":   {"up": "Z", "hand": "left",  "unit": "cm",
                       "dirs": {"X": "right", "Y": "left/back", "Z": "up"},
                       "conv": "Bl_X→UE5_Y*100, Bl_Y→UE5_X*100, Bl_Z→UE5_Z*100"},
            "Unity": {"up": "Y", "hand": "left",  "unit": "m",
                       "dirs": {"X": "right", "Y": "up", "Z": "forward"},
                       "conv": "-Bl_X→U_X, Bl_Z→U_Y, -Bl_Y→U_Z"},
            "Godot": {"up": "Y", "hand": "right", "unit": "m",
                       "dirs": {"X": "right", "Y": "up", "Z": "forward"},
                       "conv": "Bl_X→G_X, Bl_Z→G_Y, Bl_Y→G_Z"},
        }
        engine = engine_specs.get(self.target_engine, engine_specs["UE5"])
        return {
            "blender": {"up_axis": "Z", "handedness": "right", "unit": "m"},
            self.target_engine.lower(): {
                "up_axis": engine["up"],
                "handedness": engine["hand"],
                "unit": engine["unit"],
                "axis_directions": engine["dirs"],
            },
            "conversion": {
                "position": engine["conv"],
                "reconstruct_equation_blender":
                    "M_world = M_anchor @ M_reconstruct @ M_mesh_basis",
                "glb_basis_rule":
                    "glb干净网格烘烤了参考实例相对Anchor的旋转+缩放，不含平移",
            },
        }

    def _build_objects_list(self, context: ExportContext) -> list[dict]:
        """构建场景对象实例条目列表。"""
        objects_list = []
        for obj in context.mesh_objects:
            asset = context.mesh_assets_by_data.get(obj.data.name)
            if asset is None:
                continue

            anchor_relative_matrix = (
                context.anchor_inverse @ obj.matrix_world
            )
            reconstruct_matrix = (
                anchor_relative_matrix @ asset.basis_matrix.inverted_safe()
            )

            material_names = []
            for slot in obj.material_slots:
                if slot.material:
                    material_names.append(slot.material.name)

            # 提取前缀
            prefix = obj.name.split('__')[0] if '__' in obj.name else obj.name

            entry = {
                "name": obj.name,
                "prefix": prefix,
                "mesh_data": obj.data.name,
                "mesh_data_short_id": asset.short_id,
                "mesh_asset_name": asset.asset_name,
                "reference_object": asset.reference_obj.name,
                "is_reference_object": obj.name == asset.reference_obj.name,
                "original_parent": obj.parent.name if obj.parent else None,
                "anchor_relative_blender": serialize_blender_transform(
                    anchor_relative_matrix),
                "reconstruct_relative_blender": serialize_blender_transform(
                    reconstruct_matrix),
                "reconstruct_relative_target": serialize_engine_transform(
                    reconstruct_matrix, self.target_engine),
                "materials": material_names,
                "material_count": len(material_names),
                "visible": obj.visible_get(),
            }
            objects_list.append(entry)

        return objects_list

    def _build_assets_list(self, context: ExportContext) -> list[dict]:
        """构建 MeshAsset 条目列表。"""
        assets_payload = []
        for asset in context.mesh_assets:
            # 计算参考对象相对 Anchord 的矩阵
            reference_anchor_matrix = (
                context.anchor_inverse @ asset.reference_obj.matrix_world
            )
            assets_payload.append({
                "mesh_data": asset.mesh_data_name,
                "mesh_data_short_id": asset.short_id,
                "mesh_asset_name": asset.asset_name,
                "reference_object": asset.reference_obj.name,
                "instance_count": asset.instance_count,
                "reference_object_anchor_relative_blender":
                    serialize_blender_transform(reference_anchor_matrix),
                "basis_relative_to_anchor_blender":
                    serialize_blender_transform(asset.basis_matrix),
                "basis_relative_to_anchor_target":
                    serialize_engine_transform(
                        asset.basis_matrix, self.target_engine),
                "materials": asset.material_names,
                "material_count": asset.material_count,
            })
        return assets_payload

    def _build_statistics(self, context: ExportContext) -> dict:
        """构建统计摘要。"""
        shared_mesh_blocks = sum(
            1 for a in context.mesh_assets if a.instance_count > 1)
        unique_mesh_blocks = len(context.mesh_assets) - shared_mesh_blocks
        total_shared_instances = sum(
            a.instance_count - 1 for a in context.mesh_assets
            if a.instance_count > 1)

        return {
            "total_objects": len(context.mesh_objects),
            "unique_mesh_data_blocks": len(context.mesh_assets),
            "shared_mesh_data_blocks": shared_mesh_blocks,
            "unique_mesh_blocks": unique_mesh_blocks,
            "total_shared_instances": total_shared_instances,
            "total_materials": len(bpy.data.materials),
        }

    def build(self, context: ExportContext,
              scene_name: str = "untitled_scene",
              glb_filename: str = "meshes_anchor.glb",
              manifest_filename: str = "manifest_v30.json") -> dict:
        """
        构建完整的 manifest dict。

        Args:
            context: 导出上下文
            scene_name: 场景名称
            glb_filename: GLB 文件名
            manifest_filename: Manifest 文件名

        Returns:
            manifest 字典
        """
        objects_list = self._build_objects_list(context)
        assets_list = self._build_assets_list(context)
        statistics = self._build_statistics(context)

        manifest = {
            "version": "3.0",
            "format": "anchor_mesh_basis_manifest",
            "scene_name": scene_name,
            "export_time": datetime.now().isoformat(),
            "blender_version": (f"{bpy.app.version[0]}."
                                f"{bpy.app.version[1]}."
                                f"{bpy.app.version[2]}"),
            "glb_file": glb_filename,
            "manifest_file": manifest_filename,
            "precision_mode": self.precision_mode,
            "naming_mode": self.naming_mode,
            "export_yup": self.export_yup,
            "target_engine": self.target_engine,
            "pipeline_mode": "anchor_plus_mesh_basis_compensation",
            "bounding_box": context.bounding_box,
            "coordinate_system": self._build_coordinate_info(),
            "scene_anchor": {
                "name": (context.anchor_obj.name
                         if context.anchor_obj else "VIRTUAL_ROOT"),
                "type": (context.anchor_obj.type
                         if context.anchor_obj else "VIRTUAL_ROOT"),
                "source": ("BLENDER_OBJECT"
                           if context.anchor_obj else "IDENTITY_FALLBACK"),
                "blender_world": serialize_blender_transform(
                    context.anchor_matrix),
                "target_world": serialize_engine_transform(
                    context.anchor_matrix, self.target_engine),
            },
            "statistics": statistics,
            "mesh_assets": assets_list,
            "objects": objects_list,
        }

        info(f"Manifest 构建完成: {len(objects_list)} 对象条目, "
             f"{len(assets_list)} Mesh 资产")
        return manifest

    @staticmethod
    def write(manifest: dict, path: str) -> None:
        """
        将 manifest 写入 JSON 文件。

        Args:
            manifest: manifest 字典
            path: 输出文件路径
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        size_kb = os.path.getsize(path) / 1024
        info(f"Manifest 导出完成: {size_kb:.1f} KB → {path}")


# ═══════════════════════════════════════════
#  ExportPipeline
# ═══════════════════════════════════════════

class ExportPipeline:
    """
    导出管线编排器。

    串联 SceneScanner → GLBExporter → ManifestBuilder 三个阶段。
    """

    def __init__(self,
                 anchor_name: str = DEFAULT_ANCHOR_NAME,
                 include_hidden: bool = False,
                 naming_mode: str = "HASH_PREFIX",
                 max_name_length: int = MAX_ASSET_NAME_LENGTH,
                 precision_mode: str = "LOSSLESS",
                 export_yup: bool = True,
                 export_dir: str = "",
                 target_engine: str = "UE5"):
        """
        Args:
            anchor_name: 锚点对象名
            include_hidden: 是否包含隐藏对象
            naming_mode: 资产命名模式
            max_name_length: 资产名最大长度
            precision_mode: 精度模式
            export_yup: glTF Y-up
            export_dir: 导出目录
            target_engine: 目标引擎
        """
        self.export_dir = export_dir
        self.scene_name = ""
        self.glb_filename = ""
        self.manifest_filename = ""

        # 确定导出基名
        blend_path = bpy.data.filepath
        if blend_path:
            self.scene_name = os.path.splitext(
                os.path.basename(blend_path))[0]
        else:
            self.scene_name = "untitled_scene"

        self.glb_filename = f"{self.scene_name}_meshes_anchor.glb"
        self.manifest_filename = f"{self.scene_name}_manifest_v30.json"

        self.scanner = SceneScanner(
            anchor_name=anchor_name,
            include_hidden=include_hidden,
            naming_mode=naming_mode,
            max_name_length=max_name_length,
            glb_basename=os.path.splitext(self.glb_filename)[0],
        )
        self.exporter = GLBExporter(
            precision_mode=precision_mode,
            export_yup=export_yup,
            export_dir=export_dir,
        )
        self.manifest_builder = ManifestBuilder(
            naming_mode=naming_mode,
            precision_mode=precision_mode,
            export_yup=export_yup,
            target_engine=target_engine,
        )

    def run(self) -> tuple[bool, Optional[dict]]:
        """
        执行导出管线。

        Returns:
            (success, manifest_dict) — 成功时 manifest_dict 不为 None
        """
        info("=" * 50)
        info(f"  开始导出管线")
        info(f"  场景: {self.scene_name}")
        info(f"  GLB: {self.glb_filename}")
        info(f"  Manifest: {self.manifest_filename}")
        info("=" * 50)

        # 阶段 1：场景扫描
        context = self.scanner.scan()
        if not context.mesh_objects:
            warn("未找到可导出的 Mesh 对象")
            return False, None

        # 阶段 2：Manifest 构建（在 GLB 导出前于内存中完成）
        manifest = self.manifest_builder.build(
            context,
            scene_name=self.scene_name,
            glb_filename=self.glb_filename,
            manifest_filename=self.manifest_filename,
        )

        # 阶段 3：GLB 导出
        export_dir = self.export_dir or os.path.join(
            os.path.dirname(bpy.data.filepath or os.path.abspath(".")),
            "Exports")
        self.exporter.export_dir = export_dir

        success = self.exporter.export(context, self.glb_filename)
        if not success:
            error("GLB 导出失败，跳过 Manifest 写盘")
            return False, None

        # 阶段 4：Manifest 写盘
        manifest_path = os.path.join(export_dir, self.manifest_filename)
        self.manifest_builder.write(manifest, manifest_path)

        info("导出管线完成")
        return True, manifest
