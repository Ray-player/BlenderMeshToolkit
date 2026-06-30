# JSON 输出格式说明

## scene_share_groups.json — 可共享组

### 完整示例

```json
{
  "version": "1.0",
  "description": "自动生成的共享网格分组",
  "statistics": {
    "total_groups": 320,
    "total_objects": 4872
  },
  "groups": [
    {
      "source": "控制点_FDCIO221C-CN__3495546_",
      "members": [
        "控制点_FDCIO221C-CN__3495547_",
        "控制点_FDCIO221C-CN__3495548_"
      ]
    }
  ]
}
```

### 字段说明

| 路径 | 类型 | 说明 |
|------|------|------|
| `groups[]` | array | 可立即用于 `MESHTOOLKIT_OT_JsonShareMesh` 的分组列表 |
| `groups[].source` | string | 共享源对象名（组内第一个成员），必须是 MESH 类型 |
| `groups[].members` | string[] | 需共享 source 网格数据的其余对象名 |

### 筛选规则

- 组内成员数 ≥ 2
- 所有成员**顶点数完全相同**
- source 始终是组内按字母序排列的第一个对象

---

## scene_share_anomalies.json — 异常组

### 完整示例

```json
{
  "version": "1.0",
  "description": "共享网格异常组清单",
  "statistics": {
    "total_anomaly_objects": 5331,
    "singleton_groups": 1101,
    "vertex_mismatch_groups": 98,
    "anomaly_groups_total": 1199
  },
  "groups": [
    {
      "prefix": "纤维玻璃",
      "reason": "vertex_mismatch",
      "member_count": 676,
      "unique_vert_counts": [24, 26, 28, 30, 32, 34, 36, 38],
      "members": [
        {"name": "纤维玻璃__001", "verts": 24},
        {"name": "纤维玻璃__002", "verts": 26}
      ]
    },
    {
      "prefix": "某个唯一对象",
      "reason": "singleton",
      "member_count": 1,
      "vert_counts": [100],
      "members": [
        {"name": "某个唯一对象__001", "verts": 100}
      ]
    }
  ]
}
```

### 字段说明

| 路径 | 类型 | 说明 |
|------|------|------|
| `groups[].prefix` | string | 对象命名前缀 |
| `groups[].reason` | string | 异常原因: `"singleton"` 或 `"vertex_mismatch"` |
| `groups[].member_count` | int | 该前缀下的对象总数 |
| `groups[].unique_vert_counts` | int[] | (仅 vertex_mismatch) 组内出现的所有独特顶点数 |
| `groups[].members[]` | object | 每个成员的详细信息 |
| `members[].name` | string | Blender 对象全名 |
| `members[].verts` | int | 该对象的顶点数 |

### 处理建议

| 异常类型 | 建议处理方式 |
|----------|------------|
| `singleton` | 无需共享，直接保留 |
| `vertex_mismatch` | 按 `verts` 值二次分组，同一顶点数的子集可手动追加到 `scene_share_groups.json` |
