# Mesh Toolkit v1.0 — 全流程使用说明

---

## 目录

1. [简介](#1-简介)
2. [安装](#2-安装)
3. [界面概览](#3-界面概览)
4. [偏好设置](#4-偏好设置)
5. [功能详解](#5-功能详解)
   - [5.1 共享网格数据](#51-共享网格数据)
   - [5.2 清理孤立数据](#52-清理孤立数据)
   - [5.3 规范化命名](#53-规范化命名)
   - [5.4 创建锚点](#54-创建锚点)
   - [5.5 导出 GLB + Manifest](#55-导出-glb--manifest)
6. [完整工作流：Blender → UE5](#6-完整工作流blender--ue5)
7. [引擎坐标转换参考](#7-引擎坐标转换参考)
8. [故障排除](#8-故障排除)

---

## 1. 简介

Mesh Toolkit 是一个 Blender 4.0+ 插件，面向 3D 场景制作者和技术美术，提供两大核心能力：

- **网格管理**：拓扑一致的网格对象一键共享 mesh data，通过 Kabsch 算法自动补偿枢轴差异，减少文件体积与内存占用。
- **导出管线**：全场景扫描 → 按 mesh data 去重 → 导出 GLB + JSON Manifest，支持 UE5 / Unity / Godot 多引擎坐标转换。

配套的 UE5 脚本（`docs/ue5_reconstruct_simple.py`、`docs/ue5_export_actors.py`）可读取 Manifest 自动化重建场景并闭环验证。

### 文件清单

```
SimpleBleModlePlugin/
├── blender_manifest.toml       # Blender 扩展清单 (4.2+)
├── __init__.py                 # 插件入口 + 偏好设置
├── config.py                   # 全局常量与预设
├── logger.py                   # 双通道日志
├── naming.py                   # 资产命名策略
├── coordinate.py               # 坐标转换引擎
├── mesh_core.py                # Kabsch 合并 + 孤立清理
├── export_core.py              # 场景扫描 + GLB 导出 + Manifest
├── ui.py                       # UI 面板与操作符
├── docs/
│   ├── system_design.md        # 架构设计文档
│   ├── class-diagram.mermaid   # 类图
│   ├── sequence-diagram.mermaid # 时序图
│   ├── ue5_reconstruct_simple.py # UE5 场景重建脚本
│   └── ue5_export_actors.py    # UE5 闭环验证导出脚本
├── tests/                      # 单元测试
└── TEST_GUIDE.md               # 测试指南
```

---

## 2. 安装

### 方式一：Blender Extensions 安装（推荐）

1. 启动 Blender 4.0+
2. `编辑 → 偏好设置 → 扩展`（Blender 4.2+ 为 `Extensions` 标签）
3. 点击右上角下拉箭头 → `从磁盘安装`
4. 选择 `mesh_toolkit.zip`
5. 在扩展列表中启用 **Mesh Toolkit**

### 方式二：手动复制

将 `SimpleBleModlePlugin/` 目录下所有 `.py` 文件和 `blender_manifest.toml` 复制到：

```
%APPDATA%/Blender Foundation/Blender/<版本号>/scripts/addons/mesh_toolkit/
```

然后在 `编辑 → 偏好设置 → 插件` 中搜索 "Mesh Toolkit" 并启用。

### 验证安装

启用后，在 3D 视图右侧边栏（按 `N` 键）出现 **Mesh Toolkit** 标签页即表示安装成功。

---

## 3. 界面概览

插件面板位于 3D 视图右侧 `N 面板 → Mesh Toolkit`，包含三个子面板：

```
┌─────────────────────────────────────┐
│  ▼ 网格管理                         │
│  ┌───────────────────────────────┐  │
│  │  共享网格数据                  │  │
│  │  [    共享网格数据    ]        │  │
│  │  ▢ 强制补偿                    │  │
│  │  位置阈值  ▬▬▬▬○▬▬▬▬         │  │
│  │  旋转阈值  ▬▬▬▬○▬▬▬▬         │  │
│  ├───────────────────────────────┤  │
│  │  实用工具                      │  │
│  │  [    清理孤立数据    ]        │  │
│  │  匹配正则  [__[0-9].*$    ]   │  │
│  │  [    规范化命名      ]        │  │
│  └───────────────────────────────┘  │
│                                     │
│  ▼ 导出管线                         │
│  ┌───────────────────────────────┐  │
│  │  导出设置                      │  │
│  │  目标引擎   [UE5 ▼]           │  │
│  │  锚点名称   [UE_Anchor    ]   │  │
│  │  [    创建锚点      ]          │  │
│  │  导出目录   [//Exports/   ]   │  │
│  │  命名模式   [Hash+名称 ▼]     │  │
│  │  压缩精度   [无损 ▼]          │  │
│  │  ▢ glTF Y-Up                  │  │
│  │  ▢ 包含隐藏对象                │  │
│  ├───────────────────────────────┤  │
│  │  [  导出 GLB + Manifest  ]    │  │
│  └───────────────────────────────┘  │
│                                     │
│  ▼ 日志                             │
│  ┌───────────────────────────────┐  │
│  │  [日志条目...]                 │  │
│  │  [    清空日志      ]          │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

---

## 4. 偏好设置

`编辑 → 偏好设置 → 插件 → Mesh Toolkit` 可配置以下全局参数：

| 分类 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| 合并阈值 | 位置补偿阈值 | `0.001` m | 超过此位移差触发枢轴补偿 |
| | 旋转补偿阈值 | `0.015` rad | 超过此角度差触发枢轴补偿 |
| | 强制补偿 | 关闭 | 忽略阈值，强制对所有匹配对象补偿 |
| 导出设置 | 目标引擎 | `UE5` | UE5 / Unity / Godot |
| | 导出目录 | 空 | 留空则使用场景文件旁的 `Exports/` |
| | 锚点对象名称 | `UE_Anchor` | 场景统一参考锚点名 |
| | glTF Y-Up | 开启 | 导出时启用 Y-Up 坐标转换 |
| | 包含隐藏对象 | 关闭 | 是否导出隐藏的 Mesh |
| 资产命名 | 资产命名模式 | `Hash+名称` | 原始名称 / 纯 Hash / Hash+名称 |
| | 精度模式 | `无损` | 无损 / 超高 / 高 / 平衡 / 激进 |
| | 资产名最大长度 | `80` | 超出将智能截断 |
| 规范化正则 | `规范化正则` | `__[0-9].*$` | 用于规范化命名的正则表达式 |

---

## 5. 功能详解

### 5.1 共享网格数据

**用途**：将多个拓扑一致的 Mesh 对象的 mesh data 统一为活动对象的数据块，通过 Kabsch 算法自动补偿因共享网格体导致的枢轴差异。

**操作步骤**：

1. 在场景中选中多个 Mesh 对象
2. **确保活动对象**（最后选中的亮色对象）是希望作为共享源的网格体
3. 点击 `共享网格数据` 按钮

**行为说明**：

| 场景 | 行为 |
|------|------|
| 选中 < 2 个对象 | 按钮置灰，不可点击 |
| 顶点数不匹配 | 跳过该对象，在日志中记录 |
| 顶点数匹配 | 共享 mesh data，Kabsch 补偿枢轴差异 |
| 强制补偿 + >45°差异 | 弹出确认对话框，确认后强制合并 |

**预期结果**：
- 日志面板显示合并统计：重分配数、旋转/位移补偿数、跳过数
- 孤立 mesh data 自动清理

---

### 5.2 清理孤立数据

**用途**：删除场景中未被任何对象引用的 mesh data 块（`users == 0`）。

**操作步骤**：点击 `清理孤立数据` 按钮。

**预期结果**：日志显示 "已清理 N 个孤立 mesh data 块"。

---

### 5.3 规范化命名

**用途**：按正则表达式批量去除 mesh data 名称中的匹配部分。

**操作步骤**：

1. 在 `匹配正则` 输入框中填写正则表达式（默认 `__[0-9].*$` 匹配 `__001`、`__002` 等后缀）
2. 点击 `规范化命名` 按钮

**正则示例**：

| 正则表达式 | 效果 |
|-----------|------|
| `__[0-9].*$`（默认） | 去除 `__001`、`__999` 等 `__数字` 后缀 |
| `\.[0-9]{3}$` | 去除 `.001` 等三位数字后缀 |
| `_LOD[0-9]$` | 去除 `_LOD0`、`_LOD1` 等 LOD 后缀 |

**预期结果**：日志显示 "已规范化 N 个 mesh data 名称"。

---

### 5.4 创建锚点

**用途**：在世界原点创建与当前配置的锚点名称对应的纯轴空对象，作为导出的空间基准。

**操作步骤**：

1. 在导出设置中确认 `锚点名称`
2. 点击 `创建锚点` 按钮

**行为**：
- 若不存在同名对象：在 `(0, 0, 0)` 创建纯轴空对象
- 若已存在：直接选中该对象
- 日志面板提示操作结果

---

### 5.5 导出 GLB + Manifest

**用途**：全场景扫描 → 按 mesh data 去重 → 导出 GLB 文件 + JSON 元数据清单。

**操作步骤**：

1. 配置导出参数（引擎、锚点、导出目录、命名模式、精度）
2. 点击 `导出 GLB + Manifest` 按钮

**输出文件**：

| 文件 | 说明 |
|------|------|
| `<场景名>_meshes_anchor.glb` | 去重后的网格资产（每个唯一 mesh data 一份），旋转/缩放基准已 bake 进顶点 |
| `<场景名>_manifest_v30.json` | 场景元数据：锚点信息、实例变换、包围盒、统计摘要 |

**Manifest JSON 结构**：

```json
{
  "version": "3.0",
  "scene_name": "jidianGuanNew",
  "target_engine": "UE5",
  "pipeline_mode": "anchor_plus_mesh_basis_compensation",
  "coordinate_system": {
    "blender": { "up_axis": "Z", "handedness": "right", "unit": "m" },
    "ue5":     { "up_axis": "Z", "handedness": "left",  "unit": "cm" },
    "conversion": { "position": "Bl_X→UE5_Y*100, ..." }
  },
  "scene_anchor": { "name": "UE_Anchor", "blender_world": {...}, "target_world": {...} },
  "mesh_assets": [{ "mesh_asset_name": "SM_M0f800721_Cube", ... }],
  "objects":      [{ "reconstruct_relative_target": {...}, "mesh_asset_name": "..." }],
  "statistics":   { "total_objects": 6, "unique_mesh_data_blocks": 5 }
}
```

**精度模式**：

| 模式 | Draco | 说明 |
|------|-------|------|
| 无损 | 关闭 | 保留完整顶点精度 |
| 超高 | Level 1 | 几乎无损 |
| 高 | Level 4 | 高质量 |
| 平衡 | Level 6 | 推荐日常使用 |
| 激进 | Level 10 | 最小文件体积 |

**命名模式**：

| 模式 | 示例 | 说明 |
|------|------|------|
| 原始名称 | `SM_Cube` | mesh data 名经合规化后直接使用 |
| 纯 Hash | `SM_jidianGuanNew_M0f80072` | 场景名 + MD5 短 ID |
| Hash+名称 | `SM_M0f800721_Cube` | MD5 短 ID 前置 + 智能截断名称 |

---

## 6. 完整工作流：Blender → UE5

以下为从 Blender 场景到 UE5 重建的端到端流程：

### 阶段一：Blender 准备

1. 打开 `.blend` 场景文件
2. 在 N 面板 → Mesh Toolkit → 导出管线中点击 `创建锚点`
3. （可选）使用共享网格数据功能合并重复网格体
4. （可选）使用规范化命名整理 mesh data 名称

### 阶段二：导出

1. 配置参数：
   - 目标引擎：`UE5`
   - 锚点名称：`UE_Anchor`
   - 命名模式：`Hash+名称`
   - 精度模式：`平衡`
2. 点击 `导出 GLB + Manifest`
3. 确认 `Exports/` 目录中生成 `.glb` 和 `.json` 文件

### 阶段三：UE5 导入资产

1. 在 UE5 中导入 `Exports/<场景名>_meshes_anchor.glb`
2. 确保 StaticMesh 资产的命名与 Manifest 中的 `mesh_asset_name` 一致
3. 资产应放置于统一的内容目录下

### 阶段四：UE5 重建场景

1. 将 `Exports/<场景名>_manifest_v30.json` 放到脚本可读取的位置
2. 在 UE5 Python 控制台中配置并运行 `docs/ue5_reconstruct_simple.py`：
   ```python
   CONFIG = {
       "manifest_path": "F:/Library/BlenderWork/Exports/jidianGuanNew_manifest_v30.json",
       "mesh_asset_base_path": "/Game/Meshes/",
       "anchor_actor_label": "UE_Anchor",
       "location_tolerance": 0.01,
       "rotation_tolerance": 0.001,
   }
   ```
3. 脚本自动创建 Anchor Actor 并批量生成 StaticMeshActor

### 阶段五：闭环验证

1. 在 UE5 中运行 `docs/ue5_export_actors.py` 导出当前关卡中 Actor 的实际变换
2. 对比 Manifest 中的期望值与导出结果，验证重建精度

```
Blender 场景
    │
    ├─ 1. 网格管理 (合并/清理/规范化)
    │
    ▼
  [导出 GLB + Manifest]  ← Mesh Toolkit
    │
    ├─ .glb ──→ UE5 StaticMesh 资产导入
    │
    ├─ .json ─→ ue5_reconstruct_simple.py 重建场景
    │
    ▼
  ue5_export_actors.py 闭环验证
```

---

## 7. 引擎坐标转换参考

插件导出时按目标引擎执行坐标转换，Manifest 中记录了完整的转换公式。

### Blender 原生坐标系

- 上轴：`Z`
- 手性：右手系
- 单位：米
- 轴向：X=右, Y=前, Z=上

### UE5

| 属性 | 值 |
|------|-----|
| 上轴 | Z |
| 手性 | 左手系 |
| 单位 | 厘米 |
| 位置转换 | `UE5_X=Bl_Y×100, UE5_Y=Bl_X×100, UE5_Z=Bl_Z×100` |
| 四元数转换 | `(w, x, y, z) → (w, y, x, z)` |
| 缩放转换 | `(sx, sy, sz) → (sy, sx, sz)` |

### Unity

| 属性 | 值 |
|------|-----|
| 上轴 | Y |
| 手性 | 左手系 |
| 单位 | 米 |
| 位置转换 | `(-Bl_X, Bl_Z, -Bl_Y)` |
| 四元数转换 | `(w, x, y, z) → (w, x, -z, y)` |
| 缩放转换 | `(sx, sy, sz) → (sx, sz, sy)` |

### Godot

| 属性 | 值 |
|------|-----|
| 上轴 | Y |
| 手性 | 右手系 |
| 单位 | 米 |
| 位置转换 | `(Bl_X, Bl_Z, Bl_Y)` |
| 四元数转换 | `(w, x, y, z) → (w, x, z, y)` |
| 缩放转换 | `(sx, sy, sz) → (sx, sz, sy)` |

---

## 8. 故障排除

| 问题 | 可能原因 | 解决方法 |
|------|---------|---------|
| 插件不显示 | 安装方式错误 | 使用 ZIP 安装整个插件包，不能单独安装 `__init__.py` |
| 面板空白/按钮不显示 | 图标名称错误 | 确认 `blender_manifest.toml` 含 `license` 字段；检查 Blender 系统控制台错误信息 |
| 共享网格数据无效果 | 对象拓扑不一致 | 检查日志中的跳过原因；顶点数不同时无法合并 |
| 导出无反应 | 场景无 Mesh 对象 | 确认场景至少包含一个可见 Mesh |
| GLB 文件过大 | 精度模式过高 | 降低精度模式（平衡/激进）并启用 Draco 压缩 |
| UE5 重建后位置偏移 | 锚点未匹配 | 确认场景有与配置名称一致的 Anchor 空对象；UE5 侧脚本配置正确的 Anchor 名称 |
| 命名正则不生效 | 正则语法错误 | 在外部工具（如 regex101.com）中验证正则表达式 |

### 查看详细日志

所有操作均输出到两个通道：
- **日志面板**：N 面板底部，支持滚动和清空
- **系统控制台**：`窗口 → 切换系统控制台`（Windows）或终端（macOS/Linux）
