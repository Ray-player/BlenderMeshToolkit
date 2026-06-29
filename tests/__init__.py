"""
tests/__init__.py — Mock 安装 + 模块加载辅助

在导入任何源模块之前安装 bpy/mathutils mock，
然后通过 importlib 加载各个源模块（绕过 __init__.py 的 bpy 导入）。
"""

import sys
import os
import importlib
import importlib.util
import importlib.machinery

# ═══════════════════════════════════════════
#  bpy mock
# ═══════════════════════════════════════════
class _MockVersion:
    def __init__(self, ver=(4, 0, 0)): self._ver = ver
    def __ge__(self, other): return self._ver >= other
    def __getitem__(self, idx): return self._ver[idx]

class _MockBpyProps:
    @staticmethod
    def FloatProperty(**kw): return kw.get("default", 0.0)
    @staticmethod
    def BoolProperty(**kw): return kw.get("default", False)
    @staticmethod
    def EnumProperty(**kw): return kw.get("default", "")
    @staticmethod
    def StringProperty(**kw): return kw.get("default", "")
    @staticmethod
    def IntProperty(**kw): return kw.get("default", 0)

class _MockBpy:
    class app:
        version = _MockVersion()
    class context:
        pass
    class data:
        pass
    class types:
        class Panel: pass
        class Operator: pass
        class AddonPreferences: pass
    class ops:
        pass
    props = _MockBpyProps()

# ═══════════════════════════════════════════
#  mathutils mock
# ═══════════════════════════════════════════
class MockVector:
    __slots__ = ('_data',)
    def __init__(self, data):
        if isinstance(data, MockVector): self._data = list(data._data)
        else: self._data = list(data)
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
        if isinstance(data, MockQuaternion): self._data = list(data._data)
        else: self._data = list(data)
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

    def __getitem__(self, idx): return self._data[idx]

    def __matmul__(self, other):
        if isinstance(other, MockMatrix):
            result = MockMatrix()
            for i in range(4):
                for j in range(4):
                    result._data[i][j] = sum(self._data[i][k] * other._data[k][j] for k in range(4))
            return result
        elif isinstance(other, MockVector):
            result = [0.0]*4
            for i in range(4):
                result[i] = self._data[i][3] + sum(self._data[i][j] * other._data[j] for j in range(3))
            return MockVector(result[:3])
        return NotImplemented

    def decompose(self):
        loc = MockVector([self._data[0][3], self._data[1][3], self._data[2][3]])
        sx = (self._data[0][0]**2 + self._data[1][0]**2 + self._data[2][0]**2)**0.5
        sy = (self._data[0][1]**2 + self._data[1][1]**2 + self._data[2][1]**2)**0.5
        sz = (self._data[0][2]**2 + self._data[1][2]**2 + self._data[2][2]**2)**0.5
        sca = MockVector([sx, sy, sz])
        eps = 1e-12
        r00=self._data[0][0]/(sx+eps); r10=self._data[1][0]/(sx+eps); r20=self._data[2][0]/(sx+eps)
        r01=self._data[0][1]/(sy+eps); r11=self._data[1][1]/(sy+eps); r21=self._data[2][1]/(sy+eps)
        r02=self._data[0][2]/(sz+eps); r12=self._data[1][2]/(sz+eps); r22=self._data[2][2]/(sz+eps)
        trace = r00 + r11 + r22
        if trace > 0:
            sv = (trace+1)**0.5*2; w=0.25*sv; x=(r21-r12)/sv; y=(r02-r20)/sv; z=(r10-r01)/sv
        elif r00 > r11 and r00 > r22:
            sv = (1+r00-r11-r22)**0.5*2; w=(r21-r12)/sv; x=0.25*sv; y=(r01+r10)/sv; z=(r02+r20)/sv
        elif r11 > r22:
            sv = (1+r11-r00-r22)**0.5*2; w=(r02-r20)/sv; x=(r01+r10)/sv; y=0.25*sv; z=(r12+r21)/sv
        else:
            sv = (1+r22-r00-r11)**0.5*2; w=(r10-r01)/sv; x=(r02+r20)/sv; y=(r12+r21)/sv; z=0.25*sv
        return loc, MockQuaternion([w,x,y,z]), sca

    def copy(self): return MockMatrix(self)

    def inverted_safe(self):
        result = MockMatrix.Identity(4)
        for i in range(3):
            for j in range(3):
                result._data[i][j] = self._data[j][i]
        for i in range(3):
            result._data[i][3] = -sum(result._data[i][j] * self._data[j][3] for j in range(3))
        return result

    def __repr__(self): return f"Matrix({self._data})"

# ── 安装到 sys.modules ──
if "bpy" not in sys.modules:
    sys.modules["bpy"] = _MockBpy()
if "bpy.props" not in sys.modules:
    sys.modules["bpy.props"] = _MockBpyProps()
if "mathutils" not in sys.modules:
    _mu = type(sys)("mathutils")
    _mu.Matrix = MockMatrix
    _mu.Vector = MockVector
    _mu.Quaternion = MockQuaternion
    sys.modules["mathutils"] = _mu

# ── 模块加载辅助 ──
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(module_name: str):
    """加载 SimpleBleModlePlugin 下的子模块（绕过 __init__.py）。"""
    full_name = f"SimpleBleModlePlugin.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    # 确保包命名空间存在但不触发 __init__.py
    if "SimpleBleModlePlugin" not in sys.modules:
        pkg_spec = importlib.machinery.ModuleSpec(
            "SimpleBleModlePlugin", None, is_package=True)
        pkg = importlib.util.module_from_spec(pkg_spec)
        sys.modules["SimpleBleModlePlugin"] = pkg

    filepath = os.path.join(_PLUGIN_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    # 也注册为包的属性
    sys.modules["SimpleBleModlePlugin"].__dict__[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# 预加载依赖链（按拓扑顺序）
_config = _load_module("config")
_logger = _load_module("logger")
_naming = _load_module("naming")
_coordinate = _load_module("coordinate")
_mesh_core = _load_module("mesh_core")
_export_core = _load_module("export_core")
