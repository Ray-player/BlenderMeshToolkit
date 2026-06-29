"""
UE5.5 关卡 Actor 变换数据导出脚本

用途：
    在 UE5 中导出当前关卡里的 StaticMeshActor 世界变换，输出为 JSON，
    供本地诊断脚本读取，用于验证 Blender -> UE5 重建结果是否正确。

输入：
    - 当前已打开并完成重建的 UE5 关卡
    - 当前脚本中的导出路径、场景基名、Anchor 检测等配置

输出：
    - `<scene>_exported_actors.json`
    - 其中包含 Actor 名称、StaticMesh 名、世界位置、旋转、缩放、父级与文件夹信息

命名联动：
    - 支持基于 Blender 项目文件名（scene_export_basename）自动拼接导出文件名
    - 当 `output_path` 留空时，自动输出到：
      `F:/Library/BlenderWork/Exports/<scene_export_basename>_exported_actors.json`

建议流程：
    1. Blender 运行 `export_glb_and_manifest.py` 生成 GLB 与 manifest
    2. 本地运行 `Scripts/tools/verify_json_export.py` 检查 manifest 结构
    3. UE5 运行 `ue5_reconstruct_simple.py` 重建场景
    4. UE5 运行本脚本导出当前关卡实际结果
    5. 本地运行 `Scripts/tools/diagnose_rotation_error.py` 或其他诊断脚本分析偏差

注意事项：
    - 默认导出全部 StaticMeshActor；如需只导出选中对象，可切换 `selected_only`
    - 可自动识别 Anchor Actor，并记录每个对象是否挂在检测到的 Anchor 之下
    - 导出结果主要服务于闭环验证，不参与场景重建本身
"""

import unreal
import json
import os
import time


CONFIG = {
    # 留空则按 scene_export_basename 自动导出到工作区 Exports 目录
    "output_path": "",
    # 与 Blender 导出端保持一致的场景基名；用于自动拼接 exported_actors 文件名
    "scene_export_basename": "jidianGuanD",
    "selected_only": False,
    "include_mesh_path": True,
    "verbose": False,
    "detect_anchor_actor": True,
    "anchor_label_keywords": ["_Anchor", "UE_Anchor"],
}


def log(msg, level="info"):
    prefix = "[Export-Actors-v3]"
    if level == "warning":
        unreal.log_warning(f"{prefix} {msg}")
    elif level == "error":
        unreal.log_error(f"{prefix} {msg}")
    else:
        unreal.log(f"{prefix} {msg}")


def resolve_default_output_path():
    basename = (CONFIG.get("scene_export_basename") or "").strip() or "untitled_scene"
    return f"F:/Library/BlenderWork/Exports/{basename}_exported_actors.json"


def get_output_path():
    raw = (CONFIG["output_path"] or "").strip()
    if not raw:
        raw = resolve_default_output_path()
    if raw and os.path.isabs(raw):
        return raw

    project_dir = None
    try:
        project_dir = unreal.Paths.project_dir()
        if project_dir:
            project_dir = project_dir.rstrip("/\\")
    except Exception as e:
        log(f"unreal.Paths.project_dir() 失败: {e}", "warning")

    if not project_dir or not os.path.isdir(project_dir):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
        if not os.path.isdir(project_dir):
            project_dir = "C:/tmp"
            os.makedirs(project_dir, exist_ok=True)

    if raw and raw.startswith("/Game/"):
        rel = raw.replace("/Game/", "", 1).lstrip("/")
        return os.path.join(project_dir, "Content", rel)

    return os.path.join(project_dir, raw if raw else "exported_actors.json")


def get_actor_transform(actor):
    try:
        loc = actor.get_actor_location()
        location = [loc.x, loc.y, loc.z]
    except Exception as e:
        log(f"获取位置失败: {e}", "warning")
        location = [0, 0, 0]

    quaternion = [1, 0, 0, 0]
    euler_deg = [0, 0, 0]
    try:
        rot = actor.get_actor_rotation()
        euler_deg = [rot.pitch, rot.yaw, rot.roll]
        try:
            quat = rot.to_quaternion()
        except Exception:
            try:
                quat = rot.quaternion()
            except Exception:
                quat = unreal.Quat()
                import math
                px = math.radians(rot.pitch / 2)
                py = math.radians(rot.yaw / 2)
                rz = math.radians(rot.roll / 2)
                cx, sx = math.cos(px), math.sin(px)
                cy, sy = math.cos(py), math.sin(py)
                cz, sz = math.cos(rz), math.sin(rz)
                quat = unreal.Quat(
                    sx*cy*cz - cx*sy*sz,
                    cx*sy*cz + sx*cy*sz,
                    cx*cy*sz - sx*sy*cz,
                    cx*cy*cz + sx*sy*sz
                )
        quaternion = [quat.w, quat.x, quat.y, quat.z]
    except Exception as e:
        log(f"获取旋转失败: {e}", "warning")

    try:
        scale = actor.get_actor_scale3d()
        scale_list = [scale.x, scale.y, scale.z]
    except Exception as e:
        log(f"获取缩放失败: {e}", "warning")
        scale_list = [1, 1, 1]

    return location, quaternion, euler_deg, scale_list


def get_static_mesh_name(actor):
    if not CONFIG["include_mesh_path"]:
        return ""

    try:
        sm_comp = actor.get_editor_property('static_mesh_component')
    except Exception:
        try:
            sm_comp = actor.static_mesh_component
        except Exception:
            return ""

    if not sm_comp:
        return ""

    try:
        sm = sm_comp.get_editor_property('static_mesh')
    except Exception:
        try:
            sm = sm_comp.static_mesh
        except Exception:
            return ""

    if not sm:
        return ""

    try:
        return str(sm.get_fname())
    except Exception:
        try:
            asset_path = sm.get_path_name()
            return asset_path.rsplit("/", 1)[-1]
        except Exception:
            return ""


def get_actor_folder(actor):
    try:
        return str(actor.get_folder_path())
    except Exception:
        try:
            return str(actor.folder_path)
        except Exception:
            return ""


def get_parent_label(actor):
    try:
        parent = actor.get_attach_parent_actor()
    except Exception:
        parent = None
    if not parent:
        return None
    try:
        return parent.get_actor_label()
    except Exception:
        try:
            return parent.get_name()
        except Exception:
            return None


def detect_anchor_actor(all_actors):
    if not CONFIG["detect_anchor_actor"]:
        return None

    keywords = CONFIG.get("anchor_label_keywords", [])
    for actor in all_actors:
        if isinstance(actor, unreal.StaticMeshActor):
            continue
        try:
            label = actor.get_actor_label()
        except Exception:
            continue
        for keyword in keywords:
            if keyword and keyword in label:
                return actor
    return None


def export_actors():
    output_path = get_output_path()
    abs_output = os.path.abspath(output_path)
    log("=" * 60)
    log("  UE5 关卡 Actor 变换数据导出（v3 闭环友好版）")
    log(f"  输出文件: {abs_output}")
    log("=" * 60)

    world = unreal.EditorLevelLibrary.get_editor_world()
    level_name = world.get_name() if world else "Unknown"
    log(f"当前关卡: {level_name}")

    if CONFIG["selected_only"]:
        actors = unreal.EditorLevelLibrary.get_selected_level_actors()
        log(f"导出模式: 仅选中 Actor ({len(actors)} 个)")
    else:
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
        log(f"导出模式: 全部 Actor ({len(actors)} 个)")

    anchor_actor = detect_anchor_actor(actors)
    if anchor_actor:
        try:
            anchor_label = anchor_actor.get_actor_label()
        except Exception:
            anchor_label = "UnknownAnchor"
        log(f"检测到 Anchor Actor: {anchor_label}")
    else:
        anchor_label = None
        log("未检测到 Anchor Actor（继续导出，不影响结果）", "warning")

    sm_actors = []
    skipped = 0
    for actor in actors:
        if isinstance(actor, unreal.StaticMeshActor):
            sm_actors.append(actor)
        else:
            skipped += 1

    log(f"StaticMeshActor: {len(sm_actors)} 个, 其他 Actor: {skipped} 个")
    if len(sm_actors) == 0:
        log("未找到任何 StaticMeshActor!", "warning")
        return

    log("开始收集变换数据...")
    start_time = time.time()
    actors_data = []

    for i, actor in enumerate(sm_actors):
        if CONFIG["verbose"] and i % 500 == 0:
            log(f"  处理进度: {i}/{len(sm_actors)}")

        display_name = actor.get_actor_label()
        try:
            location, quaternion, euler_deg, scale = get_actor_transform(actor)
        except Exception as e:
            log(f"获取变换失败: {display_name}: {e}", "warning")
            continue

        mesh_name = get_static_mesh_name(actor)
        folder_path = get_actor_folder(actor)
        parent_label = get_parent_label(actor)

        actors_data.append({
            "name": display_name,
            "class": type(actor).__name__,
            "static_mesh": mesh_name,
            "location": location,
            "rotation_quaternion": quaternion,
            "rotation_euler_deg": euler_deg,
            "scale": scale,
            "folder_path": folder_path,
            "attach_parent": parent_label,
            "is_under_detected_anchor": bool(anchor_label and parent_label == anchor_label),
        })

    elapsed = time.time() - start_time
    log(f"数据收集完成: {len(actors_data)} 个 Actor, 耗时 {elapsed:.1f} 秒")

    result = {
        "version": "3.0",
        "export_mode": "ue5_actor_snapshot_for_v3_loop",
        "level_name": level_name,
        "export_time": time.strftime("%Y-%m-%dT%H:%M:%S.000000", time.localtime()),
        "coordinate_system": {
            "up": "Z",
            "handedness": "left",
            "unit": "cm",
            "rotation_order": "quaternion [w, x, y, z]"
        },
        "detected_anchor_actor": anchor_label,
        "total_actors": len(actors_data),
        "actors": actors_data,
    }

    log(f"写入文件: {abs_output}")
    try:
        os.makedirs(os.path.dirname(abs_output), exist_ok=True)
        with open(abs_output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"写入失败: {e}", "error")
        return

    if not os.path.exists(abs_output):
        log(f"写入操作完成但文件不存在: {abs_output}", "error")
        return

    size_mb = os.path.getsize(abs_output) / (1024 * 1024)
    log("  ✓ 导出成功!")
    log(f"  完整路径: {abs_output}")
    log(f"  共导出 {len(actors_data)} 个 StaticMeshActor")
    log(f"  文件大小: {size_mb:.2f} MB")
    log("=" * 60)
    log("  导出完成，可直接回到工作区运行 Scripts/tools/diagnose_rotation_error.py")
    log("=" * 60)


if __name__ == "__main__":
    export_actors()
