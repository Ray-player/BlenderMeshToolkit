"""
analyze_scene.py — Blender 场景网格共享分析脚本

用途：
    扫描当前 Blender 场景中所有 MESH 对象，按命名前缀自动分组，
    根据顶点数一致性生成两组 JSON 文件：
    1. scene_share_groups.json — 可直接共享网格的组（≥2 成员, 顶点数一致）
    2. scene_share_anomalies.json — 异常组（单例 或 顶点数不一致）

用法：
    在 Blender Python 控制台或通过 MCP execute_blender_code 执行此脚本。

输出：
    {BLEND_DIR}/Exports/scene_share_groups.json
    {BLEND_DIR}/Exports/scene_share_anomalies.json
"""

import bpy
import json
import os
import re
from collections import defaultdict


# ── 配置 ──
BLEND_FILEPATH = bpy.data.filepath
BLEND_DIR = os.path.dirname(BLEND_FILEPATH) or os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BLEND_DIR, "Exports")
GROUPS_FILE = "scene_share_groups.json"
ANOMALIES_FILE = "scene_share_anomalies.json"


# ── 辅助函数 ──

def extract_prefix(obj_name: str) -> str:
    """从 Blender 对象名提取命名前缀。"""
    # 策略1: __ 分隔符 → 取 __ 之前的部分
    if '__' in obj_name:
        return obj_name.split('__')[0]
    # 策略2: Blender 自动命名 .001, .002 → 去掉数字后缀
    if '.' in obj_name and re.match(r'^.+\\.\\d{3}$', obj_name):
        return obj_name.rsplit('.', 1)[0]
    # 策略3: 末尾数字后缀
    match = re.match(r'^(.+?)(_[0-9]+)?$', obj_name)
    if match:
        return match.group(1)
    return obj_name


def group_objects():
    """按命名前缀分组所有 MESH 对象。返回 {prefix: [{name, verts, mesh_name}, ...]}。"""
    groups = defaultdict(list)
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        prefix = extract_prefix(obj.name)
        groups[prefix].append({
            'name': obj.name,
            'verts': len(obj.data.vertices),
            'mesh_name': obj.data.name,
        })
    return groups


# ── JSON 生成 ──

def build_shareable_json(groups: dict) -> dict:
    """
    构建可共享组的 JSON。
    条件：组内 ≥ 2 个成员 且 所有成员顶点数一致。
    每组取第一个成员作为 source。
    """
    json_groups = []
    for prefix in sorted(groups.keys()):
        members = groups[prefix]
        if len(members) < 2:
            continue
        verts_list = [m['verts'] for m in members]
        if len(set(verts_list)) != 1:
            continue
        source = members[0]['name']
        member_names = [m['name'] for m in members[1:]]
        json_groups.append({"source": source, "members": member_names})

    json_groups.sort(key=lambda g: -len(g['members']))

    return {
        "version": "1.0",
        "description": "自动生成的共享网格分组 — 顶点数一致的组可用于批量合并",
        "statistics": {
            "total_groups": len(json_groups),
            "total_objects": sum(len(g['members']) + 1 for g in json_groups),
        },
        "groups": json_groups,
    }


def build_anomalies_json(groups: dict) -> dict:
    """
    构建异常组 JSON。
    包含：单例（只有 1 个成员）、顶点数不一致的组。
    """
    anomaly_groups = []
    total_objects = 0

    for prefix in sorted(groups.keys()):
        members = groups[prefix]
        verts_list = [m['verts'] for m in members]
        unique_verts = sorted(set(verts_list))

        if len(members) == 1:
            m = members[0]
            anomaly_groups.append({
                "prefix": prefix,
                "reason": "singleton",
                "member_count": 1,
                "vert_counts": [m['verts']],
                "members": [{"name": m['name'], "verts": m['verts']}],
            })
            total_objects += 1
        elif len(unique_verts) > 1:
            anomaly_groups.append({
                "prefix": prefix,
                "reason": "vertex_mismatch",
                "member_count": len(members),
                "unique_vert_counts": unique_verts,
                "members": [{"name": m['name'], "verts": m['verts']} for m in members],
            })
            total_objects += len(members)

    anomaly_groups.sort(key=lambda g: -g['member_count'])

    singleton_count = sum(1 for g in anomaly_groups if g['reason'] == 'singleton')
    mismatch_count = sum(1 for g in anomaly_groups if g['reason'] == 'vertex_mismatch')

    return {
        "version": "1.0",
        "description": "共享网格异常组清单 — 单例或顶点数不一致的对象",
        "statistics": {
            "total_anomaly_objects": total_objects,
            "singleton_groups": singleton_count,
            "vertex_mismatch_groups": mismatch_count,
            "anomaly_groups_total": len(anomaly_groups),
        },
        "groups": anomaly_groups,
    }


# ── 主流程 ──

def main():
    os.makedirs(EXPORT_DIR, exist_ok=True)

    print("=== 场景网格共享分析 ===\n")
    groups = group_objects()

    total_objects = sum(len(v) for v in groups.values())
    print(f"MESH 对象总数: {total_objects}")
    print(f"唯一命名前缀: {len(groups)}")

    # 可共享组
    shareable = build_shareable_json(groups)
    shareable_path = os.path.join(EXPORT_DIR, GROUPS_FILE)
    with open(shareable_path, 'w', encoding='utf-8') as f:
        json.dump(shareable, f, ensure_ascii=False, indent=2)
    shareable_size = os.path.getsize(shareable_path) / 1024

    shareable_groups = shareable['statistics']['total_groups']
    shareable_objects = shareable['statistics']['total_objects']
    print(f"可共享组: {shareable_groups} 组 ({shareable_objects} 对象)")
    print(f"  → {shareable_path} ({shareable_size:.0f} KB)")

    # 异常组
    anomalies = build_anomalies_json(groups)
    anomalies_path = os.path.join(EXPORT_DIR, ANOMALIES_FILE)
    with open(anomalies_path, 'w', encoding='utf-8') as f:
        json.dump(anomalies, f, ensure_ascii=False, indent=2)
    anomalies_size = os.path.getsize(anomalies_path) / 1024

    a_stats = anomalies['statistics']
    print(f"\n异常组: {a_stats['anomaly_groups_total']} 组 ({a_stats['total_anomaly_objects']} 对象)")
    print(f"  单例: {a_stats['singleton_groups']} 组")
    print(f"  顶点数不一致: {a_stats['vertex_mismatch_groups']} 组")
    print(f"  → {anomalies_path} ({anomalies_size:.0f} KB)")

    # Top 5 最大组
    print(f"\n=== Top 5 可共享组 ===")
    for i, g in enumerate(shareable['groups'][:5]):
        prefix = g['source'].split('__')[0] if '__' in g['source'] else g['source']
        prefix = (prefix[:45] + '...') if len(prefix) > 48 else prefix
        print(f"  {i+1}. [{prefix}] {len(g['members'])+1} 成员")

    # 顶点数不一致 Top 5
    mismatches = [g for g in anomalies['groups'] if g['reason'] == 'vertex_mismatch']
    if mismatches:
        print(f"\n=== Top 5 顶点数不一致组 ===")
        for i, g in enumerate(mismatches[:5]):
            prefix = (g['prefix'][:45] + '...') if len(g['prefix']) > 48 else g['prefix']
            print(f"  {i+1}. [{prefix}] {g['member_count']} 成员, "
                  f"{len(g['unique_vert_counts'])} 种顶点数")

    print("\n分析完成。")


if __name__ == "__main__":
    main()
