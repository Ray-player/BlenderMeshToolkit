"""
naming.py — 资产命名与规范化模块

提供 UE5 合规命名、4 种命名策略、智能截断等功能。
"""

import re
import os
import hashlib

from .config import MAX_ASSET_NAME_LENGTH

# ── UE5 命名规则编译正则 ──
_UE5_STRIP_CHARS = re.compile(r'[()（）\[\]【】\{\}"\'`<>《》「」『』、，。！：；？～]')
_UE5_REPLACE_CHARS = re.compile(r'[\.\*\?|:/\\ ,;@#$%^&+=\u00b7\u00d7]')
_NORMALIZE_SUFFIX_RE = re.compile(r'__[0-9].*$')

# 长数字阈值
LONG_DIGIT_THRESHOLD = 10


# ═══════════════════════════════════════════
#  公共函数
# ═══════════════════════════════════════════

def sanitize_ue5_name(name: str) -> str:
    """
    UE5 合规命名：删除非法字符，替换分隔符，去重下划线，去首尾下划线。

    Args:
        name: 原始名称

    Returns:
        合规后的名称字符串
    """
    result = _UE5_STRIP_CHARS.sub('', name)
    result = _UE5_REPLACE_CHARS.sub('_', result)
    while '__' in result:
        result = result.replace('__', '_')
    return result.strip('_')


def short_mesh_id(name: str) -> str:
    """
    生成 8 位 MD5 短 ID。

    Args:
        name: mesh data 名称

    Returns:
        格式为 M{hex[:8]} 的短 ID 字符串
    """
    h = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]
    return f"M{h}"


def normalize_mesh_name(name: str, pattern: str = None) -> str:
    """
    根据正则表达式去除 mesh data 名称中的匹配部分。

    Args:
        name: mesh data 原始名称
        pattern: 正则表达式字符串，默认匹配 `__数字...` 后缀

    Returns:
        规范化后的名称
    """
    if pattern is None:
        pattern = r'__[0-9].*$'
    new_name = re.sub(pattern, '', name)
    if new_name and new_name.strip():
        return new_name
    return name


# ═══════════════════════════════════════════
#  私有辅助
# ═══════════════════════════════════════════

def _classify_segment_chars(segment: str) -> tuple[int, int, int]:
    """统计段落中数字、英文、中文字符数量。"""
    digits = sum(1 for c in segment if c.isdigit())
    english = sum(1 for c in segment if c.isalpha() and ord(c) < 128)
    chinese = sum(1 for c in segment if '\u4e00' <= c <= '\u9fff')
    return digits, english, chinese


def _segment_deletion_score(segment: str, index: int, total_segments: int) -> int:
    """
    计算段落删除优先级评分。分越低越优先被保留，越高越先被删除。

    Args:
        segment: 段落文本
        index: 段落索引
        total_segments: 总段落数

    Returns:
        评分整数
    """
    # 位置评分
    if total_segments <= 1:
        pos_score = 1
    else:
        relative_pos = index / (total_segments - 1)
        if relative_pos < 0.33:
            pos_score = 3   # 开头优先删除
        elif relative_pos > 0.67:
            pos_score = 2   # 结尾其次
        else:
            pos_score = 1   # 中间优先保留

    # 类型评分
    digits, english, chinese = _classify_segment_chars(segment)
    total = digits + english + chinese
    if total == 0:
        type_score = 3
    elif digits >= english and digits >= chinese:
        type_score = 3    # 纯数字优先删除
    elif english >= chinese:
        type_score = 2    # 英文其次
    else:
        type_score = 1    # 中文优先保留

    return pos_score * 10 + type_score


def _remove_long_digit_segments(prefix: str) -> str:
    """移除前缀中纯数字且长度 > LONG_DIGIT_THRESHOLD 的段落。"""
    segments = prefix.split('-')
    filtered = []
    for seg in segments:
        clean = seg.strip('_')
        if clean.isdigit() and len(clean) > LONG_DIGIT_THRESHOLD:
            continue
        filtered.append(seg)
    return '-'.join(filtered)


def _shorten_prefix_by_priority(prefix: str, max_length: int) -> str:
    """按优先级删除段落，使前缀不超过 max_length。"""
    segments = prefix.split('-')
    if not segments:
        return prefix[:max_length]

    if len(segments) == 1:
        return segments[0][:max_length]

    scored = [(i, seg, _segment_deletion_score(seg, i, len(segments)))
              for i, seg in enumerate(segments)]
    scored.sort(key=lambda item: (-item[2], -len(item[1])))

    deleted_indices: set[int] = set()
    remaining = segments[:]

    while (len('_'.join(remaining)) > max_length
           and len(deleted_indices) < len(segments) - 1):
        removed = False
        for idx, _, _ in scored:
            if idx in deleted_indices:
                continue
            deleted_indices.add(idx)
            remaining = [s for i, s in enumerate(segments)
                         if i not in deleted_indices]
            removed = True
            break
        if not removed:
            break

    result = '_'.join(remaining).strip('_')
    if len(result) > max_length:
        result = result[:max_length].rstrip('_')
    return result


def _truncate_with_word_priority(text: str, max_length: int) -> str:
    """
    按词优先截断：保留尽可能多的完整下划线分隔词。

    Args:
        text: 待截断文本
        max_length: 最大长度

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text

    parts = [p for p in text.split('_') if p]
    if not parts:
        return text[:max_length].rstrip('_')

    kept = []
    total = 0
    for part in parts:
        extra = len(part) if not kept else len(part) + 1
        if total + extra > max_length:
            break
        kept.append(part)
        total += extra

    if kept:
        return '_'.join(kept).rstrip('_')
    return text[:max_length].rstrip('_')


def _build_shortid_prefix_name(mesh_data_name: str, max_length: int,
                                glb_basename: str = "") -> tuple[str, str]:
    """
    构建 HASH_PREFIX 模式下的资产名：SM_{short_id}_{truncated_prefix}

    Returns:
        (asset_name, short_id)
    """
    short_id_val = short_mesh_id(mesh_data_name)
    raw_prefix = (mesh_data_name.split('__')[0]
                  if '__' in mesh_data_name else mesh_data_name)
    sanitized = sanitize_ue5_name(raw_prefix)
    sanitized = _remove_long_digit_segments(sanitized)
    if not sanitized:
        sanitized = glb_basename or "Mesh"

    base = f"SM_{short_id_val}"
    if max_length <= len(base):
        return base[:max_length].rstrip('_'), short_id_val

    suffix_budget = max_length - len(base) - 1
    short_suffix = _truncate_with_word_priority(sanitized, suffix_budget)
    if short_suffix:
        return f"{base}_{short_suffix}", short_id_val
    return base, short_id_val


# ═══════════════════════════════════════════
#  资产命名主函数
# ═══════════════════════════════════════════

def generate_mesh_asset_name(
    mesh_data_name: str,
    mode: str = "HASH_PREFIX",
    max_length: int = MAX_ASSET_NAME_LENGTH,
    glb_basename: str = "",
) -> tuple[str, str]:
    """
    根据命名策略生成 StaticMesh 资产名称。

    Args:
        mesh_data_name: mesh data 块名称
        mode: 命名模式 (ORIGINAL / HASH / HASH_PREFIX)
        max_length: 资产名最大长度
        glb_basename: GLB 导出文件基名（HASH 模式使用）

    Returns:
        (asset_name, short_id) 元组
    """
    short_id_val = short_mesh_id(mesh_data_name)
    sm_prefix = "SM_"
    hash_suffix = f"_{short_id_val}"
    fixed_overhead = len(sm_prefix) + len(hash_suffix)
    max_prefix_len = max_length - fixed_overhead

    if mode == "ORIGINAL":
        clean = sanitize_ue5_name(mesh_data_name)
        if len(sm_prefix) + len(clean) > max_length:
            clean = clean[:max_prefix_len]
        name = f"{sm_prefix}{clean}"

    elif mode == "HASH":
        basename = glb_basename or os.path.splitext(
            os.path.basename(mesh_data_name))[0]
        name = f"{sm_prefix}{basename}_{short_id_val}"

    elif mode == "HASH_PREFIX":
        name, short_id_val = _build_shortid_prefix_name(
            mesh_data_name, max_length, glb_basename)

    else:
        raise ValueError(f"未知的命名模式: {mode}")

    # 最终截断保护
    if len(name) > max_length:
        name = name[:max_length].rstrip('_')

    return name, short_id_val
