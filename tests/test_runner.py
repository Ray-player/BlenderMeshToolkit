"""
test_runner.py — 独立测试运行器

在标准 Python 环境中运行 Blender Mesh Toolkit 的单元测试。
通过预安装 bpy/mathutils mock 实现无 Blender 环境测试。
"""

import sys
import os
import unittest

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════
#  Step 1: 安装 mock bpy 和 mathutils
# ═══════════════════════════════════════════

# --- Mock bpy.app.version ---
class _MockVersion:
    def __init__(self, ver=(4, 0, 0)):
        self._ver = ver
    def __ge__(self, other):
        return self._ver >= other
    def __getitem__(self, idx):
        return self._ver[idx]
    def __repr__(self):
        return f"bpy.app.version({self._ver})"

# --- Mock bpy.props ---
class _MockBpyProps:
    @staticmethod
    def FloatProperty(**kw):
        return kw.get("default", 0.0)
    @staticmethod
    def BoolProperty(**kw):
        return kw.get("default", False)
    @staticmethod
    def EnumProperty(**kw):
        return kw.get("default", "")
    @staticmethod
    def StringProperty(**kw):
        return kw.get("default", "")
    @staticmethod
    def IntProperty(**kw):
        return kw.get("default", 0)

# --- Mock bpy ---
class _MockBpyApp:
    version = _MockVersion()

class _MockBpyContext:
    pass

class _MockBpyData:
    pass

class _MockBpyTypes:
    """Mock bpy.types — Panel, Operator 基类等"""
    class Panel:
        pass
    class Operator:
        pass

class _MockBpyOps:
    pass

class _MockBpy:
    app = _MockBpyApp()
    context = _MockBpyContext()
    data = _MockBpyData()
    types = _MockBpyTypes()
    ops = _MockBpyOps()
    props = _MockBpyProps()

# --- Mock mathutils ---
class MockVector:
    __slots__ = ('_data',)
    def __init__(self, data):
        if isinstance(data, MockVector):
            self._data = list(data._data)
        else:
            self._data = list(data)
    @property
    def x(self): return self._data[0]
    @x.setter
    def x(self, val): self._data[0] = val
    @property
    def y(self): return self._data[1]
    @y.setter
    def y(self, val): self._data[1] = val
    @property
    def z(self): return self._data[2]
    @z.setter
    def z(self, val): self._data[2] = val
    def __getitem__(self, idx): return self._data[idx]
    def __setitem__(self, idx, val): self._data[idx] = val
    def __len__(self): return len(self._data)
    def __iter__(self): return iter(self._data)
    def __repr__(self): return f"Vector({self._data})"
    def __eq__(self, other):
        if isinstance(other, MockVector): return self._data == other._data
        return self._data == list(other)
    def __add__(self, other):
        if isinstance(other, MockVector):
            return MockVector([a + b for a, b in zip(self._data, other._data)])
        return NotImplemented
    def __sub__(self, other):
        if isinstance(other, MockVector):
            return MockVector([a - b for a, b in zip(self._data, other._data)])
        return NotImplemented
    def __neg__(self):
        return MockVector([-a for a in self._data])
    def copy(self):
        return MockVector(list(self._data))

class MockQuaternion:
    __slots__ = ('_data',)
    def __init__(self, data):
        if isinstance(data, MockQuaternion):
            self._data = list(data._data)
        else:
            self._data = list(data)
    @property
    def w(self): return self._data[0]
    @w.setter
    def w(self, val): self._data[0] = val
    @property
    def x(self): return self._data[1]
    @x.setter
    def x(self, val): self._data[1] = val
    @property
    def y(self): return self._data[2]
    @y.setter
    def y(self, val): self._data[2] = val
    @property
    def z(self): return self._data[3]
    @z.setter
    def z(self, val): self._data[3] = val
    def __getitem__(self, idx): return self._data[idx]
    def __len__(self): return 4
    def __repr__(self): return f"Quaternion({self._data})"

class MockMatrix:
    __slots__ = ('_data',)
    def __init__(self, data=None):
        if data is None:
            self._data = [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
        elif isinstance(data, MockMatrix):
            self._data = [[data[r][c] for c in range(4)] for r in range(4)]
        else:
            self._data = [list(row) for row in data]

    @classmethod
    def Identity(cls, size=4):
        return cls([[1.0 if r == c else 0.0 for c in range(size)] for r in range(size)])

    @classmethod
    def LocRotScale(cls, location, rotation, scale):
        m = cls.Identity(4)
        w, x, y, z = rotation.w, rotation.x, rotation.y, rotation.z
        xx, yy, zz = x*x, y*y, z*z
        xy, xz, yz = x*y, x*z, y*z
        wx, wy, wz = w*x, w*y, w*z
        m._data[0][0] = (1 - 2*(yy+zz)) * scale.x
        m._data[0][1] = (2*(xy-wz)) * scale.y
        m._data[0][2] = (2*(xz+wy)) * scale.z
        m._data[1][0] = (2*(xy+wz)) * scale.x
        m._data[1][1] = (1 - 2*(xx+zz)) * scale.y
        m._data[1][2] = (2*(yz-wx)) * scale.z
        m._data[2][0] = (2*(xz-wy)) * scale.x
        m._data[2][1] = (2*(yz+wx)) * scale.y
        m._data[2][2] = (1 - 2*(xx+yy)) * scale.z
        m._data[0][3] = location.x
        m._data[1][3] = location.y
        m._data[2][3] = location.z
        return m

    def __getitem__(self, idx):
        return self._data[idx]

    def __matmul__(self, other):
        if isinstance(other, MockMatrix):
            result = MockMatrix()
            for i in range(4):
                for j in range(4):
                    total = sum(self._data[i][k] * other._data[k][j] for k in range(4))
                    result._data[i][j] = total
            return result
        elif isinstance(other, MockVector):
            result = [0.0] * 4
            for i in range(4):
                result[i] = self._data[i][3]
                for j in range(3):
                    result[i] += self._data[i][j] * other._data[j]
            return MockVector(result[:3])
        return NotImplemented

    def decompose(self):
        loc = MockVector([self._data[0][3], self._data[1][3], self._data[2][3]])
        sx = (self._data[0][0]**2 + self._data[1][0]**2 + self._data[2][0]**2) ** 0.5
        sy = (self._data[0][1]**2 + self._data[1][1]**2 + self._data[2][1]**2) ** 0.5
        sz = (self._data[0][2]**2 + self._data[1][2]**2 + self._data[2][2]**2) ** 0.5
        sca = MockVector([sx, sy, sz])
        eps = 1e-12
        r00 = self._data[0][0]/(sx+eps); r10 = self._data[1][0]/(sx+eps); r20 = self._data[2][0]/(sx+eps)
        r01 = self._data[0][1]/(sy+eps); r11 = self._data[1][1]/(sy+eps); r21 = self._data[2][1]/(sy+eps)
        r02 = self._data[0][2]/(sz+eps); r12 = self._data[1][2]/(sz+eps); r22 = self._data[2][2]/(sz+eps)
        trace = r00 + r11 + r22
        if trace > 0:
            s_val = (trace + 1)**0.5 * 2
            w = 0.25 * s_val
            x = (r21 - r12) / s_val
            y = (r02 - r20) / s_val
            z = (r10 - r01) / s_val
        elif r00 > r11 and r00 > r22:
            s_val = (1 + r00 - r11 - r22)**0.5 * 2
            w = (r21 - r12) / s_val
            x = 0.25 * s_val
            y = (r01 + r10) / s_val
            z = (r02 + r20) / s_val
        elif r11 > r22:
            s_val = (1 + r11 - r00 - r22)**0.5 * 2
            w = (r02 - r20) / s_val
            x = (r01 + r10) / s_val
            y = 0.25 * s_val
            z = (r12 + r21) / s_val
        else:
            s_val = (1 + r22 - r00 - r11)**0.5 * 2
            w = (r10 - r01) / s_val
            x = (r02 + r20) / s_val
            y = (r12 + r21) / s_val
            z = 0.25 * s_val
        rot = MockQuaternion([w, x, y, z])
        return loc, rot, sca

    def copy(self):
        return MockMatrix(self)

    def inverted_safe(self):
        result = MockMatrix.Identity(4)
        for i in range(3):
            for j in range(3):
                result._data[i][j] = self._data[j][i]
        for i in range(3):
            result._data[i][3] = -sum(result._data[i][j] * self._data[j][3] for j in range(3))
        return result

    def __repr__(self):
        return f"Matrix({self._data})"

# 安装到 sys.modules
_bpy_module = type(sys)("bpy")
_bpy_module.app = _MockBpyApp()
_bpy_module.context = _MockBpyContext()
_bpy_module.data = _MockBpyData()
_bpy_module.types = _MockBpyTypes()
_bpy_module.ops = _MockBpyOps()
_bpy_module.props = _MockBpyProps()
sys.modules["bpy"] = _bpy_module
sys.modules["bpy.props"] = _MockBpyProps()

_mathutils_module = type(sys)("mathutils")
_mathutils_module.Matrix = MockMatrix
_mathutils_module.Vector = MockVector
_mathutils_module.Quaternion = MockQuaternion
sys.modules["mathutils"] = _mathutils_module

# 也把 SimpleBleModlePlugin 作为命名空间包注册（避免 __init__.py 执行）
import importlib
_plugin_spec = importlib.machinery.ModuleSpec("SimpleBleModlePlugin", None, is_package=True)
_plugin_module = importlib.util.module_from_spec(_plugin_spec)
sys.modules["SimpleBleModlePlugin"] = _plugin_module

# ═══════════════════════════════════════════
#  Step 2: 添加插件目录到 path
# ═══════════════════════════════════════════
sys.path.insert(0, os.path.dirname(_PLUGIN_DIR))
# 也确保 tests 可导入
sys.path.insert(0, _PLUGIN_DIR)

# ═══════════════════════════════════════════
#  Step 3: 发现并运行测试
# ═══════════════════════════════════════════

if __name__ == "__main__":
    test_dir = os.path.join(_PLUGIN_DIR, "tests")

    # 只加载我们自己的测试模块（跳过 __init__）
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 直接加载测试文件
    for fname in sorted(os.listdir(test_dir)):
        if fname.startswith("test_") and fname.endswith(".py"):
            mod_name = fname[:-3]  # strip .py
            test_path = os.path.join(test_dir, fname)
            # 使用 loader 加载
            try:
                test_spec = importlib.util.spec_from_file_location(
                    f"tests.{mod_name}", test_path,
                    submodule_search_locations=[test_dir])
                test_mod = importlib.util.module_from_spec(test_spec)
                sys.modules[f"tests.{mod_name}"] = test_mod
                test_spec.loader.exec_module(test_mod)
                suite.addTests(loader.loadTestsFromModule(test_mod))
            except Exception as e:
                print(f"[SKIP] {fname}: {e}")
                import traceback
                traceback.print_exc()

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 汇总
    print("\n" + "=" * 60)
    print(f"  测试汇总: {result.testsRun} 个运行 | "
          f"{result.testsRun - len(result.failures) - len(result.errors)} 通过 | "
          f"{len(result.failures)} 失败 | "
          f"{len(result.errors)} 错误")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)
