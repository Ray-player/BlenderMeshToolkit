"""
UE5.5 场景重建脚本（Anchor + Mesh 基准补偿版）

用途：
    在 UE5 中读取 Blender 导出的 manifest，批量重建 StaticMeshActor 场景。
    脚本会自动创建 Anchor，恢复每个对象相对 Anchor 的位置、旋转与缩放，
    并根据 short id / 资产名在内容目录中查找对应 StaticMesh 资产。

输入：
    - `manifest_v30.json` 中的 `scene_anchor`、`mesh_assets`、`objects`
    - `mesh_asset_base_path` 指向的 UE5 StaticMesh 资产目录
    - 当前脚本中的重建、匹配、补偿相关配置

输出：
    - 当前关卡中的 Anchor Actor
    - 按 manifest 批量生成并附加到 Anchor 的 StaticMeshActor
    - 可选失败清单 `failed_actors_v4.txt`

命名联动：
    - 支持按 Blender 项目文件名自动推断 manifest 文件名
    - 默认优先使用 CONFIG["manifest_path"]；若为空，则根据 CONFIG["scene_export_basename"]
      或默认场景名自动拼出 `<basename>_manifest_v30.json`
    - 资产匹配优先使用 short id，再回退到资产名与规范化前后缀匹配

建议流程：
    1. 先运行 `export_glb_and_manifest.py` 生成 GLB 与 manifest
    2. 在 UE5 中导入 GLB 对应的 StaticMesh 资产
    3. 将 manifest 放到脚本可读取的位置
    4. 运行本脚本重建场景
    5. 如需验证，再运行 `ue5_export_actors.py` 导出闭环结果

注意事项：
    - mesh 的 basis 已在 Blender 导出 GLB 时 bake 进顶点
    - UE5 侧不再对单个 mesh 做额外 basis 补偿，只使用 `reconstruct_relative_ue5` 重建
    - 当前 world 组合逻辑为：`child_world = anchor_world * child_relative`
"""

import unreal
import json
import os
import re
import time
import math


CONFIG = {
    # 可手动指定 manifest 路径；留空则按 scene_export_basename 自动拼出
    "manifest_path": "",
    # 当 manifest_path 为空时，使用此基名自动推导 `<basename>_manifest_v30.json`
    "scene_export_basename": "jidianGuanNew",
    "mesh_asset_base_path": "/Game/Models/Equip_glb/mesh/",
    "batch_size": 100,
    "verbose": False,
    "anchor_actor_label_suffix": "_Anchor",
    # ===== 旋转补偿（v3.1 导出 + UE5 端 local rotation 补偿） =====
    # +90° Z 补偿已验证可修正 Blender→glTF→Interchange 链路残余旋转偏差
    "local_rotation_compensation_z_deg": 90.0,
}


def log(msg, level="info"):
    prefix = "[Reconstruct-v4]"
    if level == "warning":
        unreal.log_warning(f"{prefix} {msg}")
    elif level == "error":
        unreal.log_error(f"{prefix} {msg}")
    else:
        unreal.log(f"{prefix} {msg}")


def resolve_manifest_path():
    raw = (CONFIG.get("manifest_path") or "").strip()
    if raw:
        return raw

    basename = (CONFIG.get("scene_export_basename") or "").strip() or "untitled_scene"
    return f"/Game/Python/{basename}_manifest_v30.json"


def load_manifest(manifest_path):
    if not os.path.isabs(manifest_path):
        manifest_path = os.path.join(unreal.Paths.project_content_dir(), manifest_path.lstrip("/"))

    log(f"加载清单: {manifest_path}")
    if not os.path.exists(manifest_path):
        alt_path = manifest_path.replace("/Game/", "")
        alt_path = os.path.join(unreal.Paths.project_content_dir(), alt_path)
        if os.path.exists(alt_path):
            manifest_path = alt_path
            log(f"使用替代路径: {manifest_path}", "warning")
        else:
            log(f"找不到清单文件: {manifest_path}", "error")
            log(f"  也尝试了: {alt_path}", "error")
            return None

    with open(manifest_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _normalize_name(name):
    return re.sub(r'[^A-Za-z0-9\u4e00-\u9fff]', '', name).lower()


_HASH_SUFFIX_RE = re.compile(r'(^|_)M([0-9a-fA-F]{8})(?:_|$)')


def _split_asset_tokens(name):
    clean = name[3:] if name.startswith("SM_") else name
    match = _HASH_SUFFIX_RE.search(clean)
    short_id = None
    prefix = clean
    suffix = ""
    if match:
        short_id = "M" + match.group(2)
        prefix = clean[:match.start()].rstrip('_')
        suffix = clean[match.end():].lstrip('_')
    return {
        "clean": clean,
        "short_id": short_id,
        "prefix": prefix,
        "suffix": suffix,
        "normalized_clean": _normalize_name(clean),
        "normalized_prefix": _normalize_name(prefix),
        "normalized_suffix": _normalize_name(suffix),
    }



def scan_static_mesh_assets(base_path):
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = []
    base_clean = base_path.rstrip("/")

    try:
        filter_obj = unreal.ARFilter()
        filter_obj.package_paths = [base_clean]
        filter_obj.recursive_paths = True
        filter_obj.class_paths = [unreal.TopLevelAssetPath("/Script/Engine", "StaticMesh")]
        assets = asset_registry.get_assets(filter_obj)
        log(f"ARFilter 方式找到 {len(assets)} 个候选资产")
    except Exception as e_a:
        log(f"ARFilter 方式失败 ({e_a}), 尝试 get_assets_by_class", "warning")
        assets = []
        try:
            class_path = unreal.TopLevelAssetPath("/Script/Engine", "StaticMesh")
            all_assets = asset_registry.get_assets_by_class(class_path, True)
            for ad in all_assets:
                pkg = str(ad.package_name)
                if base_clean in pkg:
                    assets.append(ad)
            log(f"get_assets_by_class 过滤后得到 {len(assets)} 个资产")
        except Exception as e_b:
            log(f"get_assets_by_class 也失败 ({e_b}), 尝试 EditorAssetLibrary", "warning")
            assets = []
            try:
                asset_paths = unreal.EditorAssetLibrary.list_assets(base_clean, True, False)
                for ap in asset_paths:
                    obj = unreal.EditorAssetLibrary.load_asset(ap)
                    if obj and isinstance(obj, unreal.StaticMesh):
                        name = ap.rsplit(".", 1)[-1] if "." in ap else ap.rsplit("/", 1)[-1]
                        _fake_ad = type('obj', (object,), {
                            'package_name': ap.rsplit(".", 1)[0],
                            'asset_name': name,
                            'asset_class_path': unreal.TopLevelAssetPath("/Script/Engine", "StaticMesh"),
                            '_loaded_sm': obj,
                        })()
                        assets.append(_fake_ad)
                log(f"EditorAssetLibrary 兜底找到 {len(assets)} 个 StaticMesh")
            except Exception as e_c:
                log(f"所有扫描方式均失败! ({e_c})", "error")

    cache = {}
    normalized_cache = {}
    hash_cache = {}
    prefix_cache = {}

    for asset_data in assets:
        pkg = str(asset_data.package_name)
        name = str(asset_data.asset_name)

        cls_str = ""
        try:
            acp = asset_data.asset_class_path
            cls_str = str(acp.asset_name) if hasattr(acp, 'asset_name') else str(acp)
        except Exception:
            pass
        if not cls_str:
            try:
                cls_str = str(asset_data.asset_class)
            except Exception:
                cls_str = ""
        if "StaticMesh" not in cls_str and cls_str:
            continue

        sm = None
        if hasattr(asset_data, '_loaded_sm') and asset_data._loaded_sm:
            sm = asset_data._loaded_sm
        else:
            try:
                sm = unreal.AssetRegistryHelpers.get_asset(asset_data)
            except Exception:
                try:
                    sm = asset_data.get_asset()
                except Exception:
                    try:
                        sm = unreal.EditorAssetLibrary.load_asset(f"{pkg}.{name}")
                    except Exception:
                        pass

        if sm and isinstance(sm, unreal.StaticMesh):
            cache[name] = sm
            token_info = _split_asset_tokens(name)
            norm = token_info["normalized_clean"]
            if norm and norm not in normalized_cache:
                normalized_cache[norm] = sm

            short_id = token_info["short_id"]
            if short_id and short_id not in hash_cache:
                hash_cache[short_id] = sm

            prefix_key = token_info["normalized_prefix"]
            if prefix_key:
                prefix_cache.setdefault(prefix_key, []).append({
                    "name": name,
                    "sm": sm,
                    "short_id": short_id,
                    "suffix": token_info["suffix"],
                    "normalized_suffix": token_info["normalized_suffix"],
                    "normalized_clean": token_info["normalized_clean"],
                })

    log(f"资产扫描完成: cache={len(cache)}, normalized={len(normalized_cache)}, hash={len(hash_cache)}, prefix={len(prefix_cache)}")
    return cache, normalized_cache, hash_cache, prefix_cache


def _choose_prefix_fallback(asset_name, prefix_cache):
    if not asset_name or not prefix_cache:
        return None, None

    expected = _split_asset_tokens(asset_name)
    prefix_key = expected["normalized_prefix"]
    candidates = prefix_cache.get(prefix_key, []) if prefix_key else []
    if not candidates:
        return None, None

    expected_suffix = expected["normalized_suffix"]
    if expected_suffix:
        suffix_matches = [c for c in candidates if c["normalized_suffix"] == expected_suffix]
        if len(suffix_matches) == 1:
            return suffix_matches[0]["sm"], suffix_matches[0]["name"]
        if len(suffix_matches) > 1 and expected["short_id"]:
            exact = [c for c in suffix_matches if c["short_id"] == expected["short_id"]]
            if len(exact) == 1:
                return exact[0]["sm"], exact[0]["name"]

    if len(candidates) == 1:
        return candidates[0]["sm"], candidates[0]["name"]

    return None, None


def find_mesh_in_cache(mesh_data_name, mesh_cache, normalized_cache=None, short_id=None, asset_name=None, hash_cache=None, prefix_cache=None):
    if short_id and hash_cache and short_id in hash_cache:
        return hash_cache[short_id], "short_id"
    if asset_name and asset_name in mesh_cache:
        return mesh_cache[asset_name], "asset_name_exact"
    if short_id:
        sm_key = f"SM_{short_id}"
        if sm_key in mesh_cache:
            return mesh_cache[sm_key], "short_id_exact_name"
        if short_id in mesh_cache:
            return mesh_cache[short_id], "short_id_raw"
    if mesh_data_name in mesh_cache:
        return mesh_cache[mesh_data_name], "mesh_data_exact"
    sm_name = f"SM_{mesh_data_name}"
    if sm_name in mesh_cache:
        return mesh_cache[sm_name], "sm_mesh_data_exact"

    fallback_sm, fallback_name = _choose_prefix_fallback(asset_name, prefix_cache)
    if fallback_sm:
        return fallback_sm, f"prefix_fallback:{fallback_name}"

    for cache_key, sm in mesh_cache.items():
        stripped_key = re.sub(r'(^|_)M[0-9a-fA-F]{8}(?:_|$)', '_', cache_key).strip('_')
        if stripped_key != cache_key and stripped_key == sm_name:
            return sm, "stripped_hash_match"
    if normalized_cache:
        norm = _normalize_name(mesh_data_name)
        if norm and norm in normalized_cache:
            return normalized_cache[norm], "normalized_mesh_data"
    for cache_name, sm in mesh_cache.items():
        clean = cache_name[3:] if cache_name.startswith("SM_") else cache_name
        if mesh_data_name in clean or clean in mesh_data_name:
            return sm, "substring_match"
    return None, None



# ========= 数学工具 =========
def quat_normalize(q):
    norm = math.sqrt(sum(v * v for v in q))
    if norm <= 1e-8:
        return [1.0, 0.0, 0.0, 0.0]
    return [v / norm for v in q]


def quat_multiply_raw(q1, q2):
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return [
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
    ]


def quat_multiply(q1, q2):
    return quat_normalize(quat_multiply_raw(q1, q2))


def quat_conjugate(q):
    w, x, y, z = q
    return [w, -x, -y, -z]


def quat_rotate_vector(q, v):
    qn = quat_normalize(q)
    vq = [0.0, v[0], v[1], v[2]]
    rq = quat_multiply_raw(quat_multiply_raw(qn, vq), quat_conjugate(qn))
    return [rq[1], rq[2], rq[3]]


def component_mul(a, b):
    return [a[0] * b[0], a[1] * b[1], a[2] * b[2]]


def combine_transform(anchor, rel):
    scaled_loc = component_mul(anchor["scale"], rel["location"])
    rotated_loc = quat_rotate_vector(anchor["rotation"], scaled_loc)
    world_loc = [
        anchor["location"][0] + rotated_loc[0],
        anchor["location"][1] + rotated_loc[1],
        anchor["location"][2] + rotated_loc[2],
    ]
    world_rot = quat_multiply(anchor["rotation"], rel["rotation"])
    world_scale = component_mul(anchor["scale"], rel["scale"])
    return {
        "location": world_loc,
        "rotation": world_rot,
        "scale": world_scale,
    }


def quat_to_rotator(qw, qx, qy, qz):
    quat = unreal.Quat(qx, qy, qz, qw)
    return quat.rotator()


def spawn_anchor_actor(anchor_world, actor_label):
    rotator = quat_to_rotator(*anchor_world["rotation"])
    location = unreal.Vector(anchor_world["location"][0], anchor_world["location"][1], anchor_world["location"][2])
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.Actor, location, rotator)
    if not actor:
        return None
    actor.set_actor_location(location, False, False)
    actor.set_actor_rotation(rotator, False)
    actor.set_actor_scale3d(unreal.Vector(anchor_world["scale"][0], anchor_world["scale"][1], anchor_world["scale"][2]))
    actor.set_actor_label(actor_label)

    try:
        root_comp = actor.get_editor_property('root_component')
    except Exception:
        root_comp = None

    if root_comp:
        try:
            root_comp.set_editor_property('mobility', unreal.ComponentMobility.STATIC)
        except Exception:
            try:
                root_comp.mobility = unreal.ComponentMobility.STATIC
            except Exception:
                log(f"无法将 Anchor 根组件设置为 Static: {actor_label}", "warning")

    return actor


def spawn_static_mesh_actor(static_mesh, world_transform, actor_label):
    rotator = quat_to_rotator(*world_transform["rotation"])
    location = unreal.Vector(world_transform["location"][0], world_transform["location"][1], world_transform["location"][2])

    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor, location, rotator)
    if not actor:
        return None

    actor.set_actor_location(location, False, False)
    actor.set_actor_rotation(rotator, False)
    actor.set_actor_label(actor_label)

    try:
        sm_comp = actor.get_editor_property('static_mesh_component')
    except Exception:
        try:
            sm_comp = actor.static_mesh_component
        except Exception:
            log(f"无法获取 static_mesh_component: {actor_label}", "error")
            return actor

    if sm_comp:
        sm_comp.set_static_mesh(static_mesh)
        try:
            sm_comp.set_editor_property('relative_scale3d', unreal.Vector(world_transform["scale"][0], world_transform["scale"][1], world_transform["scale"][2]))
        except Exception:
            actor.set_actor_scale3d(unreal.Vector(world_transform["scale"][0], world_transform["scale"][1], world_transform["scale"][2]))

    return actor


def reconstruct_level():
    manifest_path = resolve_manifest_path()
    log("=" * 60)
    log("  UE5 场景重建（Anchor + Mesh Basis 版）")
    log(f"  JSON: {manifest_path}")
    log(f"  Assets: {CONFIG['mesh_asset_base_path']}")
    log("=" * 60)

    manifest = load_manifest(manifest_path)
    if not manifest:
        return

    version = manifest.get("version", "unknown")
    if version != "3.0":
        log(f"当前脚本要求 manifest v3.0，但收到: {version}", "error")
        return

    scene_name = manifest.get("scene_name", "ImportedFromBlender")
    anchor_info = manifest.get("scene_anchor", {})
    objects = manifest.get("objects", [])
    mesh_assets = manifest.get("mesh_assets", [])

    if not objects:
        log("manifest 中无 objects 数据", "error")
        return

    try:
        editor_actor_subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    except Exception as e:
        log(f"EditorActorSubsystem 初始化失败 ({e}), 将无法使用文件夹分组", "warning")
        editor_actor_subsys = None

    mesh_cache, normalized_cache, hash_cache, prefix_cache = scan_static_mesh_assets(CONFIG["mesh_asset_base_path"])
    if len(mesh_cache) == 0:
        log("未找到任何 StaticMesh 资产，请确认 GLB 已导入", "error")
        return

    anchor_world_data = anchor_info.get("ue5_world", {})
    anchor_world = {
        "location": anchor_world_data.get("location", [0.0, 0.0, 0.0]),
        "rotation": anchor_world_data.get("rotation_quaternion", [1.0, 0.0, 0.0, 0.0]),
        "scale": anchor_world_data.get("scale", [1.0, 1.0, 1.0]),
    }

    # ===== 方案B：每个 Actor 相对于 Anchor 的 Z 轴 local rotation 补偿 =====
    comp_z_deg = CONFIG.get("local_rotation_compensation_z_deg", 0.0)
    q_comp = None
    if abs(comp_z_deg) > 0.001:
        half = math.radians(comp_z_deg / 2.0)
        q_comp = [math.cos(half), 0.0, 0.0, math.sin(half)]
        log(f"Actor Local Z 旋转补偿: {comp_z_deg:.1f}°")
        log(f"  补偿四元数: [{q_comp[0]:.6f}, {q_comp[1]:.6f}, {q_comp[2]:.6f}, {q_comp[3]:.6f}]")
    # ======================================================================

    anchor_label = f"{scene_name}{CONFIG['anchor_actor_label_suffix']}"
    anchor_actor = spawn_anchor_actor(anchor_world, anchor_label)
    if not anchor_actor:
        log("Anchor Actor 创建失败", "error")
        return

    if editor_actor_subsys:
        try:
            editor_actor_subsys.set_actor_folder(anchor_actor, scene_name)
        except Exception:
            pass

    log(f"Anchor Actor 已创建: {anchor_label}")
    log(f"对象数: {len(objects)} | Mesh 资产数: {len(mesh_assets)}")

    spawned = 0
    failed = 0
    failed_names = []
    start_time = time.time()

    for i, obj in enumerate(objects):
        if i > 0 and i % CONFIG["batch_size"] == 0:
            elapsed = time.time() - start_time
            rate = spawned / elapsed if elapsed > 0 else 0
            log(f"  进度: {spawned}/{len(objects)} ({spawned*100//len(objects)}%), {rate:.0f} Actor/秒")

        short_id = obj.get("mesh_data_short_id")
        mesh_data_name = obj.get("mesh_data", "")
        asset_name = obj.get("mesh_asset_name")
        sm, match_mode = find_mesh_in_cache(mesh_data_name, mesh_cache, normalized_cache, short_id, asset_name, hash_cache, prefix_cache)
        if not sm:
            failed += 1
            failed_names.append(obj.get("name", "?"))
            if CONFIG["verbose"]:
                log(f"找不到网格: {obj.get('name')} | asset={asset_name} | short_id={short_id}", "warning")
            continue
        if CONFIG["verbose"] and match_mode and match_mode not in {"short_id", "asset_name_exact"}:
            log(f"资产回退命中: {obj.get('name')} -> {asset_name} ({match_mode})", "warning")

        rel = obj.get("reconstruct_relative_ue5", {})
        rel_tf = {
            "location": rel.get("location", [0.0, 0.0, 0.0]),
            "rotation": rel.get("rotation_quaternion", [1.0, 0.0, 0.0, 0.0]),
            "scale": rel.get("scale", [1.0, 1.0, 1.0]),
        }

        # 应用 local rotation 补偿（方案B）
        if q_comp:
            rel_tf["rotation"] = quat_multiply(rel_tf["rotation"], q_comp)

        world_tf = combine_transform(anchor_world, rel_tf)

        actor_label = obj.get("name", asset_name or mesh_data_name)
        try:
            actor = spawn_static_mesh_actor(sm, world_tf, actor_label)
            if not actor:
                failed += 1
                failed_names.append(actor_label)
                continue

            try:
                actor.attach_to_actor(
                    anchor_actor,
                    socket_name="",
                    location_rule=unreal.AttachmentRule.KEEP_WORLD,
                    rotation_rule=unreal.AttachmentRule.KEEP_WORLD,
                    scale_rule=unreal.AttachmentRule.KEEP_WORLD,
                    weld_simulated_bodies=True,
                )
            except Exception as e_attach:
                if CONFIG["verbose"]:
                    log(f"附加到 Anchor 失败（保留世界姿态）: {actor_label}: {e_attach}", "warning")

            if editor_actor_subsys:
                try:
                    editor_actor_subsys.set_actor_folder(actor, scene_name)
                except Exception:
                    pass

            spawned += 1
        except Exception as e:
            failed += 1
            failed_names.append(actor_label)
            if CONFIG["verbose"]:
                log(f"spawn 失败: {actor_label}: {e}", "warning")

    elapsed = time.time() - start_time
    log("=" * 60, "warning")
    log("  场景重建完成", "warning")
    log("=" * 60, "warning")
    log(f"  场景名:    {scene_name}")
    log(f"  Anchor:    {anchor_label}")
    log(f"  总对象数:  {len(objects)}")
    log(f"  成功生成:  {spawned}")
    log(f"  失败:      {failed}")
    log(f"  耗时:      {elapsed:.1f} 秒")
    if elapsed > 0:
        log(f"  速率:      {spawned/elapsed:.0f} Actor/秒")

    if failed > 0:
        try:
            fail_path = os.path.join(unreal.Paths.project_content_dir(), "failed_actors_v4.txt")
            with open(fail_path, 'w', encoding='utf-8') as f:
                for name in failed_names:
                    f.write(name + "\n")
            log(f"失败列表已写入: {fail_path}", "warning")
        except Exception:
            pass

    log("保存当前关卡...")
    try:
        unreal.EditorLevelLibrary.save_current_level()
        log("  ✓ 关卡已保存")
    except Exception as e:
        log(f"  ⚠ 保存失败: {e}", "warning")


if __name__ == "__main__":
    reconstruct_level()
