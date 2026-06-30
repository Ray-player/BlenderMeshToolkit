---
name: blender-scene-analysis
description: Analyze a Blender scene to generate mesh-sharing grouping JSON files. Outputs shareable groups (consistent topology) and anomaly groups (singletons or vertex mismatches). Trigger when the user asks to analyze scene objects for mesh sharing, generate grouping JSON from Blender objects, or find which objects can share mesh data.
agent_created: true
---

# Blender Scene Analysis — Mesh Sharing Group Generator

## Purpose

Analyze all MESH objects in the current Blender scene, group them by naming prefix,
validate vertex-count consistency within each group, and output two JSON files:

1. **`scene_share_groups.json`** — groups ready for batch mesh sharing (≥2 members, all same vertex count)
2. **`scene_share_anomalies.json`** — singletons and vertex-mismatch groups that need manual review

These JSON files are consumed by the Mesh Toolkit plugin's "按 JSON 数据共享网格" feature.

## When to Use

- Before running batch mesh sharing to understand the scene's grouping landscape
- When the user asks "哪些对象可以共享网格数据" or "分析场景中的重复网格"
- As a preparatory step before using the `MESHTOOLKIT_OT_JsonShareMesh` operator

## Bundled Script

Use `scripts/analyze_scene.py` (in this skill's directory). Load the script content via the Read tool, then execute it in Blender through MCP `execute_blender_code`.

### Usage

```
1. Read scripts/analyze_scene.py
2. Pass the content to mcp__blender__execute_blender_code
```

The script automatically derives the export directory from the current `.blend` file location — no paths need configuration.

### Output

| File | Path | Content |
|------|------|---------|
| Shareable groups | `Exports/scene_share_groups.json` | Groups with ≥2 members, all vertex-identical |
| Anomalies | `Exports/scene_share_anomalies.json` | Singletons + vertex-mismatch groups |

### JSON Schema Reference

See `references/json_formats.md` for full schema documentation of both output files.
