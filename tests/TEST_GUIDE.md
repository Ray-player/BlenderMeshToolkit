# Blender Mesh Toolkit — 测试指南

## 0. 单元测试（纯 Python，无需 Blender）

```bash
cd F:/Library/BlenderWork/SimpleBleModlePlugin
python tests/test_runner.py
```

预期：104 tests, 104 pass, 0 fail

---

## 1. 安装插件

1. 打开 Blender 4.0+
2. `Edit → Preferences → Add-ons`
3. 点击 `Install...`，选择 `F:/Library/BlenderWork/SimpleBleModlePlugin/__init__.py`
4. 勾选启用 **Mesh Toolkit**
5. 在 3D Viewport 侧边栏（N 键）出现 `Mesh Toolkit` 标签

---

## 2. 测试：网格管理面板

### 2.1 Share Mesh Data（基础）

**准备**：
1. 创建两个立方体（默认已共享 mesh data）：`Add → Mesh → Cube` × 2
2. 选中 Cube.001，按 `Tab` 进入编辑模式，移动顶点使其拓扑一致但形状略不同
3. `Object → Apply → Make Single User → Object & Data`（断开共享）
4. 移动 Cube.001 的位置和旋转

**验证**：
1. 选中 Cube.001，再加选 Cube（`Shift+Click`，Cube 是活动对象）
2. Mesh Toolkit 面板 → `Share Mesh Data`
3. **预期**：
   - Cube.001 的 `data` 变为 Cube 的 mesh data
   - Cube.001 位置/旋转自动补偿（Kabsch），物体保持原位
   - 日志输出补偿量和统计摘要

### 2.2 Share Mesh Data（强制补偿）

**准备**：
1. 创建两个 Cube，断开共享
2. 旋转其中一个 >45°
3. 选中两个 Cube

**验证**：
1. 勾选 `Force Compensation` 
2. 点击 `Share Mesh Data`
3. **预期**：弹出确认对话框（角度 >45° 警告），确认后合并成功

### 2.3 Clean Orphan Data

**准备**：
1. 创建三个 Cube，两个共享 mesh data，一个独立
2. 独立那个运行 Share Mesh Data 合并到共享组

**验证**：
1. 点击 `Clean Orphan Data`
2. **预期**：旧 mesh data block 被删除，日志显示清理数量

### 2.4 Normalize Mesh Names

**准备**：
1. 导入或创建带有 `__001`、`__002` 等后缀的 mesh data 名称的对象

**验证**：
1. 点击 `Normalize Mesh Names`
2. **预期**：mesh data 名称去掉 `__数字` 后缀

---

## 3. 测试：导出管线面板

### 3.1 基本导出

**准备**：
1. 打开 `F:/Library/BlenderWork/jidianGuanNew.blend`（或任何含多个 Mesh 的场景）
2. 确保场景有 `UE_Anchor` 空对象（没有则自动使用虚拟根）

**验证**：
1. 配置面板参数：
   - Target Engine: `UE5`
   - Draco: `BALANCED`
   - Naming: `ORIGINAL`
   - Export Dir: 留空（默认 `//Exports/`）
2. 点击 `Export GLB + Manifest`
3. **预期**：
   - 在 Exports/ 目录生成：
     - `<场景名>_meshes_anchor.glb`
     - `<场景名>_manifest_v30.json`
   - 日志输出导出统计（对象数、唯一网格数、文件大小）

### 3.2 不同压缩级别

**验证**：
1. 分别测试 `LOSSLESS` / `HIGH` / `AGGRESSIVE` 三个级别
2. **预期**：文件大小有明显差异，压缩级别越高越小

### 3.3 不同命名模式

**验证**：
1. 分别测试 `ORIGINAL` / `SHORTID_PREFIX` 两种模式
2. **预期**：Manifest JSON 中 `mesh_asset_name` 格式符合各自模式规范

### 3.4 Manifest JSON 验证

1. 打开生成的 `.json` 文件
2. 检查字段完整性：
   - `scene_anchor`：锚点对象名和变换
   - `mesh_assets`：唯一网格资产列表
   - `objects`：所有实例条目（含 UE5 变换）
   - `statistics`：统计摘要
   - `coordinate_system`：坐标系转换公式
3. **预期**：所有字段非空，坐标值精度一致

---

## 4. 日志面板验证

所有操作后检查：
1. 日志面板显示最近操作的时间和统计
2. Blender `Window → Toggle System Console` 中同步显示日志

---

## 5. 边界测试

| 场景 | 预期 |
|------|------|
| 无选中对象点击 Share Mesh | 按钮置灰（poll 返回 False） |
| 选中1个对象点击 Share Mesh | 按钮置灰 |
| 选中不同拓扑对象（Cube + Sphere） | 跳过不匹配的，仅合并匹配的 |
| 无 UE_Anchor 导出 | 使用虚拟根（Identity），正常导出 |
| 目录不存在导出 | 自动创建 Exports/ 目录 |
